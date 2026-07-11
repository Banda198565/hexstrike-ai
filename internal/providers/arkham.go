package providers

import (
	"context"
	"strings"
)

const compromisedSinkAddress = "0x730ea0231808f42a20f8921ba7fbc788226768f5"

// ArkhamProvider collects wallet intelligence via the Arkham API (stub).
type ArkhamProvider struct{}

// NewArkhamProvider creates an ArkhamProvider instance.
func NewArkhamProvider() *ArkhamProvider {
	return &ArkhamProvider{}
}

// AnalyzeAddress checks whether a wallet address is safe.
// Returns isSafe, reason/tags, and any error from the upstream API.
func (p *ArkhamProvider) AnalyzeAddress(ctx context.Context, address string) (bool, string, error) {
	_ = ctx

	normalized := strings.ToLower(strings.TrimSpace(address))
	if normalized == compromisedSinkAddress {
		return false, "COMPROMISED_SINK", nil
	}

	return true, "clean", nil
}
