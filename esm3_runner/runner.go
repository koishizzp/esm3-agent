package esm3_runner

import (
	"fmt"
	"math/rand"
	"strings"
	"time"
)

type Client struct {
	rand *rand.Rand
}

func NewClient() *Client {
	return &Client{rand: rand.New(rand.NewSource(time.Now().UnixNano()))}
}

func (c *Client) GenerateVariants(base string, round, n int, requiredMotif, forbidden string) []string {
	if n <= 0 {
		n = 6
	}
	if base == "" {
		base = defaultGFP
	}
	forbidden = strings.ToUpper(forbidden)

	variants := make([]string, 0, n)
	for len(variants) < n {
		candidate := mutate(base, c.rand, round)
		if requiredMotif != "" && !strings.Contains(candidate, strings.ToUpper(requiredMotif)) {
			idx := c.rand.Intn(len(candidate) - len(requiredMotif) + 1)
			candidate = candidate[:idx] + strings.ToUpper(requiredMotif) + candidate[idx+len(requiredMotif):]
		}
		if forbidden != "" && hasForbidden(candidate, forbidden) {
			continue
		}
		variants = append(variants, candidate)
	}
	return variants
}

func mutate(base string, r *rand.Rand, round int) string {
	seq := []rune(strings.ToUpper(base))
	letters := []rune("ACDEFGHIKLMNPQRSTVWY")
	changes := 1 + (round % 2)
	for i := 0; i < changes; i++ {
		idx := r.Intn(len(seq))
		seq[idx] = letters[r.Intn(len(letters))]
	}
	return string(seq)
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
	return fmt.Sprintf("mock-esm3-runner")
}
