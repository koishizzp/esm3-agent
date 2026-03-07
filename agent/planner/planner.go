package planner

import (
	"fmt"

	"esm3-agent/protein_pipeline"
)

type Planner struct{}

func NewPlanner() *Planner {
	return &Planner{}
}

func (p *Planner) Build(req protein_pipeline.DesignRequest) protein_pipeline.DesignPlan {
	target := req.TargetProtein
	if target == "" {
		target = "GFP"
	}
	strategy := fmt.Sprintf("optimize %s variants with iterative mutation and ranking", target)
	if req.Objective != "" {
		strategy = req.Objective
	}

	return protein_pipeline.DesignPlan{
		Strategy:       strategy,
		MutationPolicy: "single + double point mutations with motif constraints",
		ScoringFocus:   []string{"stability", "fluorescence_proxy", "composition_penalty"},
	}
}
