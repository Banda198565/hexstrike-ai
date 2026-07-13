package watch

import (
	"context"
	"crypto/ecdsa"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethclient"
	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/monitor"
	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/orchestrator"
	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/relay"
	txpkg "github.com/hexstrike-ai/hexstrike/cmd/agent/internal/tx"
)

// Run executes the mainnet rescue watch loop until ctx is cancelled.
func Run(ctx context.Context, cfg Config) error {
	if err := cfg.Validate(); err != nil {
		return err
	}
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = 10 * time.Second
	}

	client, err := ethclient.Dial(cfg.RPCURL)
	if err != nil {
		return fmt.Errorf("watch: rpc dial: %w", err)
	}
	defer client.Close()

	engCfg := orchestrator.Config{
		AllowedFunders: cfg.AllowedFunders,
		FeeCalculator:  txpkg.NewFeeCalculator(client, 120),
		FailClosed:     cfg.FailClosedGate,
	}
	if cfg.BootstrapPath != "" {
		engCfg.BootstrapPath = cfg.BootstrapPath
	}
	eng, err := orchestrator.NewEngine(engCfg)
	if err != nil {
		return fmt.Errorf("watch: engine: %w", err)
	}

	var botECDSA *ecdsa.PrivateKey
	if cfg.BotPrivateKey != "" {
		k, kerr := crypto.HexToECDSA(cfg.BotPrivateKey)
		if kerr != nil {
			return fmt.Errorf("watch: bot key: %w", kerr)
		}
		got := crypto.PubkeyToAddress(k.PublicKey).Hex()
		if !strings.EqualFold(got, cfg.BotAddress) {
			return fmt.Errorf("watch: BOT_PRIVATE_KEY mismatch (%s vs %s)", got, cfg.BotAddress)
		}
		botECDSA = k
	}

	mode := "LIVE"
	if cfg.DryRun {
		mode = "DRY_RUN"
	}
	log.Printf("[CORE] Go watch engine started (%s) target=%s bot=%s funder=%s", mode, cfg.TargetWatch, cfg.BotAddress, cfg.FunderAddress)

	targetAddr := common.HexToAddress(cfg.TargetWatch)
	funderAddr := common.HexToAddress(cfg.FunderAddress)

	for {
		if err := pollOnce(ctx, cfg, client, eng, botECDSA, targetAddr, funderAddr); err != nil {
			log.Printf("[watch] poll error: %v", err)
		}
		if cfg.Once {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(cfg.PollInterval):
		}
	}
}

func pollOnce(
	ctx context.Context,
	cfg Config,
	client *ethclient.Client,
	eng *orchestrator.Engine,
	botECDSA *ecdsa.PrivateKey,
	targetAddr, funderAddr common.Address,
) error {
	balance, err := client.BalanceAt(ctx, targetAddr, nil)
	if err != nil {
		return err
	}

	event := map[string]any{
		"ts":           time.Now().UTC().Format(time.RFC3339),
		"target":       cfg.TargetWatch,
		"balance_wei":  balance.String(),
		"threshold_wei": cfg.ThresholdWei.String(),
		"dry_run":      cfg.DryRun,
	}

	if balance.Cmp(cfg.ThresholdWei) >= 0 {
		event["action"] = "none"
		event["result"] = "THRESHOLD_OK"
		return appendEvent(cfg.EventsPath, event)
	}

	event["action"] = "trigger"
	log.Printf("[watch] THRESHOLD HIT balance=%s wei threshold=%s wei", balance, cfg.ThresholdWei)

	chainID, err := client.ChainID(ctx)
	if err != nil {
		event["result"] = "error"
		event["error"] = err.Error()
		_ = appendEvent(cfg.EventsPath, event)
		return err
	}

	req := orchestrator.RescueRequest{
		BotAddress:    cfg.BotAddress,
		FunderAddress: cfg.FunderAddress,
		BalanceWei:    balance,
		RescueValue:   cfg.RescueValueWei,
		ChainID:       chainID.Int64(),
		DryRun:        cfg.DryRun,
	}

	plan, err := eng.PrepareRescue(ctx, req)
	if err != nil {
		event["result"] = "blocked"
		event["error"] = err.Error()
		log.Printf("[watch] PrepareRescue blocked: %v", err)
		return appendEvent(cfg.EventsPath, event)
	}

	if cfg.DryRun {
		event["result"] = "dry_run_signed_skipped"
		event["dedup_key"] = plan.DedupKey
		event["strategy"] = string(plan.Strategy)
		log.Printf("[watch] DRY_RUN rescue approved (dedup=%s)", plan.DedupKey)
		eng.ReleaseDedup(plan.DedupKey)
		return appendEvent(cfg.EventsPath, event)
	}

	if botECDSA == nil {
		return fmt.Errorf("watch: bot private key not loaded")
	}

	from := common.HexToAddress(cfg.BotAddress)
	rawTx, txHashLocal, rescueNonce, err := orchestrator.SignRescueTx(ctx, client, botECDSA, chainID, from, funderAddr, cfg.RescueValueWei, plan.Fees)
	if err != nil {
		event["result"] = "error"
		event["error"] = err.Error()
		_ = appendEvent(cfg.EventsPath, event)
		return err
	}

	relayClient := relay.DefaultPuissantRelay()
	relayClient.Public = &relay.PublicRPC{URL: cfg.PublicRPC, HTTPClient: &http.Client{Timeout: 12 * time.Second}}
	lastFees := plan.Fees
	relayClient.FeeCalc = func(_ context.Context, bumpPct int) (*txpkg.FeeSuggestion, error) {
		if bumpPct == 0 {
			return lastFees, nil
		}
		return txpkg.BumpFeeSuggestionStrict(lastFees, bumpPct), nil
	}

	submitRes, err := relayClient.Submit(ctx, relay.SubmitRequest{
		RawTx:   rawTx,
		ChainID: chainID.Int64(),
		Resign: func(ctx context.Context, bumpPct int, fees *txpkg.FeeSuggestion) ([]byte, error) {
			raw, outFees, rerr := orchestrator.ResignRescueTx(ctx, client, botECDSA, chainID, from, funderAddr, cfg.RescueValueWei, rescueNonce, lastFees, bumpPct, fees)
			if rerr != nil {
				return nil, rerr
			}
			lastFees = outFees
			return raw, nil
		},
	})
	if err != nil {
		event["result"] = "error"
		event["error"] = err.Error()
		eng.ReleaseDedup(plan.DedupKey)
		_ = appendEvent(cfg.EventsPath, event)
		return err
	}

	txHash := submitRes.TxHash
	if txHash == "" {
		txHash = txHashLocal
	}
	event["result"] = "submitted"
	event["tx_hash"] = txHash
	event["relay_strategy"] = string(submitRes.Strategy)
	event["dedup_key"] = plan.DedupKey
	log.Printf("[watch] rescue submitted tx=%s strategy=%s", txHash, submitRes.Strategy)

	fetcher, err := monitor.NewEthReceiptFetcher(cfg.PublicRPC)
	if err == nil {
		watcher := &monitor.Watcher{
			Fetcher:      fetcher,
			Releaser:     eng,
			PollInterval: 500 * time.Millisecond,
			Timeout:      45 * time.Second,
		}
		rcptCtx, cancel := context.WithTimeout(ctx, 50*time.Second)
		rcpt, werr := watcher.Watch(rcptCtx, txHash, plan.DedupKey)
		cancel()
		if werr != nil {
			event["receipt_error"] = werr.Error()
		} else if rcpt != nil {
			event["receipt_success"] = rcpt.Success
		}
	}

	return appendEvent(cfg.EventsPath, event)
}

func appendEvent(path string, event map[string]any) error {
	if path == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	return enc.Encode(event)
}
