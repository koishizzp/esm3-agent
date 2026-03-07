package esm3_runner

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"esm3-agent/config"
)

type Client struct {
	httpClient *http.Client
	endpoint   string
	apiKey     string
	model      string
	pythonPath string
	scriptDir  string
	entrypoint string
	timeoutSec int
}

type generateRequest struct {
	Sequence      string `json:"sequence"`
	Round         int    `json:"round"`
	NumCandidates int    `json:"num_candidates"`
	RequiredMotif string `json:"required_motif,omitempty"`
	ForbiddenAAs  string `json:"forbidden_aas,omitempty"`
	Model         string `json:"model,omitempty"`
}

type generateResponse struct {
	Variants  []string `json:"variants"`
	Sequences []string `json:"sequences"`
	Data      []struct {
		Sequence string `json:"sequence"`
	} `json:"data"`
	Error             string   `json:"error"`
	Attempts          []string `json:"attempts"`
	AvailableSymbols  []string `json:"available_symbols"`
	GenerationRelated []string `json:"generation_related_symbols"`
	InstantiateErrors []string `json:"instantiate_errors"`
	EntrypointUsed    string   `json:"entrypoint_used"`
}

func NewClient() *Client {
	return &Client{}
}

func NewClientFromConfig(cfg config.Config) *Client {
	c := NewClient()
	c.endpoint = firstNonEmpty(cfg.ESM3.Endpoint, os.Getenv("ESM3_ENDPOINT"))
	c.apiKey = firstNonEmpty(cfg.ESM3.APIKey, os.Getenv("ESM3_API_KEY"))
	c.model = firstNonEmpty(cfg.ESM3.Model, os.Getenv("ESM3_MODEL"))
	c.pythonPath = firstNonEmpty(cfg.ESM3.PythonPath, os.Getenv("ESM3_PYTHON_PATH"), "python3")
	c.scriptDir = firstNonEmpty(cfg.ESM3.ScriptDir, os.Getenv("ESM3_SCRIPT_DIR"))
	c.entrypoint = firstNonEmpty(cfg.ESM3.Entrypoint, os.Getenv("ESM3_ENTRYPOINT"))
	c.timeoutSec = cfg.ESM3.Timeout
	if c.timeoutSec <= 0 {
		c.timeoutSec = 120
	}
	c.httpClient = &http.Client{Timeout: time.Duration(c.timeoutSec) * time.Second}
	return c
}

func (c *Client) GenerateVariants(base string, round, n int, requiredMotif, forbidden string) ([]string, error) {
	if n <= 0 {
		n = 6
	}
	if base == "" {
		base = defaultGFP
	}
	forbidden = strings.ToUpper(forbidden)

	if strings.TrimSpace(c.endpoint) != "" {
		return c.generateByEndpoint(base, round, n, requiredMotif, forbidden)
	}
	if strings.TrimSpace(c.scriptDir) != "" {
		return c.generateByLocalPython(base, round, n, requiredMotif, forbidden)
	}
	return nil, fmt.Errorf("ESM3 not configured: set esm3.endpoint or esm3.script_dir")
}

func (c *Client) generateByEndpoint(base string, round, n int, requiredMotif, forbidden string) ([]string, error) {
	payload := generateRequest{
		Sequence:      strings.ToUpper(base),
		Round:         round,
		NumCandidates: n,
		RequiredMotif: strings.ToUpper(strings.TrimSpace(requiredMotif)),
		ForbiddenAAs:  strings.ToUpper(strings.TrimSpace(forbidden)),
		Model:         c.model,
	}
	body, _ := json.Marshal(payload)
	req, err := http.NewRequest(http.MethodPost, c.endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		blob, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return nil, fmt.Errorf("upstream status: %d body=%s", resp.StatusCode, strings.TrimSpace(string(blob)))
	}

	var parsed generateResponse
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return nil, err
	}
	if parsed.Error != "" {
		return nil, fmt.Errorf("upstream error: %s", parsed.Error)
	}
	return cleanVariants(parsed, n, payload.RequiredMotif, forbidden)
}

func (c *Client) generateByLocalPython(base string, round, n int, requiredMotif, forbidden string) ([]string, error) {
	payload := generateRequest{
		Sequence:      strings.ToUpper(base),
		Round:         round,
		NumCandidates: n,
		RequiredMotif: strings.ToUpper(strings.TrimSpace(requiredMotif)),
		ForbiddenAAs:  strings.ToUpper(strings.TrimSpace(forbidden)),
		Model:         c.model,
	}
	bridgePath := filepath.Join("esm3_runner", "bridge_generate.py")
	body, _ := json.Marshal(payload)
	cmd := exec.Command(c.pythonPath, bridgePath)
	cmd.Env = append(os.Environ(),
		"ESM3_SCRIPT_DIR="+c.scriptDir,
		"ESM3_ENTRYPOINT="+c.entrypoint,
		fmt.Sprintf("ESM3_TIMEOUT=%d", c.timeoutSec),
	)
	cmd.Stdin = bytes.NewReader(body)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("python bridge failed: %w: %s", err, strings.TrimSpace(string(out)))
	}
	parsed, err := parseGenerateResponse(out)
	if err != nil {
		return nil, fmt.Errorf("parse python output failed: %w output=%s", err, strings.TrimSpace(string(out)))
	}
	if parsed.Error != "" {
		detail := parsed.Error
		if len(parsed.Attempts) > 0 {
			detail += "; attempts=" + strings.Join(parsed.Attempts, " | ")
		}
		if len(parsed.AvailableSymbols) > 0 {
			max := len(parsed.AvailableSymbols)
			if max > 30 {
				max = 30
			}
			detail += "; available_symbols=" + strings.Join(parsed.AvailableSymbols[:max], ",")
		}
		if len(parsed.GenerationRelated) > 0 {
			max := len(parsed.GenerationRelated)
			if max > 20 {
				max = 20
			}
			detail += "; generation_related_symbols=" + strings.Join(parsed.GenerationRelated[:max], ",")
		}
		if len(parsed.InstantiateErrors) > 0 {
			max := len(parsed.InstantiateErrors)
			if max > 6 {
				max = 6
			}
			detail += "; instantiate_errors=" + strings.Join(parsed.InstantiateErrors[:max], " | ")
		}
		return nil, fmt.Errorf("python bridge error: %s", detail)
	}
	return cleanVariants(parsed, n, payload.RequiredMotif, forbidden)
}

func parseGenerateResponse(out []byte) (generateResponse, error) {
	var parsed generateResponse
	trimmed := strings.TrimSpace(string(out))
	if trimmed == "" {
		return parsed, fmt.Errorf("empty output")
	}
	if err := json.Unmarshal([]byte(trimmed), &parsed); err == nil {
		return parsed, nil
	}
	lines := strings.Split(trimmed, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		line := strings.TrimSpace(lines[i])
		if !strings.HasPrefix(line, "{") || !strings.HasSuffix(line, "}") {
			continue
		}
		if err := json.Unmarshal([]byte(line), &parsed); err == nil {
			return parsed, nil
		}
	}
	start := strings.LastIndex(trimmed, "{")
	if start >= 0 {
		candidate := trimmed[start:]
		if err := json.Unmarshal([]byte(candidate), &parsed); err == nil {
			return parsed, nil
		}
	}
	return parsed, fmt.Errorf("no json object found in python output")
}

func cleanVariants(parsed generateResponse, n int, requiredMotif, forbidden string) ([]string, error) {
	items := parsed.Variants
	if len(items) == 0 {
		items = parsed.Sequences
	}
	if len(items) == 0 && len(parsed.Data) > 0 {
		for _, row := range parsed.Data {
			if strings.TrimSpace(row.Sequence) != "" {
				items = append(items, strings.ToUpper(strings.TrimSpace(row.Sequence)))
			}
		}
	}
	cleaned := make([]string, 0, len(items))
	for _, seq := range items {
		seq = strings.ToUpper(strings.TrimSpace(seq))
		if seq == "" {
			continue
		}
		if forbidden != "" && hasForbidden(seq, forbidden) {
			continue
		}
		if requiredMotif != "" && !strings.Contains(seq, requiredMotif) {
			continue
		}
		cleaned = append(cleaned, seq)
	}
	if len(cleaned) == 0 {
		return nil, fmt.Errorf("no valid variants returned by ESM3")
	}
	if len(cleaned) > n {
		cleaned = cleaned[:n]
	}
	return cleaned, nil
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v)
		}
	}
	return ""
}

func hasForbidden(seq, forbidden string) bool {
	for _, aa := range forbidden {
		if strings.ContainsRune(seq, aa) {
			return true
		}
	}
	return false
}

const defaultGFP = "MSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK"

func (c *Client) Name() string {
	if strings.TrimSpace(c.endpoint) != "" {
		return "esm3-http-runner"
	}
	if strings.TrimSpace(c.scriptDir) != "" {
		return "esm3-local-python-runner"
	}
	return "esm3-unconfigured"
}
