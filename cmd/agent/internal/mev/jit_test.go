package mev

import "testing"

func TestPlanJITProfitableLargeVictim(t *testing.T) {
	victim := int64(5_000_000_000_000_000_000) // 5 ETH
	plan := PlanJIT(victim, 500*1e15, 1000*1e15, 450_000, 1_000_000_000)
	if !plan.Profitable {
		t.Fatalf("expected profitable JIT, net=%s", plan.NetWei)
	}
}

func TestPlanJITNotProfitableTinyVictim(t *testing.T) {
	plan := PlanJIT(1e15, 1e18, 1000*1e15, 450_000, 1_000_000_000)
	if plan.Profitable {
		t.Fatalf("expected unprofitable tiny victim, net=%s", plan.NetWei)
	}
}

func TestPlanBackrunPositiveSpread(t *testing.T) {
	plan := PlanBackrun(3e18, 1e18, 12e17, 15e17)
	if !plan.Profitable {
		t.Fatal("expected profitable backrun")
	}
}
