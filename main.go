package main

import (
	"log"

	"esm3-agent/agent/evaluator"
	"esm3-agent/agent/optimizer"
	"esm3-agent/agent/planner"
	"esm3-agent/api_server"
	"esm3-agent/esm3_runner"
	"esm3-agent/protein_pipeline"
)

func main() {
	runner := esm3_runner.NewClient()
	plan := planner.NewPlanner()
	eval := evaluator.NewEvaluator()
	opt := optimizer.NewOptimizer(runner)
	pipeline := protein_pipeline.NewPipeline(plan, eval, opt)

	server := api_server.NewServer(":8080", pipeline)
	log.Printf("🚀 ESM3 Agent API listening on %s", server.Port())
	if err := server.Start(); err != nil {
		log.Fatal(err)
	}
}
