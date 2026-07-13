package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/hexstrike-ai/hexstrike/cmd/agent/internal/watch"
)

func runWatch(once bool) (int, error) {
	BootstrapMainnet()
	cfg := watch.LoadConfigFromEnv()
	cfg.Once = once
	if err := cfg.Validate(); err != nil {
		return 1, err
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	if err := watch.Run(ctx, cfg); err != nil && err != context.Canceled {
		return 1, err
	}
	return 0, nil
}

func runWatchDryRun() (int, error) {
	_ = os.Setenv("DRY_RUN", "true")
	return runWatch(true)
}

func watchUsageHint() {
	fmt.Println(`  watch [--once]   Mainnet rescue watch loop (Go engine: EIP-1559 + Puissant + dedup)
  watch-dry-run    Single poll cycle with DRY_RUN=true`)
}
