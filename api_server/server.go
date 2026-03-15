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
	Run(req protein_pipeline.DesignRequest) (protein_pipeline.DesignResult, error)
}

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatRequest struct {
	Messages             []chatMessage   `json:"messages"`
	LatestResult         map[string]any  `json:"latest_result"`
	PreviousBestSequence string          `json:"previous_best_sequence"`
	ReasoningContext     map[string]any  `json:"reasoning_context"`
}

type Server struct {
	port          string
	pipeline      runner
	httpClient    *http.Client
	upstreamURL   string
	upstreamKey   string
	upstreamModel string
	reasonerURL   string
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
		reasonerURL:   reasonerBaseURL(),
	}
}

func reasonerBaseURL() string {
	if value := strings.TrimSpace(os.Getenv("PROTEIN_AGENT_API_URL")); value != "" {
		return value
	}
	return "http://127.0.0.1:8002"
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
	result, err := s.pipeline.Run(req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	writeJSON(w, result)
}

func (s *Server) chat(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		query := strings.TrimSpace(r.URL.Query().Get("q"))
		if query == "" {
			help := "閻犲洢鍎茬敮鎾矗閿濆棙笑 OpenAI 闁稿繒鍘ч鎰板冀閻撳海纭€闁挎稑鑻紓鎾舵媼椤旇鈻忛柣?POST JSON闁靛棔绻恘"
			help += "婵炴潙绻楅～宥夊闯閵娿儲褰ラ梺顐ゅ枍缂嶅顨ョ仦钘夎闁汇埄鐓夌槐?v1/chat/completions?q=閻犲洨鏌夐崵婊堝礉閵婎煈鍟庨悹渚囨惙FP妤犵偞鍎奸崙顖涚?
			writeChatCompletion(w, help, nil)
			return
		}
		respondWithPrompt(s, w, strings.ToLower(query), "")
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

	var req chatRequest
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	req.LatestResult, req.PreviousBestSequence = normalizeChatContext(req)
	content := latestUserContent(req.Messages)
	reasoning := isReasoningQuery(content)

	if reasoning {
		if len(req.LatestResult) != 0 {
			if reply, err := s.callReasoner(content, req.Messages, req.LatestResult, req.PreviousBestSequence); err == nil && strings.TrimSpace(reply) != "" {
				extra := extrasFromLatestResult(req.LatestResult)
				extra["chat_mode"] = "reasoning"
				extra["reasoning_context"] = buildReasoningContext("reasoning", req.LatestResult, req.PreviousBestSequence)
				writeChatCompletion(w, reply, extra)
				return
			}
			if s.upstreamEnabled() {
				s.proxyChat(w, payload, content, req.LatestResult, true, req.PreviousBestSequence)
				return
			}
			extra := extrasFromLatestResult(req.LatestResult)
			extra["chat_mode"] = "reasoning"
			extra["reasoning_context"] = buildReasoningContext("reasoning", req.LatestResult, req.PreviousBestSequence)
			writeChatCompletion(w, localReasoningReply(content, req.LatestResult, req.PreviousBestSequence), extra)
			return
		}
		if s.upstreamEnabled() {
			s.proxyChat(w, payload, content, nil, true, req.PreviousBestSequence)
			return
		}
		writeChatCompletion(w, "如果你希望我解释当前候选为什么更适合验证，请在请求里附带 `latest_result`，或先调用 `POST /v1/inference/design` 获取完整结果。", map[string]any{"chat_mode": "reasoning", "reasoning_context": buildReasoningContext("reasoning", nil, req.PreviousBestSequence)})
		return
	}

	if s.upstreamEnabled() {
		s.proxyChat(w, payload, content, nil, false, req.PreviousBestSequence)
		return
	}

	respondWithPrompt(s, w, strings.ToLower(content), req.PreviousBestSequence)
}

func latestUserContent(messages []chatMessage) string {
	content := ""
	for i := len(messages) - 1; i >= 0; i-- {
		if messages[i].Role == "user" {
			content = messages[i].Content
			break
		}
	}
	return content
}

func normalizeChatContext(req chatRequest) (map[string]any, string) {
	latestResult := req.LatestResult
	previousBestSequence := req.PreviousBestSequence
	if len(req.ReasoningContext) != 0 {
		if len(latestResult) == 0 {
			if latest, ok := req.ReasoningContext["latest_result"].(map[string]any); ok {
				latestResult = latest
			}
		}
		if previousBestSequence == "" {
			if previous, ok := req.ReasoningContext["previous_best_sequence"].(string); ok {
				previousBestSequence = previous
			}
		}
	}
	return latestResult, previousBestSequence
}

func buildReasoningContext(chatMode string, latestResult map[string]any, previousBestSequence string) map[string]any {
	context := map[string]any{
		"version":                1,
		"chat_mode":              chatMode,
		"current_mode":           "design",
		"latest_result":          latestResult,
		"previous_best_sequence": previousBestSequence,
	}
	if best := bestCandidateFromResult(latestResult); len(best) != 0 {
		context["latest_best_sequence"] = stringValue(best["sequence"])
	}
	return context
}

func summaryFromDesignResult(req protein_pipeline.DesignRequest, result protein_pipeline.DesignResult) map[string]any {
	return map[string]any{
		"request":         req,
		"best_candidate":  result.BestCandidate,
		"all_candidates":  result.AllCandidates,
		"total_generated": result.TotalGenerated,
		"rounds":          result.Rounds,
	}
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

func (s *Server) proxyChat(w http.ResponseWriter, payload map[string]any, userContent string, latestResult map[string]any, skipExecution bool, previousBestSequence string) {
	if s.upstreamModel != "" {
		payload["model"] = s.upstreamModel
	}
	messages, effectiveLatestResult := s.buildUpstreamMessages(payload["messages"], userContent, latestResult, skipExecution)
	payload["messages"] = messages
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

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		http.Error(w, "read upstream response failed: "+err.Error(), http.StatusBadGateway)
		return
	}
	chatMode := "execution"
	if skipExecution {
		chatMode = "reasoning"
	}
	var parsed map[string]any
	if json.Unmarshal(body, &parsed) == nil {
		for k, v := range extrasFromLatestResult(effectiveLatestResult) {
			parsed[k] = v
		}
		parsed["chat_mode"] = chatMode
		parsed["reasoning_context"] = buildReasoningContext(chatMode, effectiveLatestResult, previousBestSequence)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		_ = json.NewEncoder(w).Encode(parsed)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	_, _ = w.Write(body)
}

func (s *Server) buildUpstreamMessages(raw any, userContent string, latestResult map[string]any, skipExecution bool) ([]map[string]string, map[string]any) {
	system := "浣犳槸 ESM3 铔嬬櫧璁捐鍔╂墜銆傝鍩轰簬缁欏畾璁捐缁撴灉瑙ｉ噴鍊欓€夋帓搴忋€佸垎鏁般€侀獙璇佷紭鍏堢骇涓庝笅涓€姝ュ疄楠屽缓璁€?
	system += " 褰撶敤鎴峰湪杩介棶瑙ｉ噴鏃讹紝璇蜂弗鏍煎紩鐢ㄦ彁渚涚殑 JSON 瀛楁锛涘彲浠ユ帹鏂紝浣嗚鏄庣‘璇存槸鎺ㄦ柇锛屼笉瑕佹妸鍒嗘暟褰撴垚瀹為獙浜嬪疄銆?

	messages := []map[string]string{{"role": "system", "content": system}}
	effectiveLatestResult := latestResult

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

	if len(latestResult) != 0 {
		if b, err := json.Marshal(latestResult); err == nil {
			messages = append(messages, map[string]string{
				"role":    "system",
				"content": "浠ヤ笅鏄綋鍓嶅彲鐢ㄧ殑璁捐缁撴灉 JSON锛岃涓ユ牸鍩轰簬杩欎簺瀛楁瑙ｉ噴锛屼笉瑕佸亣瑁呮湁棰濆瀹為獙缁撹锛歕n" + string(b),
			})
		}
	}

	content := strings.ToLower(strings.TrimSpace(userContent))
	if !skipExecution && content != "" && !strings.Contains(content, "help") && !strings.Contains(content, "甯姪") {
		designReq := inferDesignRequest(content)
		result, err := s.pipeline.Run(designReq)
		if err != nil {
			messages = append(messages, map[string]string{"role": "system", "content": "ESM3 design execution failed: " + err.Error()})
			return messages, effectiveLatestResult
		}
		summary := summaryFromDesignResult(designReq, result)
		effectiveLatestResult = summary
		if b, err := json.Marshal(summary); err == nil {
			messages = append(messages, map[string]string{
				"role":    "system",
				"content": "浠ヤ笅鏄湰娆?ESM3 璁捐鎵ц缁撴灉 JSON锛岃涓ユ牸鍩轰簬杩欎簺瀛楁鍥炵瓟锛歕n" + string(b),
			})
		}
	}

	return messages, effectiveLatestResult
}

func (s *Server) callReasoner(message string, conversation []chatMessage, latestResult map[string]any, previousBestSequence string) (string, error) {
	if strings.TrimSpace(s.reasonerURL) == "" {
		return "", fmt.Errorf("reasoner url not configured")
	}
	payload := map[string]any{
		"message":                message,
		"conversation":           conversation,
		"latest_result":          latestResult,
		"current_mode":           "design",
		"previous_best_sequence": previousBestSequence,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	url := strings.TrimRight(s.reasonerURL, "/") + "/chat_reasoning"
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("reasoner HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	var parsed struct {
		Reply string `json:"reply"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return "", err
	}
	return parsed.Reply, nil
}

func extrasFromLatestResult(latestResult map[string]any) map[string]any {
	extra := map[string]any{}
	if len(latestResult) == 0 {
		return extra
	}
	if best, ok := latestResult["best_candidate"]; ok {
		extra["best_candidate"] = best
	} else if best, ok := latestResult["best_sequences"].(map[string]any); ok {
		extra["best_candidate"] = map[string]any{
			"sequence": best["sequence"],
			"score":    best["score"],
			"round":    best["iteration"],
		}
	}
	if total, ok := latestResult["total_generated"]; ok {
		extra["total_generated"] = total
	} else if history, ok := latestResult["history"].([]any); ok {
		extra["total_generated"] = len(history)
	}
	if rounds, ok := latestResult["rounds"]; ok {
		extra["rounds"] = rounds
	}
	return extra
}

func localReasoningReply(message string, latestResult map[string]any, previousBestSequence string) string {
	best := bestCandidateFromResult(latestResult)
	if len(best) == 0 {
		return "閹存垹骞囬崷銊︾梾閺堝瀣侀崚鏉垮讲瀵洜鏁ら惃鍕付娴ｅ啿鈧瑩鈧绱濋幍鈧禒銉ㄧ箷娑撳秷鍏樻稉銉ㄧ殤鐟欙綁鍣撮垾婊€璐熸禒鈧稊鍫濈暊閺囨挳鈧倸鎮庢宀冪槈閳ユ縿鈧倽顕崗鍫熷絹娓?latest_result閿涘本鍨ㄩ懓鍛帥鐠烘垳绔村▎陇顔曠拋掳鈧?
	}
	history := historyFromResult(latestResult)
	bestScore := numberValue(best["score"])
	bestRound := intValue(best["round"], intValue(best["iteration"], 0))
	lines := []string{
		fmt.Sprintf("婵″倹鐏夐崣顏嗘箙瑜版挸澧犳潻娆愬缂佹挻鐏夐敍宀冪箹娑擃亜鈧瑩鈧娲块柅鍌氭値娴兼ê鍘涙宀冪槈閿涘苯娲滄稉鍝勭暊閻╊喖澧犻幒鎺戞躬缁楊兛绔撮敍姝碿ore = %.4f閿涘本娼甸懛顏嗩儑 %d 鏉烆喓鈧?, bestScore, bestRound),
	}
	if len(history) > 1 {
		first := history[0]
		second := history[1]
		delta := numberValue(first["score"]) - numberValue(second["score"])
		lines = append(lines, fmt.Sprintf("鐎瑰啫鎷拌ぐ鎾冲缁楊兛绨╅崥宥勭闂傜绻曢張?%.4f 閻ㄥ嫬鍨庨弫鏉挎▕閿涘本澧嶆禒銉ょ瑝閺勵垰濯哄娲暙閸忓牄鈧?, delta))
	} else {
		lines = append(lines, "瑜版挸澧犻崣顖滄纯閹恒儲鐦潏鍐畱閸婃瑩鈧绗夋径姘剧礉閹碘偓娴犮儱鐣犻懛鍐茬毌閺勵垳骞囬張澶岀波閺嬫粓鍣烽張鈧崥鍫㈡倞閻ㄥ嫰顩绘稉顏堢崣鐠囦礁鍙嗛崣锝冣偓?)
	}
	if previousBestSequence != "" {
		currentSequence := stringValue(best["sequence"])
		if currentSequence != "" && currentSequence != previousBestSequence {
			lines = append(lines, "閹恒劍鏌囬敍姘暊閼宠棄顧勯弴澶稿敩娑撳﹣绔存潪顔芥付娴ｅ啿绨崚妤嬬礉鐠囧瓨妲戦崷銊ョ秼閸撳秷鐦庨崚鍡曠秼缁绗呴敍灞炬煀閸婃瑩鈧鐢弶銉ょ啊閸欘垵顫嗛惃鍕笓鎼村繑鏁归惄濞库偓?)
		}
	}
	lines = append(lines,
		"娴ｅ棜顩﹀▔銊﹀壈閿涘矁绻栭柌宀€娈戦垾婊勬纯闁倸鎮庢宀冪槈閳ユ繂褰ф禒锝堛€冪€瑰啫婀ぐ鎾冲鐠囧嫬鍨庨崙鑺ユ殶閸滃苯缍嬮崜宥呪偓娆撯偓澶愭肠閸氬牓鍣烽弴鎾浆閸撳稄绱濇稉宥囩搼娴滃骸鐣犲鑼病鐞氼偄鐤勬宀勭崣鐠囦椒璐熺紒婵嗩嚠閺堚偓婵傚鈧?,
		"婵″倹鐏夋担鐘靛箛閸︺劏顩﹂拃钘夋勾閿涘本鍨滃楦款唴閼峰啿鐨幎濠傜暊閸滃瞼顑囨禍灞芥倳閸嬫艾鑻熺悰宀勭崣鐠囦緤绱濇潻娆愮壉閺堚偓鐎硅妲楀Λ鈧灞界秼閸撳秵甯撴惔蹇旀Ц閸氾妇婀￠惃鍕讲闂堢姰鈧?,
	)
	if looksLikeWhyQuestion(message) {
		return strings.Join(lines, "\n")
	}
	return strings.Join(lines[:minInt(len(lines), 4)], "\n")
}

func isReasoningQuery(content string) bool {
	text := strings.ToLower(strings.TrimSpace(content))
	if text == "" {
		return false
	}
	if strings.Contains(text, "自动设计") || strings.Contains(text, "设计") || strings.Contains(text, "生成") || strings.Contains(text, "优化") || strings.Contains(text, "迭代") || strings.Contains(text, "design") || strings.Contains(text, "generate") || strings.Contains(text, "optimize") {
		return false
	}
	reasoningKeywords := []string{"鐟欙綁鍣?, "閸掑棙鐎?, "娑撹桨绮堟稊?, "娑撹桨缍?, "閻炲棛鏁?, "娓氭繃宓?, "閹簼绠為惇?, "鐠囧嫪鐜?, "閹崵绮?, "濮掑倹瀚?, "鐎佃鐦?, "濮ｆ棁绶?, "闁倸鎮庢宀冪槈", "閺囨挳鈧倸鎮?, "娴兼ê鍘涙宀冪槈", "妞嬪酣娅?, "娑撳绔村?, "閸婃瑩鈧?, "explain", "why", "compare"}
	actionKeywords := []string{"閼奉亜濮╃拋鎹愵吀", "鐠佹崘顓?, "閻㈢喐鍨?, "娴兼ê瀵?, "鏉╊厺鍞?, "缂佈呯敾娴兼ê瀵?, "缂佈呯敾鐠?, "闁插秵鏌?, "閸愬秵娼?, "缁涙盯鈧?, "閹垫挸鍨?, "缁愪礁褰?, "闁棙濮岄崣?, "design", "generate", "optimize"}
	if !containsAny(text, reasoningKeywords) {
		return false
	}
	if containsAny(text, []string{"瑜版挸澧?, "鏉╂瑤閲?, "鐠?, "娑撳﹣绔存潪?, "閸婃瑩鈧?, "閺堚偓娴ｅ啿绨崚?, "缂佹挻鐏?, "current", "candidate", "result"}) {
		return true
	}
	if containsAny(text, actionKeywords) {
		return false
	}
	return true
}

func looksLikeWhyQuestion(content string) bool {
	text := strings.ToLower(content)
	return containsAny(text, []string{"娑撹桨绮堟稊?, "娑撹桨缍?, "閻炲棛鏁?, "闁倸鎮庢宀冪槈", "why", "reason"})
}

func containsAny(content string, patterns []string) bool {
	for _, pattern := range patterns {
		if strings.Contains(content, pattern) {
			return true
		}
	}
	return false
}

func bestCandidateFromResult(latestResult map[string]any) map[string]any {
	if best, ok := latestResult["best_candidate"].(map[string]any); ok {
		return best
	}
	if best, ok := latestResult["best_sequences"].(map[string]any); ok {
		return map[string]any{
			"sequence":  best["sequence"],
			"score":     best["score"],
			"round":     best["iteration"],
			"iteration": best["iteration"],
		}
	}
	return nil
}

func historyFromResult(latestResult map[string]any) []map[string]any {
	var items []map[string]any
	if raw, ok := latestResult["all_candidates"].([]any); ok {
		for _, item := range raw {
			if record, ok := item.(map[string]any); ok {
				items = append(items, record)
			}
		}
	}
	if len(items) == 0 {
		if raw, ok := latestResult["history"].([]any); ok {
			for _, item := range raw {
				if record, ok := item.(map[string]any); ok {
					items = append(items, map[string]any{
						"sequence":  record["sequence"],
						"score":     record["score"],
						"round":     record["iteration"],
						"iteration": record["iteration"],
					})
				}
			}
		}
	}
	for i := 0; i < len(items); i++ {
		for j := i + 1; j < len(items); j++ {
			if numberValue(items[j]["score"]) > numberValue(items[i]["score"]) {
				items[i], items[j] = items[j], items[i]
			}
		}
	}
	return items
}

func numberValue(value any) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case json.Number:
		f, _ := v.Float64()
		return f
	default:
		return 0
	}
}

func intValue(value any, fallback int) int {
	switch v := value.(type) {
	case int:
		return v
	case int64:
		return int(v)
	case float64:
		return int(v)
	case json.Number:
		i, err := v.Int64()
		if err == nil {
			return int(i)
		}
	}
	return fallback
}

func stringValue(value any) string {
	if text, ok := value.(string); ok {
		return text
	}
	return ""
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func inferDesignRequest(content string) protein_pipeline.DesignRequest {
	designReq := protein_pipeline.DesignRequest{TargetProtein: "GFP", NumCandidates: 8, Rounds: 3}
	if strings.Contains(content, "閺夆晩鍘洪崬?) {
		designReq.Rounds = 5
	}
	if strings.Contains(content, "缂佹稒鐩埀?) {
		designReq.NumCandidates = 12
	}
	if strings.Contains(content, "syg") || strings.Contains(content, "chromophore") || strings.Contains(content, "鑹插洟") {
		designReq.RequiredMotif = "SYG"
	}
	if strings.Contains(content, "濞戞挸绉烽崗?) && strings.Contains(content, "c") {
		designReq.ForbiddenAAs = "C"
	}
	return designReq
}

func respondWithPrompt(s *Server, w http.ResponseWriter, content string, previousBestSequence string) {
	if strings.TrimSpace(content) == "" || strings.Contains(content, "help") || strings.Contains(content, "閻㈩垼鍠栨慨?) {
		help := "閺夆晜鐟﹀Σ?OpenAI 闁稿繒鍘ч鎰板传瀹ュ懐瀹夐柡宥囧帶缁憋繝鏁嶇仦鑲╃懝闁告柡鍓濋弸鍐嫉椤掆偓濠€?choices[0].message.content闁靛棔绻恘\n"
		help += "濠碘€冲€归悘澶嬫媴閻樺啿鍘掗柟宄扮仢閸╁瞼鈧懓鏈弳锝囨媼閹规劦鍚€缂備焦鎸婚悘澶愭晬閸績鍋撳▎鎾亾婢跺﹤鐏欓悶娑栧妸閳ь兛绀侀崹搴ㄥ极閼割兘鍋撴担瑙勪粯濞达絽鍟跨花顓㈠礆濡ゅ绀嗛柨娑樼焷椤曨剛鎷崘顏呮殢闁挎稒鐡峅ST /v1/inference/design"
		writeChatCompletion(w, help, nil)
		return
	}

	designReq := inferDesignRequest(content)
	result, err := s.pipeline.Run(designReq)
	if err != nil {
		writeChatCompletion(w, "ESM3 闁规亽鍔庨幃濠冨緞鏉堫偉袝闁?+err.Error()+"闁靛棗鍊介顒€螞閳ь剟寮?esm3 闂佹澘绉堕悿鍡涘椽鐏炵偓鎷遍柛锔藉楠炲棙鏅堕崘锔瑰亾?, nil)
		return
	}
	summary := summaryFromDesignResult(designReq, result)
	preview := sequencePreview(result.BestCandidate.Sequence)
	answer := fmt.Sprintf("鐎瑰憡褰冮悾顒勫箣閹邦垰娈伴柛鏂诲姀濞夋煡鎯傞崐鐕佸晭閻犱讲鍓濈粊锔剧矙鐎ｅ墎绐楅柣銏㈠枑閸?%d 闁哄鈧枼鍋撳▎鎾亾婢舵稓绀夐柤濂変簻婵晝绮靛☉鈶╁亾婢跺﹨瀚欓悹鍥у閸ㄥ酣鏁嶇仦鐐粯濞达絽鍟块埀顒佺懇閳?%s闁挎稑婢僣ore=%.3f闁挎稑顔抏q=%s闁挎稑顦埀顑跨箰n\n濠碘€冲€垮〒鍫曞礂閵娾晛鍔ラ柛濠冪懇閳ь剙顦板Σ鎴犵磼閸☆厾绀夐悹鍥╂焿閻ㄧ喖鎮?POST /v1/inference/design闁?,
		result.TotalGenerated,
		result.BestCandidate.ID,
		result.BestCandidate.Score,
		preview,
	)

	writeChatCompletion(w, answer, map[string]any{
		"chat_mode":       "execution",
		"reasoning_context": buildReasoningContext("execution", summary, previousBestSequence),
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

