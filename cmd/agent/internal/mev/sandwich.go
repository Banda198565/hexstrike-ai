package mev

import "math/big"

// DefaultGasPremiumPct is the offensive gas bump over victim for frontrun races (sandbox).
const DefaultGasPremiumPct = 15

// PlanSandwich estimates a simple constant-product sandwich on Anvil mock AMM.
// frontrunPct is % of pool ETH reserve used as attacker buy (e.g. 30 = 30%).
func PlanSandwich(victim *PendingSwap, poolETHWei, poolTokenWei int64, frontrunPct int) *SandwichPlan {
	if victim == nil || victim.ValueWei == nil {
		return nil
	}
	if frontrunPct <= 0 {
		frontrunPct = 30
	}

	reserveETH := big.NewInt(poolETHWei)
	reserveToken := big.NewInt(poolTokenWei)
	frontrunWei := new(big.Int).Mul(reserveETH, big.NewInt(int64(frontrunPct)))
	frontrunWei.Div(frontrunWei, big.NewInt(100))

	// Constant product: tokens from frontrun
	tokensOut := amountOut(frontrunWei, reserveETH, reserveToken)

	// Victim swap after frontrun shifts curve
	rETH := new(big.Int).Add(reserveETH, frontrunWei)
	rTok := new(big.Int).Sub(reserveToken, tokensOut)
	victimTokens := amountOut(victim.ValueWei, rETH, rTok)

	// Backrun: sell all tokens acquired in frontrun (simplified)
	rETH2 := new(big.Int).Add(rETH, victim.ValueWei)
	rTok2 := new(big.Int).Sub(rTok, victimTokens)
	ethBack := amountOut(tokensOut, rTok2, rETH2)

	profit := new(big.Int).Sub(ethBack, frontrunWei)

	return &SandwichPlan{
		VictimHash:    victim.Hash,
		FrontrunWei:   frontrunWei,
		BackrunMinOut: big.NewInt(0),
		EstProfitWei:  profit,
		GasPremiumPct: DefaultGasPremiumPct,
	}
}

// PlanFrontRunGas returns gas needed to outbid victim priority fee.
func PlanFrontRunGas(victimGas *big.Int, premiumPct int) *FrontRunPlan {
	if victimGas == nil {
		victimGas = big.NewInt(1_000_000_000)
	}
	if premiumPct <= 0 {
		premiumPct = DefaultGasPremiumPct
	}
	our := new(big.Int).Mul(victimGas, big.NewInt(int64(100+premiumPct)))
	our.Div(our, big.NewInt(100))
	return &FrontRunPlan{
		CompetitorGas: new(big.Int).Set(victimGas),
		OurGas:        our,
		PremiumPct:    premiumPct,
	}
}

// amountOut: x * y = k → out = (amountIn * reserveOut) / (reserveIn + amountIn)
func amountOut(amountIn, reserveIn, reserveOut *big.Int) *big.Int {
	if amountIn.Sign() <= 0 || reserveIn.Sign() <= 0 || reserveOut.Sign() <= 0 {
		return big.NewInt(0)
	}
	num := new(big.Int).Mul(amountIn, reserveOut)
	den := new(big.Int).Add(reserveIn, amountIn)
	if den.Sign() == 0 {
		return big.NewInt(0)
	}
	return num.Div(num, den)
}
