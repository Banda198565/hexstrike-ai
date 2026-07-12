package mev

import (
	"encoding/hex"
	"math/big"
	"strings"
)

// PancakeSwap V2 / Uniswap V2 router selectors (offensive mempool classification).
var (
	selSwapExactETHForTokens         = mustDecode("7ff36ab5") // swapExactETHForTokens(uint256,address[],address,uint256)
	selSwapExactTokensForETH         = mustDecode("18cbafe5") // swapExactTokensForETH(uint256,uint256,address[],address,uint256)
	selSwapExactETHForTokensSupportingFee = mustDecode("b6f9de95")
)

func mustDecode(h string) []byte {
	b, err := hex.DecodeString(h)
	if err != nil {
		panic(err)
	}
	return b
}

// ClassifySwap inspects calldata for known DEX swap entrypoints.
func ClassifySwap(data []byte) (SwapKind, *big.Int) {
	if len(data) < 4 {
		return SwapUnknown, nil
	}
	sel := data[:4]
	switch {
	case bytesEqual(sel, selSwapExactETHForTokens), bytesEqual(sel, selSwapExactETHForTokensSupportingFee):
		// amountOutMin is first arg after selector (uint256)
		if len(data) >= 36 {
			return SwapExactETHForTokens, new(big.Int).SetBytes(data[4:36])
		}
		return SwapExactETHForTokens, big.NewInt(0)
	case bytesEqual(sel, selSwapExactTokensForETH):
		if len(data) >= 36 {
			return SwapExactTokensForETH, new(big.Int).SetBytes(data[4:36])
		}
		return SwapExactTokensForETH, big.NewInt(0)
	default:
		return SwapUnknown, nil
	}
}

// IsSandwichCandidate returns true when tx looks like a public-mempool ETH→token swap.
func IsSandwichCandidate(valueWei *big.Int, data []byte) bool {
	if valueWei == nil || valueWei.Sign() <= 0 {
		return false
	}
	kind, _ := ClassifySwap(data)
	return kind == SwapExactETHForTokens
}

// ParsePendingSwap builds a structured swap from raw RPC fields.
func ParsePendingSwap(hash, from, to, valueHex, gasPriceHex string, dataHex string) (*PendingSwap, error) {
	value := hexToBig(valueHex)
	gasPrice := hexToBig(gasPriceHex)
	data, err := decodeHexData(dataHex)
	if err != nil {
		return nil, err
	}
	kind, minOut := ClassifySwap(data)
	return &PendingSwap{
		Hash:     strings.ToLower(hash),
		From:     strings.ToLower(from),
		To:       strings.ToLower(to),
		ValueWei: value,
		GasPrice: gasPrice,
		Data:     data,
		Kind:     kind,
		AmountIn: new(big.Int).Set(value),
		MinOut:   minOut,
	}, nil
}

func bytesEqual(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func hexToBig(h string) *big.Int {
	h = strings.TrimPrefix(strings.TrimSpace(h), "0x")
	if h == "" {
		return big.NewInt(0)
	}
	v, ok := new(big.Int).SetString(h, 16)
	if !ok {
		return big.NewInt(0)
	}
	return v
}

func decodeHexData(h string) ([]byte, error) {
	h = strings.TrimPrefix(strings.TrimSpace(h), "0x")
	if h == "" {
		return nil, nil
	}
	return hex.DecodeString(h)
}
