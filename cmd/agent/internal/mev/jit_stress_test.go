package mev

import (
	"testing"
)

func TestPlanJITGasSpikeBlocks(t *testing.T) {
	victim := int64(5_000_000_000_000_000_000) // 5 ETH
	plan := PlanJIT(
		victim,
		500*1e15,
		1000*1e15,
		JITGasUnitsDefault,
		JITGasPriceDefault*10_000,
	)
	if plan.Profitable {
		t.Fatalf("expected gas spike to block JIT, net=%s", plan.NetWei)
	}
}

func TestPlanJITLowVictimUnprofitable(t *testing.T) {
	plan := PlanJIT(1e15, 1e18, 1000*1e15, JITGasUnitsDefault, JITGasPriceDefault)
	if plan.Profitable {
		t.Fatal("tiny victim should not beat gas")
	}
}

func TestPlanJITWithILBlocksWhenILExceedsFee(t *testing.T) {
	victim := int64(5_000_000_000_000_000_000) // 5 ETH — int64-safe mirror of Python stress case
	base := PlanJIT(victim, 1e18, 2e18, JITGasUnitsDefault, 1)
	il := estimateJITILWei(victim, 2e18, 2e18, 1e18, 1e18)
	full := PlanJITWithIL(base, il)
	if full.ShouldExecute {
		t.Fatalf("IL should block execution, net=%s il=%s", full.NetWei, full.ILEstimateWei)
	}
}

func TestPlanBackrunBridgeFeeKills(t *testing.T) {
	// gross = 0.1 ETH, bridge = 0.2 ETH → aligned with Python stress case
	plan := PlanBackrunWithBridge(1e18, 11e17, 12e17, 2e17)
	if plan.ShouldExecute {
		t.Fatal("bridge fee should kill arb")
	}
	if plan.SkipReason != "bridge_fee_kills_profit" {
		t.Fatalf("skip=%s", plan.SkipReason)
	}
}

func TestSandwichZeroSpreadNetNegative(t *testing.T) {
	sim := SimulateForkSandwich(1e18, 1e18, 1e18, 1e17, 5e17)
	if sim.ShouldExecute {
		t.Fatal("balanced pool + network fee should skip")
	}
	if sim.NetProfitWei.Sign() > 0 {
		t.Fatalf("net=%s", sim.NetProfitWei)
	}
}
