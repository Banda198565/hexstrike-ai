package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

func mevEnv(rpc string, chains string) []string {
	return append(os.Environ(),
		"MEV_RPC_URL="+rpc,
		"MEV_SANDBOX_ONLY=1",
		"MEV_ALLOWED_CHAINS="+chains,
	)
}

// RunMEV executes full offensive MEV stack on Anvil (sandwich → JIT → backrun).
func (a *Agent) RunMEV() (int, error) {
	a.printBanner("⚔ HexStrike MEV Offensive — Full Stack (Anvil)")

	prereqs := a.verifyPrerequisites()
	if !a.allPrereqsOK(prereqs) {
		return 1, fmt.Errorf("missing prerequisites")
	}

	sandbox := filepath.Join(a.repoRoot, "scripts", "sandbox")
	if err := a.setupEnvironment(); err != nil {
		return 1, err
	}

	start := exec.Command("bash", filepath.Join(sandbox, "start-anvil.sh"))
	start.Dir = a.repoRoot
	if out, err := start.CombinedOutput(); err != nil {
		return 1, fmt.Errorf("start-anvil: %w\n%s", err, string(out))
	}

	rpc := "http://127.0.0.1:8545"
	steps := []struct {
		name string
		script string
	}{
		{"mempool scan", "mempool_scanner.py"},
		{"sandwich", "sandwich_engine.py"},
		{"JIT liquidity", "jit_engine.py"},
		{"backrun arb", "backrun_engine.py"},
	}

	for _, step := range steps {
		a.log("Running " + step.name + "...")
		cmd := exec.Command("python3", filepath.Join(sandbox, "mev", step.script))
		cmd.Dir = a.repoRoot
		cmd.Env = append(mevEnv(rpc, "31337"),
			"JIT_FORCE_DEMO=1", // battle/demo path when classifier would skip
		)
		out, err := cmd.CombinedOutput()
		if a.verbose {
			fmt.Print(string(out))
		}
		if err != nil {
			return 1, fmt.Errorf("%s failed: %w\n%s", step.name, err, string(out))
		}
	}

	a.log("MEV full stack complete (sandwich + JIT + backrun)")
	fmt.Println("  artifacts/sandbox/mev-mempool-scan.json")
	fmt.Println("  artifacts/sandbox/mev-sandwich-result.json")
	fmt.Println("  artifacts/sandbox/mev-jit-result.json")
	fmt.Println("  artifacts/sandbox/mev-backrun-result.json")
	return 0, nil
}

// RunMEVFork runs BSC fork offensive simulation (real pools, no tx submit).
func (a *Agent) RunMEVFork() (int, error) {
	a.printBanner("⚔ HexStrike MEV Offensive — BSC Fork Sim")

	prereqs := a.verifyPrerequisites()
	if !a.allPrereqsOK(prereqs) {
		return 1, fmt.Errorf("missing prerequisites")
	}

	sandbox := filepath.Join(a.repoRoot, "scripts", "sandbox")
	forkSetup := exec.Command("bash", filepath.Join(sandbox, "setup-bsc-fork.sh"))
	forkSetup.Dir = a.repoRoot
	if out, err := forkSetup.CombinedOutput(); err != nil {
		return 1, fmt.Errorf("bsc fork setup: %w\n%s", err, string(out))
	}

	rpc := "http://127.0.0.1:8545"
	cmd := exec.Command("python3", filepath.Join(sandbox, "mev", "fork_offensive.py"))
	cmd.Dir = a.repoRoot
	cmd.Env = mevEnv(rpc, "56")
	out, err := cmd.CombinedOutput()
	if a.verbose {
		fmt.Print(string(out))
	}
	if err != nil {
		return 1, fmt.Errorf("fork offensive: %w\n%s", err, string(out))
	}

	a.log("BSC fork MEV sim complete")
	fmt.Println("  artifacts/sandbox/mev-bsc-fork-result.json")
	return 0, nil
}
