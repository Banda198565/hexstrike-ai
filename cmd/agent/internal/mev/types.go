package mev

import "math/big"

// SwapKind classifies decoded pending swap transactions.
type SwapKind string

const (
	SwapUnknown          SwapKind = "unknown"
	SwapExactETHForTokens SwapKind = "swap_exact_eth_for_tokens"
	SwapExactTokensForETH SwapKind = "swap_exact_tokens_for_eth"
)

// PendingSwap is a mempool candidate for sandwich simulation.
type PendingSwap struct {
	Hash      string
	From      string
	To        string
	ValueWei  *big.Int
	GasPrice  *big.Int
	GasTipCap *big.Int
	Data      []byte
	Kind      SwapKind
	AmountIn  *big.Int
	MinOut    *big.Int
}

// SandwichPlan is an offensive bundle layout (sandbox simulation only).
type SandwichPlan struct {
	VictimHash   string
	FrontrunWei  *big.Int
	BackrunMinOut *big.Int
	EstProfitWei *big.Int
	GasPremiumPct int
}

// FrontRunPlan competes on gas for the same opportunity.
type FrontRunPlan struct {
	TargetHash      string
	CompetitorGas   *big.Int
	OurGas          *big.Int
	PremiumPct      int
}
