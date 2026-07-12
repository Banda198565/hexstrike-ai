package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"hexstrike-osint-agent/internal/cache"
	"hexstrike-osint-agent/internal/core"
	"hexstrike-osint-agent/internal/providers"
)

const (
	defaultWalletTarget = "0x730ea0231808f42a20f8921ba7fbc788226768f5"
	defaultServerTarget = "51.250.97.223"
)

func main() {
	apiKey := os.Getenv("ARKHAM_API_KEY")
	if apiKey == "" {
		log.Println("[ВНИМАНИЕ] Переменная ARKHAM_API_KEY не задана. Модуль Arkham запущен в режиме симуляции.")
	}

	shodanKey := os.Getenv("SHODAN_API_KEY")
	if shodanKey == "" {
		log.Println("[ВНИМАНИЕ] Переменная SHODAN_API_KEY не задана. Модуль Network запущен в режиме симуляции.")
	}

	getblockKey := os.Getenv("GETBLOCK_API_KEY")
	if getblockKey == "" {
		log.Println("[ВНИМАНИЕ] Переменная GETBLOCK_API_KEY не задана. Модуль GetBlock запущен в режиме симуляции.")
	}

	walletTarget := envOrDefault("WALLET_TARGET", defaultWalletTarget)
	serverTarget := envOrDefault("IP_TARGET", defaultServerTarget)
	walletInterval := envDurationOrDefault("WALLET_INTERVAL", 15*time.Second)
	serverInterval := envDurationOrDefault("IP_INTERVAL", 30*time.Second)

	log.Printf("[OSINT-AGENT] Monitoring wallet=%s (%s), ip=%s (%s)", walletTarget, walletInterval, serverTarget, serverInterval)

	memCache := cache.NewMemoryCache()
	engine := core.NewOsintEngine(
		memCache,
		providers.NewArkhamProvider(apiKey),
		providers.NewGetBlockProvider(getblockKey),
		providers.NewNetworkProvider(shodanKey),
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go engine.MonitorTarget(ctx, walletTarget, "wallet", walletInterval)
	go engine.MonitorTarget(ctx, serverTarget, "ip", serverInterval)

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	<-sigCh

	cancel()
	time.Sleep(100 * time.Millisecond)

	memCache.Destroy()
	fmt.Println("[!] OSINT-Agent stopped safely. Cache destroyed.")
}

func envOrDefault(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func envDurationOrDefault(key string, fallback time.Duration) time.Duration {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}

	parsed, err := time.ParseDuration(value)
	if err != nil {
		log.Printf("[ВНИМАНИЕ] Некорректное значение %s=%q, используется %s", key, value, fallback)
		return fallback
	}

	return parsed
}
