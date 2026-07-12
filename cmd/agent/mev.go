package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

// RunMEV executes offensive MEV sandbox pipeline (Anvil only).
func (a *Agent) RunMEV() (int, error) {
	a.printBanner("⚔ HexStrike MEV Offensive — Sandbox Only")

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

	steps := []struct {
		name string
		cmd  []string
	}{
		{"mempool scan", []string{"python3", filepath.Join(sandbox, "mev", "mempool_scanner.py")}},
		{"sandwich engine", []string{"python3", filepath.Join(sandbox, "mev", "sandwich_engine.py")}},
	}

	for _, step := range steps {
		a.log(fmt.Sprintf("Running %s...", step.name))
		cmd := exec.Command(step.cmd[0], step.cmd[1:]...)
		cmd.Dir = a.repoRoot
		cmd.Env = append(os.Environ(),
			"MEV_RPC_URL=http://127.0.0.1:8545",
			"MEV_SANDBOX_ONLY=1",
		)
		out, err := cmd.CombinedOutput()
		if a.verbose {
			fmt.Print(string(out))
		}
		if err != nil {
			return 1, fmt.Errorf("%s failed: %w\n%s", step.name, err, string(out))
		}
	}

	a.log("MEV sandbox pipeline complete")
	fmt.Println("  artifacts/sandbox/mev-mempool-scan.json")
	fmt.Println("  artifacts/sandbox/mev-sandwich-result.json")
	return 0, nil
}
