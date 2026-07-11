// Package orchestrator wires guard, entity gate, fee calc, and dedup before signing.
package orchestrator

import (
	"context"
	"fmt"
	"math/big"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/entity"
	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/guard"
	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/tx"
)

// RescueRequest is the pre-sign payload evaluated by the engine.
type RescueRequest struct {
	BotAddress    string
	FunderAddress string
	BalanceWei    *big.Int
	RescueValue   *big.Int
	ChainID       int64
	DryRun        bool
}

// RescuePlan is returned when the engine approves signing.
type RescuePlan struct {
	Strategy  guard.ExecutionStrategy
	Fees      *tx.FeeSuggestion
	DedupKey  string
	AllowedAt time.Time
}

// Engine coordinates P0–P2 checks immediately before signing.
type Engine struct {
	limits   *guard.RouteGuard
	gate     *entity.EntityGate
	fees     *tx.FeeCalculator
	allow    map[string]struct{}
	dedup    sync.Map
	failGate bool
}

// Config for battle engine.
type Config struct {
	BootstrapPath string
	APIKey        string
	FailClosed    bool
	AllowedFunders []string
	FeeCalculator  *tx.FeeCalculator
}

// NewEngine builds an engine from repo-relative defaults.
func NewEngine(cfg Config) (*Engine, error) {
	bootstrap := cfg.BootstrapPath
	if bootstrap == "" {
		bootstrap = defaultBootstrapPath()
	}
	apiKey := cfg.APIKey
	if apiKey == "" {
		apiKey = os.Getenv("ARKHAM_API_KEY")
	}
	eg := entity.NewEntityGate(apiKey, bootstrap, entity.WithFailClosed(cfg.FailClosed))
	if err := eg.Prewarm(); err != nil {
		return nil, fmt.Errorf("entity prewarm: %w", err)
	}
	allow := make(map[string]struct{})
	for _, a := range cfg.AllowedFunders {
		key := strings.ToLower(strings.TrimSpace(a))
		if key != "" {
			allow[key] = struct{}{}
			if eg.IsDenied(a) {
				continue
			}
			eg.AllowAddress(a, "configured_funder", "ALLOWLIST")
		}
	}
	return &Engine{
		limits:   guard.NewRouteGuard(),
		gate:     eg,
		fees:     cfg.FeeCalculator,
		allow:    allow,
		failGate: cfg.FailClosed,
	}, nil
}

func defaultBootstrapPath() string {
	for _, p := range []string{
		"cmd/agent/internal/entity/testdata/entity-gate-bootstrap.json",
		"artifacts/entity-id.json",
	} {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return "cmd/agent/internal/entity/testdata/entity-gate-bootstrap.json"
}

// PrepareRescue runs limits → entity gate → funder allowlist → dedup → fees.
func (e *Engine) PrepareRescue(ctx context.Context, req RescueRequest) (*RescuePlan, error) {
	if req.BalanceWei == nil {
		req.BalanceWei = big.NewInt(0)
	}
	if req.RescueValue == nil {
		req.RescueValue = big.NewInt(0)
	}

	strategy := e.limits.EvaluateCombined(req.BalanceWei, req.RescueValue)
	switch strategy {
	case guard.StrategyBlockNoGas:
		return nil, fmt.Errorf("ENGINE: balance below MIN_GAS")
	case guard.StrategyNoTrigger:
		return nil, fmt.Errorf("ENGINE: THRESHOLD_OK — rescue not required")
	case guard.StrategyEscalate:
		return nil, fmt.Errorf("ENGINE: %s — emit %s for KMS review", strategy, guard.TopicHighValuePending)
	}

	funder := strings.ToLower(strings.TrimSpace(req.FunderAddress))
	if funder == "" {
		return nil, fmt.Errorf("ENGINE: empty funder address")
	}
	if len(e.allow) > 0 {
		if _, ok := e.allow[funder]; !ok {
			return nil, fmt.Errorf("ENGINE: funder %s not in allowlist (attack #06)", req.FunderAddress)
		}
	}

	ok, err := e.gate.VerifyAddress(ctx, req.FunderAddress)
	if err != nil || !ok {
		if err != nil {
			return nil, err
		}
		return nil, fmt.Errorf("ENGINE: entity gate denied funder %s", req.FunderAddress)
	}

	dedupKey := fmt.Sprintf("%s:%s:%s", req.BotAddress, req.FunderAddress, req.RescueValue.String())
	if _, loaded := e.dedup.LoadOrStore(dedupKey, time.Now().UTC()); loaded {
		return nil, fmt.Errorf("ENGINE: duplicate rescue suppressed (attack #02/#04)")
	}

	var fees *tx.FeeSuggestion
	if e.fees != nil && !req.DryRun {
		fees, err = e.fees.SuggestAggressiveFees(ctx)
		if err != nil {
			return nil, fmt.Errorf("ENGINE: fee suggestion failed: %w", err)
		}
	}

	return &RescuePlan{
		Strategy:  guard.StrategyAutoSign,
		Fees:      fees,
		DedupKey:  dedupKey,
		AllowedAt: time.Now().UTC(),
	}, nil
}

// ReleaseDedup clears a dedup key after on-chain revert (monitor.HandleReceipt).
func (e *Engine) ReleaseDedup(dedupKey string) {
	e.dedup.Delete(dedupKey)
}

// HandleReceipt processes tx receipt; releases dedup on failure/revert.
func (e *Engine) HandleReceipt(dedupKey string, success bool, txHash string) error {
	if success {
		return nil
	}
	e.ReleaseDedup(dedupKey)
	return fmt.Errorf("ENGINE: tx %s failed — dedup released for retry", txHash)
}

// BlockFunder marks an address compromised (runtime policy update).
func (e *Engine) BlockFunder(address, reason string) {
	e.gate.BlockAddress(address, reason, "COMPROMISED")
}
