package main

import (
	"log"

	"esm3-agent/agent/evaluator"
	"esm3-agent/agent/optimizer"
	"esm3-agent/agent/planner"
	"esm3-agent/api_server"
	"esm3-agent/config"
	"esm3-agent/esm3_runner"
	"esm3-agent/protein_pipeline"
)

func main() {
	listenAddr := ":8080"
	cfg := config.Config{}
	if loaded, err := config.Load("config.yaml"); err != nil {
		log.Printf("⚠️  load config.yaml failed, using defaults/env: %v", err)
	} else {
		cfg = loaded
		cfg.ApplyLLMEnv()
		listenAddr = cfg.ListenAddr(listenAddr)
	}

	runner := esm3_runner.NewClientFromConfig(cfg)
	plan := planner.NewPlanner()
	eval := evaluator.NewEvaluator()
	opt := optimizer.NewOptimizer(runner)
	pipeline := protein_pipeline.NewPipeline(plan, eval, opt)

	server := api_server.NewServer(listenAddr, pipeline)
	log.Printf("🚀 ESM3 Agent API listening on %s", server.Port())
	if err := server.Start(); err != nil {
		log.Fatal(err)
	}
}
