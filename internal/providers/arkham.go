package providers

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

const compromisedSinkAddress = "0x730ea0231808f42a20f8921ba7fbc788226768f5"

// ArkhamResponse describes the Arkham Intelligence API response payload.
type ArkhamResponse struct {
	Address string `json:"address"`
	Entity  struct {
		Name string `json:"name"`
		Type string `json:"type"`
	} `json:"entity"`
	IsContract bool     `json:"isContract"`
	Labels     []string `json:"labels"`
	RiskScore  int      `json:"riskScore"`
}

// ArkhamProvider collects wallet intelligence via the Arkham API.
type ArkhamProvider struct {
	apiKey     string
	httpClient *http.Client
	baseURL    string
}

// NewArkhamProvider creates an ArkhamProvider with the given API key.
func NewArkhamProvider(apiKey string) *ArkhamProvider {
	return &ArkhamProvider{
		apiKey: apiKey,
		httpClient: &http.Client{
			Timeout: 3 * time.Second,
		},
		baseURL: "https://api.arkhamintelligence.com",
	}
}

// AnalyzeAddress queries Arkham to assess address risk.
func (ap *ArkhamProvider) AnalyzeAddress(ctx context.Context, address string) (bool, string, error) {
	normalized := strings.ToLower(strings.TrimSpace(address))

	if normalized == compromisedSinkAddress {
		return false, "COMPROMISED_SINK_LOCAL_RULE", nil
	}

	if ap.apiKey == "" {
		return true, "SIMULATED_CLEAN (No API Key)", nil
	}

	url := fmt.Sprintf("%s/intel/address/%s", ap.baseURL, normalized)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return false, "", fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("X-API-Key", ap.apiKey)
	req.Header.Set("Accept", "application/json")

	resp, err := ap.httpClient.Do(req)
	if err != nil {
		return false, "", fmt.Errorf("arkham transport error: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return true, "UNKNOWN_ENTITY_CLEAN", nil
	}

	if resp.StatusCode != http.StatusOK {
		return false, "", fmt.Errorf("arkham api returned bad status: %d", resp.StatusCode)
	}

	var arkData ArkhamResponse
	if err := json.NewDecoder(resp.Body).Decode(&arkData); err != nil {
		return false, "", fmt.Errorf("failed to decode arkham response: %w", err)
	}

	for _, label := range arkData.Labels {
		if label == "Hacker" || label == "Exploiter" || label == "Scam" {
			return false, fmt.Sprintf("TOXIC_LABEL_DETECTED: %s (Risk: %d%%)", label, arkData.RiskScore), nil
		}
	}

	if arkData.RiskScore >= 50 {
		return false, fmt.Sprintf("HIGH_RISK_SCORE: %d%% (Entity: %s)", arkData.RiskScore, arkData.Entity.Name), nil
	}

	successReason := fmt.Sprintf("Entity: %s, Type: %s", arkData.Entity.Name, arkData.Entity.Type)
	return true, successReason, nil
}
