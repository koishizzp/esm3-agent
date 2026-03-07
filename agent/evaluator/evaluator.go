package evaluator

import (
	"math"
	"strings"

	"esm3-agent/protein_pipeline"
)

type Evaluator struct{}

func NewEvaluator() *Evaluator {
	return &Evaluator{}
}

func (e *Evaluator) Score(req protein_pipeline.DesignRequest, candidate protein_pipeline.Candidate) protein_pipeline.Candidate {
	seq := strings.ToUpper(candidate.Sequence)
	length := float64(len(seq))
	if length == 0 {
		candidate.Score = 0
		candidate.Reason = "empty sequence"
		return candidate
	}

	hydrophobic := countAny(seq, "AILMFWYV")
	glySer := countAny(seq, "GS")
	charged := countAny(seq, "KRDE")

	stability := 1 - math.Abs((float64(hydrophobic)/length)-0.35)
	fluorProxy := (float64(glySer) / length) * 2.2
	compositionPenalty := math.Max(0, (float64(charged)/length)-0.22)

	score := (stability * 0.45) + (fluorProxy * 0.75) - (compositionPenalty * 0.55)

	if req.RequiredMotif != "" && !strings.Contains(seq, strings.ToUpper(req.RequiredMotif)) {
		score -= 0.35
	}
	if req.ForbiddenAAs != "" && containsAny(seq, strings.ToUpper(req.ForbiddenAAs)) {
		score -= 0.4
	}

	candidate.Score = score
	candidate.Reason = "high fluorescence proxy and balanced composition"
	return candidate
}

func countAny(seq, chars string) int {
	total := 0
	for _, aa := range seq {
		if strings.ContainsRune(chars, aa) {
			total++
		}
	}
	return total
}

func containsAny(seq, chars string) bool {
	for _, aa := range chars {
		if strings.ContainsRune(seq, aa) {
			return true
		}
	}
	return false
}
