package mev

import "math/big"

// JITPlanFull extends JITPlan with IL estimate and execution gate.
type JITPlanFull struct {
	JITPlan
	ILEstimateWei *big.Int
	ShouldExecute bool
	SkipReason    string
}

// estimateJITILWei — Go mirror of Python estimate_jit_il_wei.
func estimateJITILWei(victimSwap, poolETH, poolToken, jitETH, jitLiq int64) *big.Int {
	if poolETH <= 0 || poolToken <= 0 || jitETH <= 0 {
		return big.NewInt(0)
	}
	fee := victimSwap * JITFeeBPSDefault / 10_000
	netV := victimSwap - fee
	outV := amountOut64(netV, poolETH, poolToken)
	eth2 := poolETH + netV
	tok2 := poolToken - outV
	jitEthShare := eth2 * jitETH / max64(poolETH+jitETH, 1)
	jitTokShare := tok2 * jitLiq / max64(poolToken+jitLiq, 1)
	if jitTokShare <= 0 {
		il := jitETH - jitEthShare
		if il < 0 {
			return big.NewInt(0)
		}
		return big.NewInt(il)
	}
	marginal := eth2 * 1_000_000 / max64(tok2, 1)
	mtm := jitEthShare + jitTokShare*marginal/1_000_000
	il := jitETH - mtm
	if il < 0 {
		return big.NewInt(0)
	}
	return big.NewInt(il)
}

func amountOut64(amountIn, reserveIn, reserveOut int64) int64 {
	if amountIn <= 0 || reserveIn <= 0 || reserveOut <= 0 {
		return 0
	}
	return amountIn * reserveOut / (reserveIn + amountIn)
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

// PlanJITWithIL applies IL haircut to base JIT plan.
func PlanJITWithIL(base *JITPlan, ilWei *big.Int) *JITPlanFull {
	net := new(big.Int).Sub(base.NetWei, ilWei)
	full := &JITPlanFull{
		JITPlan:       *base,
		ILEstimateWei: new(big.Int).Set(ilWei),
		ShouldExecute: net.Sign() > 0,
	}
	full.NetWei = net
	if base.GasCostWei.Cmp(base.FeeShareWei) >= 0 {
		full.ShouldExecute = false
		full.SkipReason = "gas_exceeds_fee_share"
	} else if ilWei.Cmp(base.FeeShareWei) >= 0 {
		full.ShouldExecute = false
		full.SkipReason = "il_exceeds_fee_share"
	} else if net.Sign() <= 0 {
		full.ShouldExecute = false
		full.SkipReason = "net_non_positive"
	}
	return full
}

// BackrunPlanFull adds bridge fee and skip reason.
type BackrunPlanFull struct {
	BackrunPlan
	BridgeFeeWei  *big.Int
	NetProfitWei  *big.Int
	ShouldExecute bool
	SkipReason    string
}

// PlanBackrunWithBridge classifies multi-pool arb with bridge cost.
func PlanBackrunWithBridge(arbETH, poolAOut, poolBOut, bridgeFee int64) *BackrunPlanFull {
	gross := poolAOut - arbETH
	net := gross - bridgeFee
	full := &BackrunPlanFull{
		BackrunPlan: BackrunPlan{
			VictimSwapWei: big.NewInt(0),
			ArbETHWei:     big.NewInt(arbETH),
			EstProfitWei:  big.NewInt(gross),
			Profitable:    net > 0 && poolBOut > poolAOut,
		},
		BridgeFeeWei:  big.NewInt(bridgeFee),
		NetProfitWei:  big.NewInt(net),
		ShouldExecute: net > 0 && poolBOut > poolAOut,
	}
	if poolBOut <= poolAOut {
		full.ShouldExecute = false
		full.SkipReason = "no_cross_pool_spread"
	} else if bridgeFee >= gross {
		full.ShouldExecute = false
		full.SkipReason = "bridge_fee_kills_profit"
	} else if net <= 0 {
		full.ShouldExecute = false
		full.SkipReason = "net_non_positive"
	}
	return full
}

// ForkSandwichSim models BSC fork sandwich with network fees.
type ForkSandwichSim struct {
	GrossProfitWei *big.Int
	NetworkFeeWei  *big.Int
	NetProfitWei   *big.Int
	ShouldExecute  bool
	SkipReason     string
}

// SimulateForkSandwich pure reserve-based sandwich PnL.
func SimulateForkSandwich(reserveETH, reserveToken, victim, frontrun, networkFee int64) ForkSandwichSim {
	ethRes, tokRes := reserveETH, reserveToken
	const feeBPS = 25

	swapIn := func(amount, rin, rout int64) (int64, int64, int64) {
		fee := amount * feeBPS / 10_000
		net := amount - fee
		out := amountOut64(net, rin, rout)
		return out, rin + net, rout - out
	}

	frOut, ethRes, tokRes := swapIn(frontrun, ethRes, tokRes)
	_, ethRes, tokRes = swapIn(victim, ethRes, tokRes)
	ethBack := amountOut64(frOut, tokRes, ethRes)
	gross := ethBack - frontrun
	net := gross - networkFee

	sim := ForkSandwichSim{
		GrossProfitWei: big.NewInt(gross),
		NetworkFeeWei:  big.NewInt(networkFee),
		NetProfitWei:   big.NewInt(net),
		ShouldExecute:  net > 0,
	}
	if gross <= 0 {
		sim.ShouldExecute = false
		sim.SkipReason = "zero_or_negative_gross_spread"
	} else if net <= 0 {
		sim.ShouldExecute = false
		sim.SkipReason = "network_fees_exceed_gross"
	}
	return sim
}
