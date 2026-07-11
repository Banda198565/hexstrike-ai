package tx

import (
	"context"
	"math/big"

	"github.com/ethereum/go-ethereum/ethclient"
)

// FeeSuggestion holds EIP-1559 fee envelope.
type FeeSuggestion struct {
	GasFeeCap *big.Int
	GasTipCap *big.Int
}

// FeeCalculator suggests dynamic fees from an RPC client.
type FeeCalculator struct {
	client     *ethclient.Client
	tipPercent int // e.g. 120 = +20%
}

// NewFeeCalculator wraps an ethclient. tipPercent defaults to 120 (+20%).
func NewFeeCalculator(client *ethclient.Client, tipPercent int) *FeeCalculator {
	if tipPercent <= 0 {
		tipPercent = 120
	}
	return &FeeCalculator{client: client, tipPercent: tipPercent}
}

// SuggestAggressiveFees returns EIP-1559 caps with aggressive tip offset.
func (fc *FeeCalculator) SuggestAggressiveFees(ctx context.Context) (*FeeSuggestion, error) {
	tip, err := fc.client.SuggestGasTipCap(ctx)
	if err != nil {
		return nil, err
	}
	header, err := fc.client.HeaderByNumber(ctx, nil)
	if err != nil {
		return nil, err
	}
	baseFee := header.BaseFee
	if baseFee == nil {
		baseFee = big.NewInt(0)
	}
	return CalculateAggressiveFees(baseFee, tip, fc.tipPercent), nil
}

// CalculateAggressiveFees is pure math for tests and offline estimation.
// feeCap = baseFee*2 + aggressiveTip; aggressiveTip = tip * tipPercent / 100.
func CalculateAggressiveFees(baseFee, tip *big.Int, tipPercent int) *FeeSuggestion {
	if tipPercent <= 0 {
		tipPercent = 120
	}
	if baseFee == nil {
		baseFee = big.NewInt(0)
	}
	if tip == nil {
		tip = big.NewInt(0)
	}
	aggressiveTip := new(big.Int).Mul(tip, big.NewInt(int64(tipPercent)))
	aggressiveTip.Div(aggressiveTip, big.NewInt(100))
	feeCap := new(big.Int).Mul(baseFee, big.NewInt(2))
	feeCap.Add(feeCap, aggressiveTip)
	return &FeeSuggestion{GasFeeCap: feeCap, GasTipCap: aggressiveTip}
}
