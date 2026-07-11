package orchestrator

import (
	"context"
	"crypto/ecdsa"
	"math/big"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/ethclient"
	txpkg "github.com/hexstrike-ai/hexstrike/cmd/agent/internal/tx"
)

// SignRescueTx builds and signs an EIP-1559 rescue transfer from bot → funder.
func SignRescueTx(
	ctx context.Context,
	client *ethclient.Client,
	key *ecdsa.PrivateKey,
	chainID *big.Int,
	from, to common.Address,
	value *big.Int,
	fees *txpkg.FeeSuggestion,
) (raw []byte, hash string, err error) {
	nonce, err := client.PendingNonceAt(ctx, from)
	if err != nil {
		return nil, "", err
	}
	txn := types.NewTx(&types.DynamicFeeTx{
		ChainID:   chainID,
		Nonce:     nonce,
		To:        &to,
		Value:     value,
		Gas:       21_000,
		GasTipCap: fees.GasTipCap,
		GasFeeCap: fees.GasFeeCap,
	})
	signed, err := types.SignTx(txn, types.NewLondonSigner(chainID), key)
	if err != nil {
		return nil, "", err
	}
	raw, err = signed.MarshalBinary()
	if err != nil {
		return nil, "", err
	}
	return raw, signed.Hash().Hex(), nil
}

// ResignRescueTx re-signs the same nonce with bumped fees (relay gas escalation).
func ResignRescueTx(
	ctx context.Context,
	client *ethclient.Client,
	key *ecdsa.PrivateKey,
	chainID *big.Int,
	from, to common.Address,
	value *big.Int,
	baseFees *txpkg.FeeSuggestion,
	bumpPct int,
	fees *txpkg.FeeSuggestion,
) ([]byte, error) {
	useFees := fees
	if useFees == nil {
		useFees = txpkg.BumpFeeSuggestion(baseFees, bumpPct)
	}
	raw, _, err := SignRescueTx(ctx, client, key, chainID, from, to, value, useFees)
	return raw, err
}
