package protein_pipeline

type DesignRequest struct {
	TargetProtein   string `json:"target_protein"`
	Objective       string `json:"objective"`
	BaseSequence    string `json:"base_sequence"`
	NumCandidates   int    `json:"num_candidates"`
	Rounds          int    `json:"rounds"`
	MinLength       int    `json:"min_length"`
	MaxLength       int    `json:"max_length"`
	RequiredMotif   string `json:"required_motif"`
	ForbiddenAAs    string `json:"forbidden_aas"`
	TemperatureHint string `json:"temperature_hint"`
}

type DesignPlan struct {
	Strategy       string   `json:"strategy"`
	MutationPolicy string   `json:"mutation_policy"`
	ScoringFocus   []string `json:"scoring_focus"`
}

type Candidate struct {
	ID       string             `json:"id"`
	Sequence string             `json:"sequence"`
	Round    int                `json:"round"`
	Score    float64            `json:"score"`
	Reason   string             `json:"reason"`
	Metrics  map[string]float64 `json:"metrics,omitempty"`
}

type DesignResult struct {
	Plan           DesignPlan  `json:"plan"`
	BestCandidate  Candidate   `json:"best_candidate"`
	AllCandidates  []Candidate `json:"all_candidates"`
	TotalGenerated int         `json:"total_generated"`
	Rounds         int         `json:"rounds"`
}
