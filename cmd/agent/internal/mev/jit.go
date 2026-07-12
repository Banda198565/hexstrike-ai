package mev

import "math/big"

// JITGasDefaults for sandbox profit classifier (fee vs gas).
const (
	JITGasUnitsDefault  = 450_000
	JITGasPriceDefault  = 1_000_000_000 // 1 gwei
	JITFeeBPSDefault    = 30
)

// JITPlan models one-block liquidity injection profit.
type JITPlan struct {
	VictimSwapWei   *big.Int
	JITLiquidity    *big.Int
	TotalLiqBefore  *big.Int
	FeeShareWei     *big.Int
	GasCostWei      *big.Int
	NetWei          *big.Int
	Profitable      bool
}

// PlanJIT estimates whether JIT fee capture beats gas (offensive classifier).
func PlanJIT(victimSwapWei, jitLiquidity, totalLiqBefore int64, gasUnits, gasPrice int64) *JITPlan {
	if gasUnits <= 0 {
		gasUnits = JITGasUnitsDefault
	}
	if gasPrice <= 0 {
		gasPrice = JITGasPriceDefault
	}
	victim := big.NewInt(victimSwapWei)
	jit := big.NewInt(jitLiquidity)
	total := big.NewInt(totalLiqBefore)
	if total.Sign() <= 0 {
		total = big.NewInt(1)
	}

	feeTotal := new(big.Int).Mul(victim, big.NewInt(JITFeeBPSDefault))
	feeTotal.Div(feeTotal, big.NewInt(10_000))

	denom := new(big.Int).Add(total, jit)
	share := new(big.Int).Mul(feeTotal, jit)
	share.Div(share, denom)

	gasCost := big.NewInt(gasUnits * gasPrice)
	net := new(big.Int).Sub(share, gasCost)

	return &JITPlan{
		VictimSwapWei:  victim,
		JITLiquidity:   jit,
		TotalLiqBefore: total,
		FeeShareWei:    share,
		GasCostWei:     gasCost,
		NetWei:         net,
		Profitable:     net.Sign() > 0,
	}
}

// BackrunPlan models cross-pool arb after victim swap.
type BackrunPlan struct {
	VictimSwapWei    *big.Int
	ArbETHWei        *big.Int
	EstProfitWei     *big.Int
	SpreadBPS        int
	Profitable       bool
}

// PlanBackrun estimates arb when poolB quote beats poolA post-victim (simplified).
func PlanBackrun(victimSwap, arbETH, poolAOut, poolBOut int64) *BackrunPlan {
	profit := poolAOut - arbETH
	spread := int64(0)
	if arbETH > 0 {
		spread = (profit * 10_000) / arbETH
	}
	return &BackrunPlan{
		VictimSwapWei: big.NewInt(victimSwap),
		ArbETHWei:     big.NewInt(arbETH),
		EstProfitWei:  big.NewInt(profit),
		SpreadBPS:     int(spread),
		Profitable:    profit > 0 && poolBOut > poolAOut,
	}
}
