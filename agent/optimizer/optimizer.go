package optimizer

import (
	"fmt"

	"esm3-agent/protein_pipeline"
)

type Generator interface {
	GenerateVariants(base string, round, n int, requiredMotif, forbidden string) ([]string, error)
}

type Optimizer struct {
	runner Generator
}

func NewOptimizer(runner Generator) *Optimizer {
	return &Optimizer{runner: runner}
}

func (o *Optimizer) Generate(req protein_pipeline.DesignRequest, round int, seed string) ([]protein_pipeline.Candidate, error) {
	base := seed
	if base == "" {
		base = req.BaseSequence
	}
	variants, err := o.runner.GenerateVariants(base, round, req.NumCandidates, req.RequiredMotif, req.ForbiddenAAs)
	if err != nil {
		return nil, fmt.Errorf("esm3 generation failed: %w", err)
	}
	items := make([]protein_pipeline.Candidate, 0, len(variants))
	for i, v := range variants {
		items = append(items, protein_pipeline.Candidate{
			ID:       candidateID(round, i+1),
			Sequence: v,
			Round:    round,
		})
	}
	return items, nil
}

func candidateID(round, idx int) string {
	return "r" + itoa(round) + "-c" + itoa(idx)
}

func itoa(v int) string {
	if v == 0 {
		return "0"
	}
	out := ""
	for v > 0 {
		out = string(rune('0'+(v%10))) + out
		v /= 10
	}
	return out
}
