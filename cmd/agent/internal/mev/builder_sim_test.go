package mev

import "testing"

func TestSimulateBuilderProfitable(t *testing.T) {
	sim := SimulateBuilder(2e18, 630000000000000, int64(0.01e18), 0)
	if !sim.ShouldExecute {
		t.Fatalf("expected profitable builder sim, net=%d", sim.NetProfitWei)
	}
	if sim.WouldSubmit {
		t.Fatal("dry-run must not submit")
	}
}

func TestSimulateBuilderTipKills(t *testing.T) {
	sim := SimulateBuilder(1e17, 630000000000000, 2e17, 0)
	if sim.ShouldExecute {
		t.Fatal("tip should kill profit")
	}
	if sim.SkipReason != "builder_tip_exceeds_gross" {
		t.Fatalf("skip=%s", sim.SkipReason)
	}
}

func TestBestBuilderAttempt(t *testing.T) {
	best := BestBuilderAttempt(5e17, 630000000000000, int64(0.01e18), []int{0, 15, 25})
	if best == nil || !best.ShouldExecute {
		t.Fatal("expected best attempt profitable")
	}
}
