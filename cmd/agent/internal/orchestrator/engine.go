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

	"github.com/ethereum/go-ethereum/common"
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
	limits           *guard.RouteGuard
	gate             *entity.EntityGate
	fees             *tx.FeeCalculator
	allow            map[string]struct{}
	destAllow        map[string]struct{}
	dedup            sync.Map
	intentDedup      *guard.IntentDedup
	killSwitch       *guard.KillSwitch
	quorum           *guard.QuorumReader
	failGate         bool
	requireAllowlist bool
}

// Config for battle engine.
type Config struct {
	BootstrapPath       string
	APIKey              string
	FailClosed          bool
	RequireAllowlist    bool // empty allowlist → reject (attack #06 bypass deny)
	AllowedFunders      []string
	AllowedDestinations []string
	QuorumRPCURLs       []string
	QuorumMinAgree      int
	FeeCalculator       *tx.FeeCalculator
	KillSwitch          *guard.KillSwitch
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
	destAllow := make(map[string]struct{})
	destList := cfg.AllowedDestinations
	if len(destList) == 0 {
		destList = cfg.AllowedFunders
	}
	for _, a := range destList {
		key := strings.ToLower(strings.TrimSpace(a))
		if key != "" {
			destAllow[key] = struct{}{}
		}
	}
	ks := cfg.KillSwitch
	if ks == nil {
		ks = guard.NewKillSwitch()
	}
	var quorum *guard.QuorumReader
	if len(cfg.QuorumRPCURLs) > 0 {
		minAgree := cfg.QuorumMinAgree
		if minAgree < 1 {
			minAgree = 2
		}
		quorum = &guard.QuorumReader{URLs: cfg.QuorumRPCURLs, MinAgree: minAgree}
	}
	requireAllow := cfg.RequireAllowlist || cfg.FailClosed
	return &Engine{
		limits:           guard.NewRouteGuard(),
		gate:             eg,
		fees:             cfg.FeeCalculator,
		allow:            allow,
		destAllow:        destAllow,
		intentDedup:      guard.NewIntentDedup(),
		killSwitch:       ks,
		quorum:           quorum,
		failGate:         cfg.FailClosed,
		requireAllowlist: requireAllow,
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

// PrepareRescue runs limits → kill switch → entity gate → allowlist → intent dedup → fees.
func (e *Engine) PrepareRescue(ctx context.Context, req RescueRequest) (*RescuePlan, error) {
	if req.BalanceWei == nil {
		req.BalanceWei = big.NewInt(0)
	}
	if req.RescueValue == nil {
		req.RescueValue = big.NewInt(0)
	}

	if engaged, reason := e.killSwitch.Engaged(); engaged {
		return nil, fmt.Errorf("ENGINE: kill switch engaged — %s", reason)
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
	if e.requireAllowlist && len(e.allow) == 0 && len(e.destAllow) == 0 {
		return nil, fmt.Errorf("ENGINE: allowlist required (attack #06) — empty ALLOWED_FUNDERS/DESTINATIONS")
	}
	if len(e.allow) > 0 {
		if _, ok := e.allow[funder]; !ok {
			return nil, fmt.Errorf("ENGINE: funder %s not in allowlist (attack #06) BLOCK_COMPROMISED_FUNDER", req.FunderAddress)
		}
	}
	if len(e.destAllow) > 0 {
		if _, ok := e.destAllow[funder]; !ok {
			return nil, fmt.Errorf("ENGINE: destination %s not in allowlist (attack #06) BLOCK_COMPROMISED_FUNDER", req.FunderAddress)
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

// ClaimSignIntent binds intent_hash+nonce before sign (TOCTOU + dedup).
func (e *Engine) ClaimSignIntent(to string, value *big.Int, chainID int64, nonce uint64) (string, error) {
	if e.intentDedup == nil {
		return guard.IntentHash(to, value, "0x", chainID, nonce), nil
	}
	ih := guard.IntentHash(to, value, "0x", chainID, nonce)
	if !e.intentDedup.Claim(ih, nonce) {
		return ih, fmt.Errorf("ENGINE: duplicate intent suppressed (intent_hash+nonce)")
	}
	return ih, nil
}

// VerifyPostSign rechecks balance+nonce via quorum before broadcast (TOCTOU).
func (e *Engine) VerifyPostSign(
	ctx context.Context,
	botAddress string,
	expectedNonce uint64,
	balanceBefore *big.Int,
	intentHash string,
) error {
	if e.quorum == nil {
		return nil
	}
	addr := common.HexToAddress(botAddress)
	bal, err := e.quorum.BalanceQuorum(ctx, addr)
	if err != nil {
		if e.intentDedup != nil {
			e.intentDedup.Release(intentHash, expectedNonce)
		}
		return fmt.Errorf("ENGINE: post-sign quorum balance failed: %w", err)
	}
	nonce, err := e.quorum.NonceQuorum(ctx, addr)
	if err != nil {
		if e.intentDedup != nil {
			e.intentDedup.Release(intentHash, expectedNonce)
		}
		return fmt.Errorf("ENGINE: post-sign quorum nonce failed: %w", err)
	}
	drift, reasons := guard.PostSignDrift(expectedNonce, balanceBefore, guard.PostSignSnapshot{
		BalanceWei: bal,
		Nonce:      nonce,
	})
	if drift {
		if e.intentDedup != nil {
			e.intentDedup.Release(intentHash, expectedNonce)
		}
		return fmt.Errorf("ENGINE: post-sign drift %v — drop tx (TOCTOU)", reasons)
	}
	return nil
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
