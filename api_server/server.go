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

	designReq := protein_pipeline.DesignRequest{TargetProtein: "GFP", NumCandidates: 8, Rounds: 3}
	if strings.Contains(content, "迭代") {
		designReq.Rounds = 5
	}
	if strings.Contains(content, "筛选") {
		designReq.NumCandidates = 12
	}
	result := s.pipeline.Run(designReq)

	answer := fmt.Sprintf("已完成自动蛋白设计流程：生成 %d 条候选，自动筛选并评分，最佳序列 %s，得分 %.3f。",
		result.TotalGenerated, result.BestCandidate.ID, result.BestCandidate.Score)

	writeJSON(w, map[string]any{
		"id":      fmt.Sprintf("chatcmpl-%d", time.Now().Unix()),
		"object":  "chat.completion",
		"created": time.Now().Unix(),
		"model":   "esm3-protein-design-agent",
		"choices": []any{map[string]any{
			"index": 0,
			"message": map[string]string{
				"role":    "assistant",
				"content": answer,
			},
			"finish_reason": "stop",
		}},
	})
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
