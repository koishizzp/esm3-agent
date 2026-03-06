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
	DBPath        string
	Timeout       time.Duration
	UpstreamAPI   string // 上游LLM API（用于意图理解）
	UpstreamKey   string
	UpstreamModel string
	EnableLogging bool
}

func NewConfig() *Config {
	return &Config{
		PythonPath:    getEnv("PYTHON_PATH", "/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python"),
		ScriptDir:     getEnv("SCRIPT_DIR", "/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction"),
		Port:          getEnv("PORT", ":8080"),
		DBPath:        getEnv("DB_PATH", "./data/sequences.db"),
		Timeout:       5 * time.Minute,
		UpstreamAPI:   getEnv("UPSTREAM_API", "https://api.openai.com/v1/chat/completions"),
		UpstreamKey:   getEnv("UPSTREAM_KEY", ""),
		UpstreamModel: getEnv("UPSTREAM_MODEL", "gpt-4o-mini"),
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
		"parameters": map[string]interface{}{
			"type":       "object",
			"properties": map[string]interface{}{},
		},
	},
	{
		"name":        "analyze_sequence",
		"description": "分析蛋白质序列，可直接传序列，也可从文件或SQLite数据库读取",
		"parameters": map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"sequence": map[string]string{
					"type":        "string",
					"description": "要分析的蛋白质序列（一字母代码，直接输入模式）",
				},
				"source": map[string]string{
					"type":        "string",
					"description": "序列来源: direct(默认), file, database",
				},
				"file_path": map[string]string{
					"type":        "string",
					"description": "当source=file时，填写本地文件路径，支持FASTA或纯文本",
				},
				"db_path": map[string]string{
					"type":        "string",
					"description": "当source=database时，SQLite文件路径，不填则使用默认DB_PATH",
				},
				"query": map[string]string{
					"type":        "string",
					"description": "当source=database时，SQL查询语句（需返回至少1列序列）",
				},
			},
			"required": []string{},
		},
	},
	{
		"name":        "generate_protein",
		"description": "使用ESM3模型生成新的GFP蛋白质序列（支持长度、motif、禁用氨基酸等约束）",
		"parameters": map[string]interface{}{
			"type": "object",
			"properties": map[string]interface{}{
				"min_length":    map[string]string{"type": "integer", "description": "最小长度"},
				"max_length":    map[string]string{"type": "integer", "description": "最大长度"},
				"must_include":  map[string]string{"type": "string", "description": "必须包含的短motif，如GSG"},
				"forbidden_aas": map[string]string{"type": "string", "description": "禁止出现的氨基酸字母集合，如CM"},
				"temperature":   map[string]string{"type": "number", "description": "采样温度，默认0.7"},
			},
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
	cleanSeq := strings.ToUpper(strings.TrimSpace(sequence))
	if !isProteinSeq(cleanSeq) {
		return "", fmt.Errorf("invalid protein sequence: only ACDEFGHIKLMNPQRSTVWY is allowed")
	}

	script := fmt.Sprintf(`
seq = %q
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
`, cleanSeq)
	return c.runPython(script)
}

func extractSequenceFromFile(filePath string) (string, error) {
	content, err := os.ReadFile(filePath)
	if err != nil {
		return "", err
	}

	lines := strings.Split(string(content), "\n")
	var b strings.Builder
	for _, raw := range lines {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, ">") || strings.HasPrefix(line, ";") {
			continue
		}
		for _, ch := range line {
			if ch >= 'a' && ch <= 'z' {
				ch = ch - 'a' + 'A'
			}
			if strings.ContainsRune("ACDEFGHIKLMNPQRSTVWY", ch) {
				b.WriteRune(ch)
			}
		}
	}

	seq := b.String()
	if seq == "" {
		return "", fmt.Errorf("未在文件中解析到蛋白序列")
	}
	return seq, nil
}

func (c *ESM3Client) AnalyzeSequenceFromSource(source, sequence, filePath, dbPath, query string) (string, error) {
	switch strings.ToLower(strings.TrimSpace(source)) {
	case "", "direct":
		return c.AnalyzeSequence(sequence)
	case "file":
		seq, err := extractSequenceFromFile(filePath)
		if err != nil {
			return "", fmt.Errorf("读取文件失败: %w", err)
		}
		return c.AnalyzeSequence(seq)
	case "database":
		if strings.TrimSpace(dbPath) == "" {
			dbPath = c.config.DBPath
		}
		if strings.TrimSpace(query) == "" {
			query = "SELECT sequence FROM sequences LIMIT 1"
		}
		script := fmt.Sprintf(`
import sqlite3
db_path = %q
query = %q
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(query)
row = cur.fetchone()
conn.close()
if not row:
    raise RuntimeError("query returned empty result")
print(str(row[0]).strip())
`, dbPath, query)
		seq, err := c.runPython(script)
		if err != nil {
			return "", fmt.Errorf("数据库读取失败: %w", err)
		}
		return c.AnalyzeSequence(seq)
	default:
		return "", fmt.Errorf("不支持的source: %s（可选 direct/file/database）", source)
	}
}

func (c *ESM3Client) GenerateProtein(minLength, maxLength int, mustInclude, forbiddenAAs string, temperature float64) (string, error) {
	if temperature <= 0 {
		temperature = 0.7
	}
	if minLength < 0 {
		minLength = 0
	}
	if maxLength < 0 {
		maxLength = 0
	}
	mustInclude = strings.ToUpper(strings.TrimSpace(mustInclude))
	forbiddenAAs = strings.ToUpper(strings.TrimSpace(forbiddenAAs))

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
    result = generator.chain_of_thought_generation(prompt, structure_steps=200, sequence_steps=150, temperature=%f)
    seq = str(result.sequence)
    if %d > 0 and len(seq) < %d:
        raise RuntimeError(f"长度不满足最小要求: {len(seq)} < %d")
    if %d > 0 and len(seq) > %d:
        raise RuntimeError(f"长度超过最大要求: {len(seq)} > %d")
    motif = %q
    if motif and motif not in seq:
        raise RuntimeError(f"序列未包含指定motif: {motif}")
    forbidden = set(%q)
    bad = sorted(set([aa for aa in seq if aa in forbidden]))
    if bad:
        raise RuntimeError(f"序列包含禁用氨基酸: {''.join(bad)}")
    print(f"生成成功! 序列: {seq[:60]}... 长度: {len(seq)}")
except Exception as e:
    print(f"错误: {e}")
`, c.config.ScriptDir, c.config.ScriptDir, temperature, minLength, minLength, minLength, maxLength, maxLength, maxLength, mustInclude, forbiddenAAs)
	return c.runPython(script)
}

// ============================================================
// LLM Client（用于意图理解）
// ============================================================

type LLMClient struct {
	apiURL string
	apiKey string
	model  string
	http   *http.Client
}

func NewLLMClient(apiURL, apiKey, model string) *LLMClient {
	return &LLMClient{
		apiURL: apiURL,
		apiKey: apiKey,
		model:  model,
		http:   &http.Client{Timeout: 30 * time.Second},
	}
}

func (l *LLMClient) CallWithTools(userMessage string, tools []map[string]interface{}) (string, map[string]interface{}, error) {
	// 如果没有配置上游API，使用简单匹配
	if l.apiKey == "" {
		return l.simpleMatch(userMessage)
	}

	toolName, toolInput, err := l.callOpenAICompatible(userMessage, tools)
	if err != nil {
		log.Printf("⚠️ LLM Function Calling失败，回退到规则匹配: %v", err)
		return l.simpleMatch(userMessage)
	}

	if toolName == "" {
		return "chat", nil, nil
	}

	return toolName, toolInput, nil
}

func normalizeToolForOpenAI(tool map[string]interface{}) map[string]interface{} {
	normalized := map[string]interface{}{}
	for k, v := range tool {
		normalized[k] = v
	}
	if schema, ok := normalized["input_schema"]; ok {
		normalized["parameters"] = schema
		delete(normalized, "input_schema")
	}
	return normalized
}

func isAllowedTool(name string) bool {
	switch name {
	case "check_environment", "analyze_sequence", "generate_protein":
		return true
	default:
		return false
	}
}

func (l *LLMClient) callOpenAICompatible(userMessage string, tools []map[string]interface{}) (string, map[string]interface{}, error) {
	type openAITool struct {
		Type     string                 `json:"type"`
		Function map[string]interface{} `json:"function"`
	}

	type openAIMessage struct {
		Role    string `json:"role"`
		Content string `json:"content"`
	}

	reqBody := map[string]interface{}{
		"model": l.model,
		"messages": []openAIMessage{
			{Role: "system", Content: `你是一个ESM3工具调度器。请在可用工具中选择最合适的一个：
- check_environment: 用户要检查环境/依赖时使用
- analyze_sequence: 支持参数 source( direct/file/database )，可配 sequence/file_path/db_path/query
- generate_protein: 支持可选参数 min_length/max_length/must_include/forbidden_aas/temperature
如果无法匹配，直接回复普通文本，不要编造工具参数。`},
			{Role: "user", Content: userMessage},
		},
		"temperature": 0,
	}

	if len(tools) > 0 {
		convertedTools := make([]openAITool, 0, len(tools))
		for _, tool := range tools {
			convertedTools = append(convertedTools, openAITool{Type: "function", Function: normalizeToolForOpenAI(tool)})
		}
		reqBody["tools"] = convertedTools
		reqBody["tool_choice"] = "auto"
	}

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		return "", nil, err
	}

	req, err := http.NewRequest(http.MethodPost, l.apiURL, bytes.NewBuffer(bodyBytes))
	if err != nil {
		return "", nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+l.apiKey)

	resp, err := l.http.Do(req)
	if err != nil {
		return "", nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", nil, fmt.Errorf("llm api status=%d body=%s", resp.StatusCode, truncate(string(body), 200))
	}

	var parsed struct {
		Choices []struct {
			Message struct {
				Content   string `json:"content"`
				ToolCalls []struct {
					Function struct {
						Name      string          `json:"name"`
						Arguments json.RawMessage `json:"arguments"`
					} `json:"function"`
				} `json:"tool_calls"`
			} `json:"message"`
		} `json:"choices"`
	}

	if err := json.Unmarshal(body, &parsed); err != nil {
		return "", nil, fmt.Errorf("parse llm response failed: %w", err)
	}

	if len(parsed.Choices) == 0 {
		return "", nil, fmt.Errorf("empty llm choices")
	}

	if len(parsed.Choices[0].Message.ToolCalls) == 0 {
		return "", nil, nil
	}

	call := parsed.Choices[0].Message.ToolCalls[0]
	if call.Function.Name == "" {
		return "", nil, fmt.Errorf("tool call name is empty")
	}
	if !isAllowedTool(call.Function.Name) {
		return "", nil, fmt.Errorf("unknown tool from llm: %s", call.Function.Name)
	}

	input := map[string]interface{}{}
	if len(call.Function.Arguments) > 0 && string(call.Function.Arguments) != "null" {
		if err := json.Unmarshal(call.Function.Arguments, &input); err != nil {
			return "", nil, fmt.Errorf("parse tool args failed: %w", err)
		}
	}

	return call.Function.Name, input, nil
}

func (l *LLMClient) simpleMatch(msg string) (string, map[string]interface{}, error) {
	msg = strings.ToLower(msg)

	if strings.Contains(msg, "check") || strings.Contains(msg, "检查") || strings.Contains(msg, "环境") {
		return "check_environment", nil, nil
	}

	if strings.Contains(msg, "generate") || strings.Contains(msg, "生成") {
		params := map[string]interface{}{}
		if strings.Contains(msg, "不能") || strings.Contains(msg, "禁用") {
			if strings.Contains(msg, "c") {
				params["forbidden_aas"] = "C"
			}
		}
		return "generate_protein", params, nil
	}

	if strings.Contains(msg, "analyze") || strings.Contains(msg, "分析") {
		sequence := extractSequence(msg)
		if sequence != "" {
			return "analyze_sequence", map[string]interface{}{"source": "direct", "sequence": sequence}, nil
		}
		if strings.Contains(msg, "文件") || strings.Contains(msg, "file") {
			return "analyze_sequence", map[string]interface{}{"source": "file", "file_path": extractLikelyPath(msg)}, nil
		}
		if strings.Contains(msg, "数据库") || strings.Contains(msg, "sqlite") || strings.Contains(msg, "db") {
			return "analyze_sequence", map[string]interface{}{"source": "database"}, nil
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
		llmClient:   NewLLMClient(config.UpstreamAPI, config.UpstreamKey, config.UpstreamModel),
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
		if toolInput == nil {
			toolInput = map[string]interface{}{}
		}
		source, _ := toolInput["source"].(string)
		seq, _ := toolInput["sequence"].(string)
		filePath, _ := toolInput["file_path"].(string)
		dbPath, _ := toolInput["db_path"].(string)
		query, _ := toolInput["query"].(string)
		if strings.TrimSpace(source) == "" && strings.TrimSpace(seq) == "" {
			response = "请提供参数：\n1) 直接序列：source=direct, sequence=...\n2) 文件：source=file, file_path=/path/to.fasta\n3) 数据库：source=database, db_path=/path/to.db, query='SELECT sequence FROM sequences LIMIT 1'"
			break
		}
		if strings.EqualFold(strings.TrimSpace(source), "file") && strings.TrimSpace(filePath) == "" {
			response = "文件模式需要 file_path，例如：source=file, file_path=/data/sample.fasta"
			break
		}
		response, err = a.esm3Client.AnalyzeSequenceFromSource(source, seq, filePath, dbPath, query)
	case "generate_protein":
		if toolInput == nil {
			toolInput = map[string]interface{}{}
		}
		minLength := intFromAny(toolInput["min_length"])
		maxLength := intFromAny(toolInput["max_length"])
		mustInclude, _ := toolInput["must_include"].(string)
		forbidden, _ := toolInput["forbidden_aas"].(string)
		temp := floatFromAny(toolInput["temperature"])
		response, err = a.esm3Client.GenerateProtein(minLength, maxLength, mustInclude, forbidden, temp)
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
2. 序列分析:
   - 直接输入: "分析序列 MKGEELF..."
   - 文件输入: "请分析文件 /data/a.fasta 里的蛋白"
   - 数据库输入: "从数据库读取并分析，query=SELECT sequence FROM sequences LIMIT 1"
3. 蛋白质生成（可加约束）:
   - "生成蛋白，长度 180-220，必须包含 GSG，不能有 C"

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

func extractLikelyPath(text string) string {
	for _, word := range strings.Fields(text) {
		w := strings.Trim(word, "'\"，。,.!?:;()[]{}")
		if strings.HasPrefix(w, "/") || strings.Contains(w, "./") {
			return w
		}
		if strings.Contains(w, ".fasta") || strings.Contains(w, ".fa") || strings.Contains(w, ".txt") {
			return w
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

func intFromAny(v interface{}) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case string:
		var out int
		fmt.Sscanf(n, "%d", &out)
		return out
	default:
		return 0
	}
}

func floatFromAny(v interface{}) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case string:
		var out float64
		fmt.Sscanf(n, "%f", &out)
		return out
	default:
		return 0
	}
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
