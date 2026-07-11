// Package relay submits private bundles with BSC Puissant / ETH Flashbots fallback.
package relay

import (
	"context"
	"fmt"
	"time"

	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/tx"
)

// Strategy for bundle delivery.
type Strategy string

const (
	StrategyPrivate Strategy = "private_bundle"
	StrategyPublic  Strategy = "public_mempool"
)

// SubmitRequest is a signed raw tx payload.
type SubmitRequest struct {
	RawTx       []byte
	ChainID     int64
	MaxWait     time.Duration
	BlockTarget int // max blocks before fallback
}

// SubmitResult reports how the tx was sent.
type SubmitResult struct {
	Strategy    Strategy
	BundleID    string
	TxHash      string
	BlocksWaited int
	GasBumpPct  int
}

// PuissantRelay sends BSC bundles via 48Club Puissant with gas bump + public fallback.
type PuissantRelay struct {
	Endpoint       string
	MaxWaitBlocks  int
	GasBumpSteps   []int // e.g. []int{0, 15, 25}
	AllowPublicFallback bool
	FeeCalc        func(ctx context.Context, bumpPct int) (*tx.FeeSuggestion, error)
}

// DefaultPuissantRelay returns BSC-oriented defaults (3-block wait, +15/+25% gas steps).
func DefaultPuissantRelay() *PuissantRelay {
	return &PuissantRelay{
		Endpoint:            "https://puissant-builder.48.club/",
		MaxWaitBlocks:       3,
		GasBumpSteps:        []int{0, 15, 25},
		AllowPublicFallback: true,
	}
}

// Submit tries private bundle with escalating gas; falls back to public mempool if configured.
func (p *PuissantRelay) Submit(ctx context.Context, req SubmitRequest) (*SubmitResult, error) {
	if len(req.RawTx) == 0 {
		return nil, fmt.Errorf("relay: empty raw tx")
	}
	maxBlocks := req.BlockTarget
	if maxBlocks <= 0 {
		maxBlocks = p.MaxWaitBlocks
	}
	if maxBlocks <= 0 {
		maxBlocks = 3
	}

	for step, bump := range p.GasBumpSteps {
		_ = step
		if p.FeeCalc != nil {
			if _, err := p.FeeCalc(ctx, bump); err != nil {
				return nil, fmt.Errorf("relay: fee bump %d%%: %w", bump, err)
			}
		}
		// TODO(P3): HTTP submit to Puissant bundle API
		included := false // stub until live endpoint wired
		if included {
			return &SubmitResult{
				Strategy: StrategyPrivate,
				BundleID: "puissant-stub",
				BlocksWaited: 1,
				GasBumpPct: bump,
			}, nil
		}
	}

	if !p.AllowPublicFallback {
		return nil, fmt.Errorf("relay: private bundle not included after %d blocks", maxBlocks)
	}
	return &SubmitResult{
		Strategy:     StrategyPublic,
		TxHash:       "0x-public-fallback-stub",
		BlocksWaited: maxBlocks,
		GasBumpPct:   p.GasBumpSteps[len(p.GasBumpSteps)-1],
	}, nil
}
