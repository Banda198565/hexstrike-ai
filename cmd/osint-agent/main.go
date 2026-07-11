package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"hexstrike-osint-agent/internal/cache"
	"hexstrike-osint-agent/internal/core"
	"hexstrike-osint-agent/internal/providers"
)

const (
	walletTarget = "0x730ea0231808f42a20f8921ba7fbc788226768f5"
	serverTarget = "51.250.97.223"
)

func main() {
	memCache := cache.NewMemoryCache()
	engine := core.NewOsintEngine(
		memCache,
		providers.NewArkhamProvider(),
		providers.NewNetworkProvider(),
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go engine.MonitorTarget(ctx, walletTarget, "wallet", 15*time.Second)
	go engine.MonitorTarget(ctx, serverTarget, "ip", 30*time.Second)

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	<-sigCh

	cancel()
	time.Sleep(100 * time.Millisecond)

	memCache.Destroy()
	fmt.Println("[!] OSINT-Agent stopped safely. Cache destroyed.")
}
