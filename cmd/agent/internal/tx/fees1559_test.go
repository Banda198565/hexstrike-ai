package tx

import (
	"math/big"
	"testing"
)

func TestCalculateAggressiveFees(t *testing.T) {
	base := big.NewInt(30_000_000_000)       // 30 gwei
	tip := big.NewInt(2_000_000_000)         // 2 gwei
	fees := CalculateAggressiveFees(base, tip, 120)
	// tip +20% = 2.4 gwei
	wantTip := int64(2_400_000_000)
	if fees.GasTipCap.Int64() != wantTip {
		t.Fatalf("tip cap %s want %d", fees.GasTipCap, wantTip)
	}
	// feeCap = 60 gwei + 2.4 gwei = 62.4 gwei
	wantCap := int64(62_400_000_000)
	if fees.GasFeeCap.Int64() != wantCap {
		t.Fatalf("fee cap %s want %d", fees.GasFeeCap, wantCap)
	}
}

func TestCalculateAggressiveFeesZeroBase(t *testing.T) {
	fees := CalculateAggressiveFees(nil, big.NewInt(1_000_000_000), 100)
	if fees.GasFeeCap.Cmp(big.NewInt(1_000_000_000)) != 0 {
		t.Fatalf("zero base: %s", fees.GasFeeCap)
	}
}
