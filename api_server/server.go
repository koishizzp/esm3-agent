package api_server

import (
	"encoding/json"
	"fmt"
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
	port     string
	pipeline runner
}

func NewServer(port string, pipeline runner) *Server {
	if port == "" {
		port = ":8080"
	}
	return &Server{port: port, pipeline: pipeline}
}

func (s *Server) Port() string { return s.port }

func (s *Server) Start() error {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.health)
	mux.HandleFunc("/v1/models", s.models)
	mux.HandleFunc("/v1/inference/design", s.design)
	mux.HandleFunc("/v1/chat/completions", s.chat)
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
	var req struct {
		Messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	content := ""
	for i := len(req.Messages) - 1; i >= 0; i-- {
		if req.Messages[i].Role == "user" {
			content = strings.ToLower(req.Messages[i].Content)
			break
		}
	}
	respondWithPrompt(s, w, content)
}

func respondWithPrompt(s *Server, w http.ResponseWriter, content string) {
	if strings.TrimSpace(content) == "" || strings.Contains(content, "help") || strings.Contains(content, "帮助") {
		help := "这是 OpenAI 兼容响应格式，业务文本在 choices[0].message.content。\n\n"
		help += "如果你想拿到完整设计结果（候选列表、分数、最佳序列），请调用：POST /v1/inference/design"
		writeChatCompletion(w, help, nil)
		return
	}

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
