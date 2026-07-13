package watch

import (
	"math/big"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds mainnet rescue watch loop parameters (mirrors scripts/sandbox/mainnet.env).
type Config struct {
	RPCURL          string
	PublicRPC       string
	TargetWatch     string
	BotAddress      string
	FunderAddress   string
	AllowedFunders  []string
	BotPrivateKey   string
	ChainID         int64
	ThresholdWei    *big.Int
	MinGasWei       *big.Int
	RescueValueWei  *big.Int
	PollInterval    time.Duration
	DryRun          bool
	Once            bool
	EventsPath      string
	BootstrapPath   string
	ArkhamAPIKey    string
	FailClosedGate  bool
}

// LoadConfigFromEnv reads .env-style variables already exported into the process environment.
func LoadConfigFromEnv() Config {
	allowed := splitCSV(os.Getenv("ALLOWED_FUNDERS"))
	funder := strings.TrimSpace(os.Getenv("FUNDER_ADDRESS"))
	if funder != "" && !containsAddr(allowed, funder) {
		allowed = append(allowed, funder)
	}

	target := strings.TrimSpace(os.Getenv("TARGET_WATCH_ADDRESS"))
	if target == "" {
		target = strings.TrimSpace(os.Getenv("TARGET_ADDRESS"))
	}

	cfg := Config{
		RPCURL:         envOr("RPC_URL", "https://bsc-dataseed.binance.org"),
		PublicRPC:      envOr("RELAY_PUBLIC_RPC", envOr("DIRECT_RPC_URL", envOr("RPC_URL", "https://bsc-dataseed.binance.org"))),
		TargetWatch:    target,
		BotAddress:     strings.TrimSpace(os.Getenv("BOT_ADDRESS")),
		FunderAddress:  funder,
		AllowedFunders: allowed,
		BotPrivateKey:  firstNonEmptyKey(),
		ChainID:        parseInt64Env("CHAIN_ID", 56),
		ThresholdWei:   parseWeiEnv("THRESHOLD_WEI", 500_000_000_000_000_000),
		MinGasWei:      parseWeiEnv("MIN_GAS_WEI", 10_000_000_000_000_000),
		RescueValueWei: parseWeiEnv("RESCUE_VALUE_WEI", 1_000_000_000_000_000),
		PollInterval:   time.Duration(parseInt64Env("POLL_INTERVAL_SEC", 10)) * time.Second,
		DryRun:         parseBoolEnv("DRY_RUN", true),
		EventsPath:     envOr("WATCH_EVENTS_PATH", "artifacts/sandbox/go-watch-events.jsonl"),
		BootstrapPath:  strings.TrimSpace(os.Getenv("ENTITY_BOOTSTRAP_PATH")),
		ArkhamAPIKey:   strings.TrimSpace(os.Getenv("ARKHAM_API_KEY")),
		FailClosedGate: parseBoolEnv("HARDENING_ENABLED", true),
	}
	if cfg.FunderAddress == "" && len(cfg.AllowedFunders) > 0 {
		cfg.FunderAddress = cfg.AllowedFunders[0]
	}
	return cfg
}

func firstNonEmptyKey() string {
	for _, key := range []string{"BOT_PRIVATE_KEY", "AGENT_PRIVATE_KEY"} {
		if v := strings.TrimPrefix(strings.TrimSpace(os.Getenv(key)), "0x"); v != "" {
			return v
		}
	}
	return ""
}

func (c Config) Validate() error {
	if c.TargetWatch == "" {
		return errConfig("TARGET_WATCH_ADDRESS required")
	}
	if c.BotAddress == "" {
		return errConfig("BOT_ADDRESS required")
	}
	if c.FunderAddress == "" {
		return errConfig("FUNDER_ADDRESS or ALLOWED_FUNDERS required")
	}
	if !c.DryRun && c.BotPrivateKey == "" {
		return errConfig("BOT_PRIVATE_KEY required for LIVE mode")
	}
	return nil
}

func envOr(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

func parseInt64Env(key string, def int64) int64 {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	n, err := strconv.ParseInt(v, 10, 64)
	if err != nil {
		return def
	}
	return n
}

func parseWeiEnv(key string, def int64) *big.Int {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return big.NewInt(def)
	}
	n, ok := new(big.Int).SetString(v, 10)
	if !ok {
		return big.NewInt(def)
	}
	return n
}

func parseBoolEnv(key string, def bool) bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv(key)))
	if v == "" {
		return def
	}
	switch v {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return def
	}
}

func splitCSV(raw string) []string {
	out := make([]string, 0)
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}

func containsAddr(list []string, addr string) bool {
	addr = strings.ToLower(strings.TrimSpace(addr))
	for _, a := range list {
		if strings.ToLower(strings.TrimSpace(a)) == addr {
			return true
		}
	}
	return false
}

type configError string

func (e configError) Error() string { return string(e) }

func errConfig(msg string) error { return configError(msg) }
