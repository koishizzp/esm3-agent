package api_server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"esm3-agent/protein_pipeline"
)

type runner interface {
	Run(req protein_pipeline.DesignRequest) protein_pipeline.DesignResult
}

type Server struct {
	port          string
	pipeline      runner
	httpClient    *http.Client
	upstreamURL   string
	upstreamKey   string
	upstreamModel string
}

func NewServer(port string, pipeline runner) *Server {
	if port == "" {
		port = ":8080"
	}
	return &Server{
		port:          port,
		pipeline:      pipeline,
		httpClient:    &http.Client{Timeout: 60 * time.Second},
		upstreamURL:   strings.TrimSpace(os.Getenv("OPENAI_BASE_URL")),
		upstreamKey:   strings.TrimSpace(os.Getenv("OPENAI_API_KEY")),
		upstreamModel: strings.TrimSpace(os.Getenv("OPENAI_MODEL")),
	}
}

func (s *Server) Port() string { return s.port }

func (s *Server) Start() error {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.health)
	mux.HandleFunc("/v1/models", s.models)
	mux.HandleFunc("/v1/inference/design", s.design)
	mux.HandleFunc("/v1/chat/completions", s.chat)
	mux.HandleFunc("/v1/debug/provider", s.provider)
	mux.HandleFunc("/", s.web)
	return http.ListenAndServe(s.port, mux)
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	_, _ = w.Write([]byte("OK"))
}

func (s *Server) models(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, map[string]any{
		"data": []map[string]string{{"id": "esm3-protein-design-agent", "object": "model"}},
	})
}

func (s *Server) design(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req protein_pipeline.DesignRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	result := s.pipeline.Run(req)
	writeJSON(w, result)
}

func (s *Server) chat(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		query := strings.TrimSpace(r.URL.Query().Get("q"))
		if query == "" {
			help := "该接口是 OpenAI 兼容格式，建议使用 POST JSON。\n"
			help += "浏览器快速体验可用：/v1/chat/completions?q=请自动设计GFP并迭代"
			writeChatCompletion(w, help, nil)
			return
		}
		respondWithPrompt(s, w, strings.ToLower(query))
		return
	}

	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	var req struct {
		Messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	content := latestUserContent(req.Messages)

	if s.upstreamEnabled() {
		s.proxyChat(w, payload, content)
		return
	}

	respondWithPrompt(s, w, strings.ToLower(content))
}

func latestUserContent(messages []struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}) string {
	content := ""
	for i := len(messages) - 1; i >= 0; i-- {
		if messages[i].Role == "user" {
			content = messages[i].Content
			break
		}
	}
	return content
}

func (s *Server) provider(w http.ResponseWriter, _ *http.Request) {
	masked := ""
	if s.upstreamKey != "" {
		if len(s.upstreamKey) <= 8 {
			masked = "****"
		} else {
			masked = s.upstreamKey[:4] + "..." + s.upstreamKey[len(s.upstreamKey)-4:]
		}
	}
	writeJSON(w, map[string]any{
		"mode":             map[bool]string{true: "upstream", false: "local-mock"}[s.upstreamEnabled()],
		"upstream_enabled": s.upstreamEnabled(),
		"upstream_url":     s.upstreamURL,
		"upstream_model":   s.upstreamModel,
		"api_key_masked":   masked,
	})
}

func (s *Server) upstreamEnabled() bool {
	return s.upstreamURL != "" && s.upstreamKey != ""
}

func (s *Server) proxyChat(w http.ResponseWriter, payload map[string]any, userContent string) {
	if s.upstreamModel != "" {
		payload["model"] = s.upstreamModel
	}
	payload["messages"] = s.buildUpstreamMessages(payload["messages"], userContent)
	patched, _ := json.Marshal(payload)

	upstream := strings.TrimRight(s.upstreamURL, "/") + "/chat/completions"
	req, err := http.NewRequest(http.MethodPost, upstream, bytes.NewReader(patched))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+s.upstreamKey)

	resp, err := s.httpClient.Do(req)
	if err != nil {
		http.Error(w, "upstream request failed: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func (s *Server) buildUpstreamMessages(raw any, userContent string) []map[string]string {
	system := "你是 ESM3 蛋白设计助手。你的职责是基于给定设计结果解释分数、候选优先级与下一步实验建议，不要偏离 ESM3 场景。"
	system += "当用户询问候选分数时，优先解释 best_candidate.score、候选排序与 round 配置；需要完整明细时提醒调用 POST /v1/inference/design。"

	messages := []map[string]string{{"role": "system", "content": system}}

	if existing, ok := raw.([]any); ok {
		for _, msg := range existing {
			m, ok := msg.(map[string]any)
			if !ok {
				continue
			}
			role, _ := m["role"].(string)
			content, _ := m["content"].(string)
			if role == "" || content == "" {
				continue
			}
			messages = append(messages, map[string]string{"role": role, "content": content})
		}
	}

	content := strings.ToLower(strings.TrimSpace(userContent))
	if content != "" && !strings.Contains(content, "help") && !strings.Contains(content, "帮助") {
		designReq := inferDesignRequest(content)
		result := s.pipeline.Run(designReq)
		summary := map[string]any{
			"request":         designReq,
			"best_candidate":  result.BestCandidate,
			"total_generated": result.TotalGenerated,
			"rounds":          result.Rounds,
			"candidates":      result.AllCandidates,
		}
		if b, err := json.Marshal(summary); err == nil {
			messages = append(messages, map[string]string{
				"role":    "system",
				"content": "以下是本次 ESM3 设计执行结果（JSON），请严格基于这些字段回答：\n" + string(b),
			})
		}
	}

	return messages
}

func inferDesignRequest(content string) protein_pipeline.DesignRequest {
	designReq := protein_pipeline.DesignRequest{TargetProtein: "GFP", NumCandidates: 8, Rounds: 3}
	if strings.Contains(content, "迭代") {
		designReq.Rounds = 5
	}
	if strings.Contains(content, "筛选") {
		designReq.NumCandidates = 12
	}
	if strings.Contains(content, "gsg") {
		designReq.RequiredMotif = "GSG"
	}
	if strings.Contains(content, "不能") && strings.Contains(content, "c") {
		designReq.ForbiddenAAs = "C"
	}
	return designReq
}

func respondWithPrompt(s *Server, w http.ResponseWriter, content string) {
	if strings.TrimSpace(content) == "" || strings.Contains(content, "help") || strings.Contains(content, "帮助") {
		help := "这是 OpenAI 兼容响应格式，业务文本在 choices[0].message.content。\n\n"
		help += "如果你想拿到完整设计结果（候选列表、分数、最佳序列），请调用：POST /v1/inference/design"
		writeChatCompletion(w, help, nil)
		return
	}

	designReq := inferDesignRequest(content)
	result := s.pipeline.Run(designReq)
	preview := sequencePreview(result.BestCandidate.Sequence)
	answer := fmt.Sprintf("已完成自动蛋白设计流程：生成 %d 条候选，自动筛选并评分，最佳候选 %s（score=%.3f，seq=%s）。\n\n如需全部候选明细，请调用 POST /v1/inference/design。",
		result.TotalGenerated,
		result.BestCandidate.ID,
		result.BestCandidate.Score,
		preview,
	)

	writeChatCompletion(w, answer, map[string]any{
		"best_candidate":  result.BestCandidate,
		"total_generated": result.TotalGenerated,
		"rounds":          result.Rounds,
	})
}

func writeChatCompletion(w http.ResponseWriter, content string, extra map[string]any) {
	resp := map[string]any{
		"id":      fmt.Sprintf("chatcmpl-%d", time.Now().Unix()),
		"object":  "chat.completion",
		"created": time.Now().Unix(),
		"model":   "esm3-protein-design-agent",
		"choices": []any{map[string]any{
			"index": 0,
			"message": map[string]string{
				"role":    "assistant",
				"content": content,
			},
			"finish_reason": "stop",
		}},
	}
	for k, v := range extra {
		resp[k] = v
	}
	writeJSON(w, resp)
}

func sequencePreview(seq string) string {
	if len(seq) <= 24 {
		return seq
	}
	return seq[:12] + "..." + seq[len(seq)-12:]
}

func (s *Server) web(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	content, err := os.ReadFile("web_ui/index.html")
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_, _ = w.Write(content)
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}
