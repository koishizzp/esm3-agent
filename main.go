package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

// ============================================================
// 配置
// ============================================================

type Config struct {
	PythonPath    string
	ScriptDir     string
	Port          string
	Timeout       time.Duration
	UpstreamAPI   string // 上游LLM API（用于意图理解）
	UpstreamKey   string
	EnableLogging bool
}

func NewConfig() *Config {
	return &Config{
		PythonPath:    getEnv("PYTHON_PATH", "/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python"),
		ScriptDir:     getEnv("SCRIPT_DIR", "/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction"),
		Port:          getEnv("PORT", ":8080"),
		Timeout:       5 * time.Minute,
		UpstreamAPI:   getEnv("UPSTREAM_API", "https://api.anthropic.com/v1/messages"),
		UpstreamKey:   getEnv("UPSTREAM_KEY", ""),
		EnableLogging: true,
	}
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// ============================================================
// 使用日志
// ============================================================

type UsageLogger struct {
	logFile string
}

func NewUsageLogger(logFile string) *UsageLogger {
	return &UsageLogger{logFile: logFile}
}

func (l *UsageLogger) Log(userMsg, agentResp string, tool string, duration time.Duration) {
	entry := fmt.Sprintf("[%s] User: %s | Tool: %s | Duration: %.2fs | Response: %s\n",
		time.Now().Format("2006-01-02 15:04:05"),
		truncate(userMsg, 50),
		tool,
		duration.Seconds(),
		truncate(agentResp, 100))
	
	f, err := os.OpenFile(l.logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("❌ 写入使用日志失败: %v", err)
		return
	}
	defer f.Close()
	
	f.WriteString(entry)
}

// ============================================================
// 工具定义（Function Calling）
// ============================================================

var ESM3Tools = []map[string]interface{}{
	{
		"name":        "check_environment",
		"description": "检查ESM3环境状态，包括Python、PyTorch、CUDA、ESM3模块",
		"input_schema": map[string]interface{}{
			"type":       "object",
			"properties": map[string]interface{}{},
		},
	},
	{
		"name":        "analyze_sequence",
		"description": "分析蛋白质序列的基本特性，包括长度、氨基酸组成、疏水性、电荷等",
		"input_schema": map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"sequence": map[string]string{
					"type":        "string",
					"description": "要分析的蛋白质序列（一字母代码）",
				},
			},
			"required": []string{"sequence"},
		},
	},
	{
		"name":        "generate_protein",
		"description": "使用ESM3模型生成新的GFP蛋白质序列（需要2-5分钟）",
		"input_schema": map[string]interface{}{
			"type":       "object",
			"properties": map[string]interface{}{},
		},
	},
}

// ============================================================
// ESM3 Client
// ============================================================

type ESM3Client struct {
	config *Config
}

func NewESM3Client(config *Config) *ESM3Client {
	return &ESM3Client{config: config}
}

func (c *ESM3Client) runPython(script string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), c.config.Timeout)
	defer cancel()
	
	cmd := exec.CommandContext(ctx, c.config.PythonPath, "-c", script)
	var out, stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr
	
	if err := cmd.Run(); err != nil {
		if ctx.Err() == context.DeadlineExceeded {
			return "", fmt.Errorf("timeout after %v", c.config.Timeout)
		}
		return "", fmt.Errorf("%v", stderr.String())
	}
	
	return strings.TrimSpace(out.String()), nil
}

func (c *ESM3Client) CheckEnvironment() (string, error) {
	script := `
import sys
print(f"Python: {sys.version.split()[0]}")
try:
    import torch
    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
except:
    print("PyTorch: Not installed")
try:
    import esm
    print("ESM3: Installed")
except:
    print("ESM3: Not installed")
`
	return c.runPython(script)
}

func (c *ESM3Client) AnalyzeSequence(sequence string) (string, error) {
	script := fmt.Sprintf(`
seq = "%s"
length = len(seq)
aa_counts = {}
for aa in seq:
    aa_counts[aa] = aa_counts.get(aa, 0) + 1
hydrophobic = "AILMFWYV"
hydrophobic_ratio = sum(1 for aa in seq if aa in hydrophobic) / length if length > 0 else 0
positive = "KR"
negative = "DE"
net_charge = sum(1 for aa in seq if aa in positive) - sum(1 for aa in seq if aa in negative)
print(f"长度: {length} aa")
print(f"种类: {len(aa_counts)} 种")
print(f"疏水性: {hydrophobic_ratio:.2f}")
print(f"净电荷: {net_charge:+d}")
if aa_counts:
    most = max(aa_counts, key=aa_counts.get)
    print(f"最常见: {most} ({aa_counts[most]}次, {aa_counts[most]/length*100:.1f}%%)")
`, sequence)
	return c.runPython(script)
}

func (c *ESM3Client) GenerateProtein() (string, error) {
	script := fmt.Sprintf(`
import sys
sys.path.insert(0, '%s')
try:
    from utils.esm_wrapper import ESM3Generator
    import pickle
    with open('%s/data/prompts/gfp_prompt.pkl', 'rb') as f:
        prompt = pickle.load(f)
    print("开始生成...")
    generator = ESM3Generator()
    result = generator.chain_of_thought_generation(
        prompt, structure_steps=200, sequence_steps=150, temperature=0.7
    )
    print(f"生成成功! 序列: {result.sequence[:60]}... 长度: {len(result.sequence)}")
except Exception as e:
    print(f"错误: {e}")
`, c.config.ScriptDir, c.config.ScriptDir)
	return c.runPython(script)
}

// ============================================================
// LLM Client（用于意图理解）
// ============================================================

type LLMClient struct {
	apiURL string
	apiKey string
}

func NewLLMClient(apiURL, apiKey string) *LLMClient {
	return &LLMClient{apiURL: apiURL, apiKey: apiKey}
}

func (l *LLMClient) CallWithTools(userMessage string, tools []map[string]interface{}) (string, map[string]interface{}, error) {
	// 如果没有配置上游API，使用简单匹配
	if l.apiKey == "" {
		return l.simpleMatch(userMessage)
	}
	
	// TODO: 实现真正的Function Calling
	// 这里需要调用Claude/GPT的Function Calling API
	return l.simpleMatch(userMessage)
}

func (l *LLMClient) simpleMatch(msg string) (string, map[string]interface{}, error) {
	msg = strings.ToLower(msg)
	
	if strings.Contains(msg, "check") || strings.Contains(msg, "检查") || strings.Contains(msg, "环境") {
		return "check_environment", nil, nil
	}
	
	if strings.Contains(msg, "generate") || strings.Contains(msg, "生成") {
		return "generate_protein", nil, nil
	}
	
	if strings.Contains(msg, "analyze") || strings.Contains(msg, "分析") {
		sequence := extractSequence(msg)
		if sequence != "" {
			return "analyze_sequence", map[string]interface{}{"sequence": sequence}, nil
		}
	}
	
	return "chat", nil, nil
}

// ============================================================
// Agent
// ============================================================

type ESM3Agent struct {
	esm3Client  *ESM3Client
	llmClient   *LLMClient
	usageLogger *UsageLogger
}

func NewESM3Agent(config *Config) *ESM3Agent {
	return &ESM3Agent{
		esm3Client:  NewESM3Client(config),
		llmClient:   NewLLMClient(config.UpstreamAPI, config.UpstreamKey),
		usageLogger: NewUsageLogger("logs/usage.log"),
	}
}

func (a *ESM3Agent) HandleRequest(userMessage string) (string, error) {
	start := time.Now()
	
	// 步骤1: 使用LLM理解意图，决定调用哪个工具
	toolName, toolInput, err := a.llmClient.CallWithTools(userMessage, ESM3Tools)
	if err != nil {
		return "", err
	}
	
	log.Printf("🤖 Agent决策: tool=%s, input=%v", toolName, toolInput)
	
	// 步骤2: 执行工具
	var response string
	switch toolName {
	case "check_environment":
		response, err = a.esm3Client.CheckEnvironment()
	case "analyze_sequence":
		if seq, ok := toolInput["sequence"].(string); ok {
			response, err = a.esm3Client.AnalyzeSequence(seq)
		}
	case "generate_protein":
		response, err = a.esm3Client.GenerateProtein()
	default:
		response = a.getHelp()
	}
	
	if err != nil {
		response = fmt.Sprintf("工具执行错误: %v", err)
	}
	
	// 记录使用日志
	duration := time.Since(start)
	a.usageLogger.Log(userMessage, response, toolName, duration)
	
	return response, nil
}

func (a *ESM3Agent) getHelp() string {
	return `ESM3 Agent - 蛋白质AI助手

功能:
1. 环境检查: "检查环境"
2. 序列分析: "分析序列 MKGEELF..."
3. 蛋白质生成: "生成蛋白质"

试试看！`
}

// ============================================================
// HTTP Server
// ============================================================

type Server struct {
	agent  *ESM3Agent
	config *Config
}

func NewServer(config *Config) *Server {
	return &Server{
		agent:  NewESM3Agent(config),
		config: config,
	}
}

func (s *Server) chatHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
	
	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}
	
	body, _ := io.ReadAll(r.Body)
	defer r.Body.Close()
	
	var req struct {
		Messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	}
	json.Unmarshal(body, &req)
	
	var userMessage string
	for i := len(req.Messages) - 1; i >= 0; i-- {
		if req.Messages[i].Role == "user" {
			userMessage = req.Messages[i].Content
			break
		}
	}
	
	log.Printf("📨 收到请求: %s", truncate(userMessage, 50))
	
	response, err := s.agent.HandleRequest(userMessage)
	if err != nil {
		response = fmt.Sprintf("错误: %v", err)
	}
	
	log.Printf("📤 返回响应: %s", truncate(response, 50))
	
	result := map[string]interface{}{
		"id":      fmt.Sprintf("esm3-%d", time.Now().Unix()),
		"object":  "chat.completion",
		"created": time.Now().Unix(),
		"model":   "esm3-agent-v1",
		"choices": []map[string]interface{}{
			{
				"index": 0,
				"message": map[string]string{
					"role":    "assistant",
					"content": response,
				},
				"finish_reason": "stop",
			},
		},
	}
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

func (s *Server) modelsHandler(w http.ResponseWriter, r *http.Request) {
	models := map[string]interface{}{
		"data": []map[string]string{
			{"id": "esm3-agent-v1", "object": "model"},
		},
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(models)
}

func (s *Server) healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Write([]byte("OK"))
}

func (s *Server) Start() error {
	http.HandleFunc("/v1/chat/completions", s.chatHandler)
	http.HandleFunc("/v1/models", s.modelsHandler)
	http.HandleFunc("/health", s.healthHandler)
	
	log.Printf("\n%s", strings.Repeat("=", 60))
	log.Printf("🚀 ESM3 Agent Server v2 (Enhanced)")
	log.Printf("%s", strings.Repeat("=", 60))
	log.Printf("📡 API: http://localhost%s/v1/chat/completions", s.config.Port)
	log.Printf("📊 使用日志: logs/usage.log")
	log.Printf("%s\n", strings.Repeat("=", 60))
	
	return http.ListenAndServe(s.config.Port, nil)
}

// ============================================================
// Utils
// ============================================================

func truncate(s string, length int) string {
	if len(s) <= length {
		return s
	}
	return s[:length] + "..."
}

func extractSequence(text string) string {
	for _, word := range strings.Fields(text) {
		if len(word) > 10 && isProteinSeq(word) {
			return strings.ToUpper(word)
		}
	}
	return ""
}

func isProteinSeq(s string) bool {
	validAA := "ACDEFGHIKLMNPQRSTVWY"
	for _, c := range strings.ToUpper(s) {
		if !strings.ContainsRune(validAA, c) {
			return false
		}
	}
	return true
}

// ============================================================
// Main
// ============================================================

func main() {
	config := NewConfig()
	
	log.Println("🔬 检查ESM3环境...")
	client := NewESM3Client(config)
	if env, err := client.CheckEnvironment(); err == nil {
		log.Println(env)
	}
	
	server := NewServer(config)
	
	go func() {
		sigint := make(chan os.Signal, 1)
		signal.Notify(sigint, os.Interrupt, syscall.SIGTERM)
		<-sigint
		log.Println("\n🛑 关闭服务...")
		os.Exit(0)
	}()
	
	if err := server.Start(); err != nil {
		log.Fatal(err)
	}
}
