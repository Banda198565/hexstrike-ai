package mev

// BuilderSim models Puissant/48.club bundle dry-run profitability.
type BuilderSim struct {
	GrossProfitWei  int64
	NetworkFeeWei   int64
	BuilderTipWei   int64
	GasBumpPct      int
	NetProfitWei    int64
	ShouldExecute   bool
	SkipReason      string
	WouldSubmit     bool
}

// SimulateBuilder estimates bundle net after tip + gas bumps (no submit).
func SimulateBuilder(gross, networkFee, builderTip int64, gasBumpPct int) *BuilderSim {
	bumpCost := networkFee * int64(gasBumpPct) / 100
	net := gross - networkFee - builderTip - bumpCost
	sim := &BuilderSim{
		GrossProfitWei: gross,
		NetworkFeeWei:  networkFee,
		BuilderTipWei:  builderTip,
		GasBumpPct:     gasBumpPct,
		NetProfitWei:   net,
		ShouldExecute:  net > 0 && gross > 0,
		WouldSubmit:    false,
	}
	if gross <= 0 {
		sim.ShouldExecute = false
		sim.SkipReason = "zero_or_negative_gross_spread"
	} else if builderTip >= gross {
		sim.ShouldExecute = false
		sim.SkipReason = "builder_tip_exceeds_gross"
	} else if net <= 0 {
		sim.ShouldExecute = false
		sim.SkipReason = "builder_costs_exceed_profit"
	}
	return sim
}

// BestBuilderAttempt picks max net across gas bump ladder.
func BestBuilderAttempt(gross, networkFee, builderTip int64, bumps []int) *BuilderSim {
	var best *BuilderSim
	for _, b := range bumps {
		s := SimulateBuilder(gross, networkFee, builderTip, b)
		if best == nil || s.NetProfitWei > best.NetProfitWei {
			best = s
		}
	}
	return best
}
