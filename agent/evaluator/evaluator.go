package evaluator

import (
	"fmt"
	"math"
	"strings"

	"esm3-agent/protein_pipeline"
)

type Evaluator struct{}

func NewEvaluator() *Evaluator {
	return &Evaluator{}
}

func (e *Evaluator) Score(req protein_pipeline.DesignRequest, candidate protein_pipeline.Candidate) protein_pipeline.Candidate {
	seq := strings.ToUpper(strings.TrimSpace(candidate.Sequence))
	length := float64(len(seq))
	if length == 0 {
		candidate.Score = 0
		candidate.Reason = "empty sequence"
		candidate.Metrics = map[string]float64{"length": 0}
		return candidate
	}

	hydrophobicRatio := float64(countAny(seq, "AILMFWYV")) / length
	glySerRatio := float64(countAny(seq, "GS")) / length
	chargedRatio := float64(countAny(seq, "KRDE")) / length

	stability := clamp01(1 - math.Abs(hydrophobicRatio-0.35))
	fluorProxy := clamp01(glySerRatio * 2.2)
	chargePenalty := clamp01(math.Max(0, chargedRatio-0.22))
	lengthPenalty := 0.0
	if req.MinLength > 0 && len(seq) < req.MinLength {
		lengthPenalty += clamp01(float64(req.MinLength-len(seq)) / float64(req.MinLength))
	}
	if req.MaxLength > 0 && len(seq) > req.MaxLength {
		lengthPenalty += clamp01(float64(len(seq)-req.MaxLength) / float64(req.MaxLength))
	}

	motifPenalty := 0.0
	if req.RequiredMotif != "" && !strings.Contains(seq, strings.ToUpper(req.RequiredMotif)) {
		motifPenalty = 1.0
	}
	forbiddenPenalty := 0.0
	if req.ForbiddenAAs != "" && containsAny(seq, strings.ToUpper(req.ForbiddenAAs)) {
		forbiddenPenalty = 1.0
	}

	// Weighted additive score: positive terms reward composition for GFP-like fluorescence/stability;
	// penalty terms discourage risks and hard-constraint violations.
	score := (stability * 0.45) + (fluorProxy * 0.75) - (chargePenalty * 0.55) - (lengthPenalty * 0.30) - (motifPenalty * 0.35) - (forbiddenPenalty * 0.40)

	candidate.Score = score
	candidate.Metrics = map[string]float64{
		"length":              length,
		"hydrophobic_ratio":   hydrophobicRatio,
		"gly_ser_ratio":       glySerRatio,
		"charged_ratio":       chargedRatio,
		"stability_component": stability,
		"fluor_component":     fluorProxy,
		"charge_penalty":      chargePenalty,
		"length_penalty":      lengthPenalty,
		"motif_penalty":       motifPenalty,
		"forbidden_penalty":   forbiddenPenalty,
	}
	candidate.Reason = fmt.Sprintf("weighted score: +0.45*stability +0.75*fluor -0.55*charge -0.30*length -0.35*motif -0.40*forbidden; metrics=%v", candidate.Metrics)
	return candidate
}

func clamp01(v float64) float64 {
	if v < 0 {
		return 0
	}
	if v > 1 {
		return 1
	}
	return v
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
