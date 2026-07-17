# VPS Ideal Ready (lab / defense)

| Field | Value |
|-------|--------|
| Host | `root@78.27.235.70` (E-12 / Mirohost) |
| Repo | `https://github.com/Banda198565/hexstrike-ai` → `/root/hexstrike-ai` |
| SSH | **key-only** (`PasswordAuthentication no`) |
| Keys | `bogdan-pentest` (Mac `~/.ssh/mirohost_pentest`), cloud agent, `hexstrike-01@cursor-20260714` |
| Secrets | `/root/hexstrike-ai/.env` + `/root/Desktop/hexstrike-ALL-KEYS-APIs.txt` |
| Status JSON | `/root/hexstrike-ai/artifacts/vps-ideal-status.json` |
| Production GLOBAL GO | **NO-GO** (unchanged) |

## Mac login

```bash
ssh -i ~/.ssh/mirohost_pentest -o IdentitiesOnly=yes root@78.27.235.70
```

## Operator notes

- Remote was previously `0x4m4/hexstrike-ai`; remapped to **Banda198565**.
- Root password was **not** rotated in this pass.
- Cursor cloud egress IPs allowlisted (ufw + iptables); IPs rotate — refresh via `scripts/vps-allow-cursor-cloud-ssh.sh` / `scripts/vps-open-for-cloud-agent.sh`.
