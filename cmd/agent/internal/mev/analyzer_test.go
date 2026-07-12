package mev

import (
	"encoding/hex"
	"math/big"
	"testing"
)

func TestClassifySwapETHForTokens(t *testing.T) {
	// swapExactETHForTokens(uint256 amountOutMin, address[] path, address to, uint256 deadline)
	data, _ := hex.DecodeString("7ff36ab5" + "0000000000000000000000000000000000000000000000000de0b6b3a7640000")
	kind, minOut := ClassifySwap(data)
	if kind != SwapExactETHForTokens {
		t.Fatalf("kind=%s", kind)
	}
	if minOut.Cmp(big.NewInt(1e18)) != 0 {
		t.Fatalf("minOut=%s", minOut)
	}
}

func TestIsSandwichCandidate(t *testing.T) {
	data, _ := hex.DecodeString("7ff36ab50000000000000000000000000000000000000000000000000000000000000000")
	if !IsSandwichCandidate(big.NewInt(1e18), data) {
		t.Fatal("expected candidate")
	}
	if IsSandwichCandidate(big.NewInt(0), data) {
		t.Fatal("zero value should not be candidate")
	}
}

func TestPlanSandwichProfitPositive(t *testing.T) {
	victim := &PendingSwap{
		Hash:     "0xabc",
		ValueWei: big.NewInt(1e18),
		Kind:     SwapExactETHForTokens,
	}
	pool := int64(1_000_000_000_000_000_000) // 1 ETH reserve each side
	plan := PlanSandwich(victim, pool, pool, 30)
	if plan == nil {
		t.Fatal("nil plan")
	}
	if plan.EstProfitWei.Sign() <= 0 {
		t.Fatalf("expected positive profit estimate, got %s", plan.EstProfitWei)
	}
}

func TestPlanFrontRunGas(t *testing.T) {
	plan := PlanFrontRunGas(big.NewInt(1_000_000_000), 15)
	if plan.OurGas.Cmp(plan.CompetitorGas) <= 0 {
		t.Fatalf("our gas should exceed victim: %s vs %s", plan.OurGas, plan.CompetitorGas)
	}
}
