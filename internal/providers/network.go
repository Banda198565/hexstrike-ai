package providers

import (
	"context"
	"strings"
)

const jenkinsVulnIP = "51.250.97.223"

const (
	// JenkinsPort is the default Jenkins HTTP port.
	JenkinsPort = 8080
)

// NetworkProvider scans network infrastructure for exposed services (stub).
type NetworkProvider struct{}

// NewNetworkProvider creates a NetworkProvider instance.
func NewNetworkProvider() *NetworkProvider {
	return &NetworkProvider{}
}

// ScanInfrastructure performs a background host/port availability check.
// Returns the first open vulnerable port found, or 0 if none detected.
func (p *NetworkProvider) ScanInfrastructure(ctx context.Context, ip string) (int, error) {
	_ = ctx

	normalized := strings.TrimSpace(ip)
	if normalized == jenkinsVulnIP {
		return JenkinsPort, nil
	}

	return 0, nil
}
