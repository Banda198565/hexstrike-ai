// Package relay submits private bundles with BSC Puissant / ETH Flashbots fallback.
package relay

import (
	"context"
	"encoding/hex"
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
	Strategy     Strategy
	BundleID     string
	TxHash       string
	BlocksWaited int
	GasBumpPct   int
}

// Client abstracts bundle + public submission (for tests).
type Client interface {
	SendBundle(ctx context.Context, params BundleParams) (string, error)
}

// PuissantRelay sends BSC bundles via 48Club Puissant with gas bump + public fallback.
type PuissantRelay struct {
	Endpoint            string
	MaxWaitBlocks       int
	GasBumpSteps        []int
	AllowPublicFallback bool
	FeeCalc             func(ctx context.Context, bumpPct int) (*tx.FeeSuggestion, error)
	Bundle              Client
	Public              *PublicRPC
	PollInterval        time.Duration
	// StatusQuery overrides bundle status polling (tests); nil → QueryBundleStatus.
	StatusQuery func(ctx context.Context, bundleHash string) (*BundleStatus, error)
}

// DefaultPuissantRelay returns BSC-oriented defaults (3-block wait, +15/+25% gas steps).
func DefaultPuissantRelay() *PuissantRelay {
	return &PuissantRelay{
		Endpoint:            "https://puissant-builder.48.club/",
		MaxWaitBlocks:       3,
		GasBumpSteps:        []int{0, 15, 25},
		AllowPublicFallback: true,
		Bundle:              NewBundleClient(),
		Public:              NewPublicRPC(),
		PollInterval:        2 * time.Second,
	}
}

// Submit tries private bundle with escalating gas; polls status; falls back to public mempool.
func (p *PuissantRelay) Submit(ctx context.Context, req SubmitRequest) (*SubmitResult, error) {
	if len(req.RawTx) == 0 {
		return nil, fmt.Errorf("relay: empty raw tx")
	}
	rawHex := "0x" + hex.EncodeToString(req.RawTx)
	maxBlocks := req.BlockTarget
	if maxBlocks <= 0 {
		maxBlocks = p.MaxWaitBlocks
	}
	if maxBlocks <= 0 {
		maxBlocks = 3
	}
	if p.Bundle == nil {
		p.Bundle = NewBundleClient()
	}
	if p.Public == nil {
		p.Public = NewPublicRPC()
	}

	for _, bump := range p.GasBumpSteps {
		if p.FeeCalc != nil {
			if _, err := p.FeeCalc(ctx, bump); err != nil {
				return nil, fmt.Errorf("relay: fee bump %d%%: %w", bump, err)
			}
		}
		bundleHash, err := p.Bundle.SendBundle(ctx, BundleParams{
			Txs:            []string{rawHex},
			MaxBlockNumber: 0, // builder default current+100
		})
		if err != nil {
			continue
		}
		deadline := time.Now().Add(time.Duration(maxBlocks) * 3 * time.Second)
		statusFn := p.StatusQuery
		if statusFn == nil {
			statusFn = QueryBundleStatus
		}
		for time.Now().Before(deadline) {
			st, qerr := statusFn(ctx, bundleHash)
			if qerr == nil && st != nil && st.Confirmed {
				return &SubmitResult{
					Strategy:     StrategyPrivate,
					BundleID:     bundleHash,
					TxHash:       rawHex,
					BlocksWaited: maxBlocks,
					GasBumpPct:   bump,
				}, nil
			}
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(p.PollInterval):
			}
		}
	}

	if !p.AllowPublicFallback {
		return nil, fmt.Errorf("relay: private bundle not included after %d blocks", maxBlocks)
	}
	txHash, err := p.Public.SendRawTransaction(ctx, rawHex)
	if err != nil {
		return nil, fmt.Errorf("relay: public fallback failed: %w", err)
	}
	return &SubmitResult{
		Strategy:     StrategyPublic,
		TxHash:       txHash,
		BlocksWaited: maxBlocks,
		GasBumpPct:   p.GasBumpSteps[len(p.GasBumpSteps)-1],
	}, nil
}
