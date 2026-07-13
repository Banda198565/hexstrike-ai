package watch

import (
	"os"
	"testing"
)

func TestLoadConfigFromEnv(t *testing.T) {
	t.Setenv("TARGET_WATCH_ADDRESS", "0x96B23C4680E1a37cE17730e6118D0C9223e72A66")
	t.Setenv("BOT_ADDRESS", "0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846")
	t.Setenv("FUNDER_ADDRESS", "0x060447dC91dfb22A5233731aF67E9E8dafdF24d1")
	t.Setenv("DRY_RUN", "true")
	t.Setenv("CHAIN_ID", "56")

	cfg := LoadConfigFromEnv()
	if err := cfg.Validate(); err != nil {
		t.Fatalf("validate: %v", err)
	}
	if cfg.TargetWatch == "" || cfg.BotAddress == "" {
		t.Fatal("addresses not loaded")
	}
	if !cfg.DryRun {
		t.Fatal("expected dry run")
	}
}

func TestValidateRequiresKeyLive(t *testing.T) {
	cfg := Config{
		TargetWatch:   "0x1",
		BotAddress:    "0x2",
		FunderAddress: "0x3",
		DryRun:        false,
	}
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected error without bot key in live mode")
	}
}

func TestFirstNonEmptyKey(t *testing.T) {
	os.Unsetenv("BOT_PRIVATE_KEY")
	os.Unsetenv("AGENT_PRIVATE_KEY")
	if firstNonEmptyKey() != "" {
		t.Fatal("expected empty")
	}
	t.Setenv("AGENT_PRIVATE_KEY", "abc")
	if firstNonEmptyKey() != "abc" {
		t.Fatalf("got %q", firstNonEmptyKey())
	}
}
