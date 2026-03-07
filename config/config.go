package config

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Server struct {
		Host string
		Port int
	}
	ESM3 struct {
		Endpoint   string
		APIKey     string
		Model      string
		Timeout    int
		PythonPath string
		ScriptDir  string
		Entrypoint string
	}
	LLM struct {
		Provider string
		BaseURL  string
		APIKey   string
		Model    string
	}
}

func Load(path string) (Config, error) {
	file, err := os.Open(path)
	if err != nil {
		return Config{}, err
	}
	defer file.Close()

	cfg := Config{}
	section := ""
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		if !strings.HasPrefix(scanner.Text(), " ") && strings.HasSuffix(line, ":") {
			section = strings.TrimSuffix(line, ":")
			continue
		}

		parts := strings.SplitN(line, ":", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		value := cleanValue(parts[1])

		switch section {
		case "server":
			switch key {
			case "host":
				cfg.Server.Host = value
			case "port":
				if p, err := strconv.Atoi(value); err == nil {
					cfg.Server.Port = p
				}
			}
		case "llm":
			switch key {
			case "provider":
				cfg.LLM.Provider = value
			case "base_url":
				cfg.LLM.BaseURL = value
			case "api_key":
				cfg.LLM.APIKey = value
			case "model":
				cfg.LLM.Model = value
			}
		case "esm3":
			switch key {
			case "endpoint":
				cfg.ESM3.Endpoint = value
			case "api_key":
				cfg.ESM3.APIKey = value
			case "model":
				cfg.ESM3.Model = value
			case "timeout":
				if t, err := strconv.Atoi(value); err == nil {
					cfg.ESM3.Timeout = t
				}
			case "python_path":
				cfg.ESM3.PythonPath = value
			case "script_dir":
				cfg.ESM3.ScriptDir = value
			case "entrypoint":
				cfg.ESM3.Entrypoint = value
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return Config{}, err
	}

	return cfg, nil
}

func cleanValue(raw string) string {
	v := strings.TrimSpace(raw)
	if idx := strings.Index(v, "#"); idx >= 0 {
		v = strings.TrimSpace(v[:idx])
	}
	v = strings.Trim(v, `"`)
	v = strings.Trim(v, `'`)
	return strings.TrimSpace(v)
}

func (c Config) ListenAddr(defaultPort string) string {
	host := strings.TrimSpace(c.Server.Host)
	if host == "" {
		host = "0.0.0.0"
	}
	port := c.Server.Port
	if port == 0 {
		fallback := strings.TrimSpace(defaultPort)
		fallback = strings.TrimPrefix(fallback, ":")
		if fallback == "" {
			fallback = "8080"
		}
		parsed, err := strconv.Atoi(fallback)
		if err != nil {
			parsed = 8080
		}
		port = parsed
	}
	return fmt.Sprintf("%s:%d", host, port)
}

func (c Config) ApplyLLMEnv() {
	provider := strings.ToLower(strings.TrimSpace(c.LLM.Provider))
	if provider != "" && provider != "openai" {
		return
	}
	setWhenPresent("OPENAI_BASE_URL", c.LLM.BaseURL)
	setWhenPresent("OPENAI_API_KEY", c.LLM.APIKey)
	setWhenPresent("OPENAI_MODEL", c.LLM.Model)
}

func setWhenPresent(key, value string) {
	if strings.TrimSpace(value) == "" {
		return
	}
	_ = os.Setenv(key, strings.TrimSpace(value))
}
