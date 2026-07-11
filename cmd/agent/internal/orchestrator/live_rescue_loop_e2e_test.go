package orchestrator

import (
	"context"
	"crypto/ecdsa"
	"fmt"
	"math/big"
	"net/http"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/ethclient"
	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/monitor"
	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/relay"
	txpkg "github.com/hexstrike-ai/hexstrike/cmd/agent/internal/tx"
)

// failBundleClient simulates Puissant unavailable on local Anvil (forces public fallback).
type failBundleClient struct{}

func (failBundleClient) SendBundle(context.Context, relay.BundleParams) (string, error) {
	return "", fmt.Errorf("puissant: not available on anvil fork")
}

// TestLiveRescueLoopAnvilE2E runs PrepareRescue → EIP-1559 sign → PuissantRelay.Submit → Watcher.Watch.
// Driven by scripts/sandbox/test-live-rescue-loop.sh (RUN_LIVE_LOOP_E2E=1).
func TestLiveRescueLoopAnvilE2E(t *testing.T) {
	if os.Getenv("RUN_LIVE_LOOP_E2E") != "1" {
		t.Skip("set RUN_LIVE_LOOP_E2E=1 — use scripts/sandbox/test-live-rescue-loop.sh")
	}

	rpc := envOr("RPC_URL", "http://127.0.0.1:8545")
	bot := strings.TrimSpace(os.Getenv("BOT_ADDRESS"))
	funder := strings.TrimSpace(os.Getenv("FUNDER_ADDRESS"))
	keyHex := strings.TrimPrefix(strings.TrimSpace(os.Getenv("BOT_PRIVATE_KEY")), "0x")
	if bot == "" || funder == "" || keyHex == "" {
		t.Fatal("BOT_ADDRESS, FUNDER_ADDRESS, BOT_PRIVATE_KEY required")
	}

	rescueValue := parseWeiEnv("RESCUE_VALUE_WEI", 1_000_000_000_000_000)
	balanceWei := parseWeiEnv("BOT_BALANCE_WEI", 300_000_000_000_000_000)

	botKey, err := crypto.HexToECDSA(keyHex)
	if err != nil {
		t.Fatal(err)
	}
	if got := crypto.PubkeyToAddress(botKey.PublicKey).Hex(); !strings.EqualFold(got, bot) {
		t.Fatalf("BOT_PRIVATE_KEY mismatch: %s vs %s", got, bot)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	client, err := ethclient.Dial(rpc)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()

	chainID, err := client.ChainID(ctx)
	if err != nil {
		t.Fatal(err)
	}

	allowed := []string{funder}
	if v := os.Getenv("ALLOWED_FUNDERS"); v != "" {
		allowed = strings.Split(v, ",")
	}
	fc := txpkg.NewFeeCalculator(client, 120)
	eng, err := NewEngine(Config{
		AllowedFunders: allowed,
		FeeCalculator:  fc,
		FailClosed:     false,
	})
	if err != nil {
		t.Fatal(err)
	}

	funderAddr := common.HexToAddress(funder)
	funderBefore, err := client.BalanceAt(ctx, funderAddr, nil)
	if err != nil {
		t.Fatal(err)
	}

	req := RescueRequest{
		BotAddress:    bot,
		FunderAddress: funder,
		BalanceWei:    balanceWei,
		RescueValue:   rescueValue,
		ChainID:       chainID.Int64(),
		DryRun:        false,
	}
	plan, err := eng.PrepareRescue(ctx, req)
	if err != nil {
		t.Fatalf("PrepareRescue: %v", err)
	}
	if plan.Fees == nil {
		t.Fatal("expected EIP-1559 fee suggestion")
	}

	rawTx, txHashLocal, err := signRescueTx(ctx, client, botKey, chainID, common.HexToAddress(bot), funderAddr, rescueValue, plan.Fees)
	if err != nil {
		t.Fatalf("sign rescue tx: %v", err)
	}

	pubURL := envOr("RELAY_PUBLIC_RPC", rpc)
	relayClient := relay.DefaultPuissantRelay()
	relayClient.GasBumpSteps = []int{0}
	relayClient.MaxWaitBlocks = 1
	relayClient.PollInterval = 10 * time.Millisecond
	relayClient.Bundle = failBundleClient{}
	relayClient.Public = &relay.PublicRPC{URL: pubURL, HTTPClient: &http.Client{Timeout: 10 * time.Second}}

	submitRes, err := relayClient.Submit(ctx, relay.SubmitRequest{
		RawTx:   rawTx,
		ChainID: chainID.Int64(),
	})
	if err != nil {
		t.Fatalf("PuissantRelay.Submit: %v", err)
	}
	if submitRes.Strategy != relay.StrategyPublic {
		t.Fatalf("expected public fallback on anvil, got %s", submitRes.Strategy)
	}
	txHash := submitRes.TxHash
	if !strings.HasPrefix(txHash, "0x") {
		txHash = "0x" + txHash
	}
	if !strings.EqualFold(txHash, txHashLocal) {
		t.Logf("relay tx hash %s (local %s)", txHash, txHashLocal)
	}

	fetcher, err := monitor.NewEthReceiptFetcher(rpc)
	if err != nil {
		t.Fatal(err)
	}
	watcher := &monitor.Watcher{
		Fetcher:      fetcher,
		Releaser:     eng,
		PollInterval: 100 * time.Millisecond,
		Timeout:      30 * time.Second,
	}
	rcpt, err := watcher.Watch(ctx, txHash, plan.DedupKey)
	if err != nil {
		t.Fatalf("Watcher.Watch: %v", err)
	}
	if rcpt == nil || !rcpt.Success || rcpt.Status != monitor.ReceiptSuccess {
		t.Fatalf("expected success receipt, got %+v", rcpt)
	}

	funderAfter, err := client.BalanceAt(ctx, funderAddr, nil)
	if err != nil {
		t.Fatal(err)
	}
	delta := new(big.Int).Sub(funderAfter, funderBefore)
	if delta.Cmp(rescueValue) != 0 {
		t.Fatalf("funder delta=%s want=%s", delta, rescueValue)
	}

	if _, err := eng.PrepareRescue(ctx, req); err == nil {
		t.Fatal("duplicate PrepareRescue must fail after successful rescue (dedup held)")
	}

	t.Logf("live loop OK tx=%s strategy=%s funder_delta=%s dedup=%s",
		txHash, submitRes.Strategy, delta, plan.DedupKey)
}

func signRescueTx(
	ctx context.Context,
	client *ethclient.Client,
	key *ecdsa.PrivateKey,
	chainID *big.Int,
	from, to common.Address,
	value *big.Int,
	fees *txpkg.FeeSuggestion,
) (raw []byte, hash string, err error) {
	nonce, err := client.PendingNonceAt(ctx, from)
	if err != nil {
		return nil, "", err
	}
	tx := types.NewTx(&types.DynamicFeeTx{
		ChainID:   chainID,
		Nonce:     nonce,
		To:        &to,
		Value:     value,
		Gas:       21_000,
		GasTipCap: fees.GasTipCap,
		GasFeeCap: fees.GasFeeCap,
	})
	signed, err := types.SignTx(tx, types.NewLondonSigner(chainID), key)
	if err != nil {
		return nil, "", err
	}
	raw, err = signed.MarshalBinary()
	if err != nil {
		return nil, "", err
	}
	return raw, signed.Hash().Hex(), nil
}

func envOr(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

func parseWeiEnv(key string, def int64) *big.Int {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return big.NewInt(def)
	}
	n, err := strconv.ParseInt(v, 10, 64)
	if err != nil {
		return big.NewInt(def)
	}
	return big.NewInt(n)
}
