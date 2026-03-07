package protein_pipeline

import (
	"fmt"
	"sort"
)

type planBuilder interface {
	Build(req DesignRequest) DesignPlan
}

type evaluator interface {
	Score(req DesignRequest, candidate Candidate) Candidate
}

type optimizer interface {
	Generate(req DesignRequest, round int, seed string) ([]Candidate, error)
}

type Pipeline struct {
	planner   planBuilder
	evaluator evaluator
	optimizer optimizer
}

func NewPipeline(planner planBuilder, evaluator evaluator, optimizer optimizer) *Pipeline {
	return &Pipeline{planner: planner, evaluator: evaluator, optimizer: optimizer}
}

func (p *Pipeline) Run(req DesignRequest) (DesignResult, error) {
	normalize(&req)
	plan := p.planner.Build(req)

	all := make([]Candidate, 0, req.NumCandidates*req.Rounds)
	bestSeed := req.BaseSequence
	best := Candidate{Score: -9999}

	for round := 1; round <= req.Rounds; round++ {
		batch, err := p.optimizer.Generate(req, round, bestSeed)
		if err != nil {
			return DesignResult{}, fmt.Errorf("round %d generate failed: %w", round, err)
		}
		if len(batch) == 0 {
			return DesignResult{}, fmt.Errorf("round %d generate returned empty candidates", round)
		}
		for _, c := range batch {
			scored := p.evaluator.Score(req, c)
			all = append(all, scored)
			if scored.Score > best.Score {
				best = scored
				bestSeed = scored.Sequence
			}
		}
	}

	sort.Slice(all, func(i, j int) bool {
		return all[i].Score > all[j].Score
	})

	return DesignResult{
		Plan:           plan,
		BestCandidate:  best,
		AllCandidates:  all,
		TotalGenerated: len(all),
		Rounds:         req.Rounds,
	}, nil
}

func normalize(req *DesignRequest) {
	if req.NumCandidates <= 0 {
		req.NumCandidates = 8
	}
	if req.Rounds <= 0 {
		req.Rounds = 3
	}
}
