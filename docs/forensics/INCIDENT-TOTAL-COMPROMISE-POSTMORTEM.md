# ОТЧЁТ ОБ ИНЦИДЕНТЕ: ПОЛНАЯ КОМПРОМЕТАЦИЯ ИНФРАСТРУКТУРЫ

**Статус:** CRITICAL BREACH POST-MORTEM (worst-case planning document)  
**Идентификатор дела:** HEX-2026-07-12-TOTAL-COMPROMISE  
**Классификация:** APT / полный захват периметра (сценарий)  
**Режим HexStrike:** read-only forensics + defensive IR — без offensive exploit instructions  

---

## 0. Факт vs сценарий (важно)

| Параметр | **Факт (pentest 2026-07-08)** | **Worst-case (этот документ)** |
|----------|-------------------------------|--------------------------------|
| Jenkins RCE | ✅ доказан | ✅ предполагается |
| Open BSC RPC | ✅ доказан | ✅ предполагается |
| Private key hot wallet | ❌ **не получен** | ⚠️ **предполагается скомпрометирован** |
| Drain выполнен | ❌ **BLOCKED** | ⚠️ **возможен** |
| Payroll/OTC verdict | ✅ CLOSED (MEDIUM-HIGH) | N/A — смена контура выплат |

> Документ описывает **план реагирования**, если worst-case materialized.  
> Текущий live-статус: **инфраструктура exposed, ключи hot wallet не подтверждены как утечшие**.

---

## 1. Scope активов

| Актив | Значение |
|-------|----------|
| Hot wallet (TARGET) | `0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA` |
| Authority (EIP-7702) | `0x730ea0231808f42a20f8921ba7fbc788226768f5` |
| Bridge sink (Rhino.fi) | `0xb80a582fa430645a043bb4f6135321ee01005fef` |
| Infra-correlated wallet | `0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a` |
| Jenkins | `51.250.97.223:8080` (Yandex Cloud) |
| BSC Geth RPC | `51.222.42.220:8545` (OVH) |
| Operator PoC (out of scope) | `0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846` |

**Behavioral class (forensics):** Payment processor / Payroll disbursement rail — см. `artifacts/forensics/payroll-otc-verdict.md`

---

## 2. Attack Kill Chain (worst-case)

```
[Шаг 1: Recon]        Публичный Jenkins 51.250.97.223:8080 (CVE-2024-23897 class)
         │
         ▼
[Шаг 2: Exploit]      File read / Groovy RCE → .env, CI secrets, deploy vars
         │
         ▼
[Шаг 3: Lateral]      Pivot → internal 10.129.0.0/24, Gym API, cred hints
         │
         ▼
[Шаг 4: RPC abuse]    Open Geth 51.222.42.220:8545 → mempool intel, state reads
         │
         ▼
[Шаг 5: Signing]      Compromise isolated Signing Service → PRIVATE KEY exfil
         │
         ▼
[Шаг 6: Impact]       Unauthorized signed txs from 0x4943... → bridge/CEX exit
```

**Факт pentest:** цепочка остановлена на **Шаг 5** (ключ не получен).

---

## 3. Compromised Assets (worst-case matrix)

| Компонент | Worst-case статус | Следствие |
|-----------|-------------------|-----------|
| Private key `0x4943...` | **COMPROMISED** | Полная криптографическая власть над hot wallet |
| Jenkins credentials | **COMPROMISED** | Утечка repo tokens, deploy secrets, `.env` |
| Geth / RPC node | **FULL CONTROL** | Mempool manipulation, DoS, false balance reads |
| Signing service | **COMPROMISED** | Bot key exfil; txs вне легитимного софта |
| GitHub/GitLab tokens | **ASSUME BREACH** | Rotate all PATs tied to CI |
| Binance funding trail | **INFO LEAK** | KYC entity link exposed (LEA path) |

---

## 4. Incident Response Protocol

### 4.1 Containment — немедленно (0–4 ч)

| # | Действие | Mac (оператор) | Server / Cloud |
|---|----------|----------------|----------------|
| 1 | Isolate Jenkins host | — | Yandex console: **stop** VM `51.250.97.223` |
| 2 | Isolate Geth RPC host | — | OVH panel: **stop** or firewall **8545** |
| 3 | Revoke CI secrets | Rotate GitHub/GitLab PATs | `jenkins` credentials revoke |
| 4 | Revoke cloud API keys | — | Yandex/OVH IAM key rotation |
| 5 | Block outbound from signing svc | — | Network ACL deny egress (if identified) |
| 6 | Preserve evidence | Copy artifacts to air-gapped | Snapshot disks before power-off |

**HexStrike (read-only):** продолжить `autonomous_monitor.py` только до containment, затем **stop**.

### 4.2 Asset Rescue — легитимный владелец (4–24 ч)

> Только если **подтверждена** компрометация ключа и остаток ликвидности на hot wallet.

| Mac | Server |
|-----|--------|
| Создать **новый** cold wallet на чистом air-gapped/host device | **Не** использовать скомпрометированные hosts |
| Использовать **авторизованный** rescue pipeline (`dummy_bot.py` / hardened bot) с **новым** ключом funder | RPC только с **чистого** endpoint (не 51.222.42.220) |
| `gas_bump` ≥ +50% tip для competitive rescue | Monitor mempool с clean RPC |

**Запрещено:** rescue с ключами, хранившимися на Jenkins/Geth/signing host.

**Факт:** в pentest 2026-07-08 rescue **не требовался** — drain blocked.

### 4.3 Eradication & Recovery (1–7 дней)

1. **Burn address:** `0x4943...` **навсегда** исключить из ops; считать ключ публично скомпрометированным.
2. **Greenfield deployment:**
   - New VPS, clean OS images
   - Jenkins **only VPN**, no WAN `:8080`
   - HashiCorp Vault / cloud KMS — signing via API, raw key never on CI
   - RPC `:8545` bind `127.0.0.1` + auth proxy
3. **New hot wallet:** новый адрес + новый signing service + payroll rail migration.
4. **Forensics retention:** `artifacts/forensics/*`, pentest logs, chain of custody.

### 4.4 Recovery verification

| Check | Pass criteria |
|-------|---------------|
| Old hot wallet disabled | No new payroll txs from `0x4943...` |
| New signing path | HSM/Vault audit log only |
| RPC | No public JSON-RPC |
| Jenkins | CVE patched, auth + VPN |
| HexStrike monitor | Watches **new** addresses only |

---

## 5. Timeline (reference)

| UTC | Event | Source |
|-----|-------|--------|
| 2026-07-08 | Pentest: Jenkins RCE proven | PENTEST_FULL_REPORT |
| 2026-07-08 | Drain BLOCKED — no private key | PENTEST_FULL_REPORT |
| 2026-07-10 | Recon master: 5-wallet BSC set | TARGETS-REPORT |
| 2026-07-12 | Forensics 7/7 + hot-wallet dossier | session-report-20260712 |
| 2026-07-12 | Payroll/OTC case CLOSED | payroll-otc-verdict.md |
| 2026-07-12 | **This document** — worst-case IR plan | HEX-2026-07-12-TOTAL-COMPROMISE |

---

## 6. Evidence index

| Artifact | Path |
|----------|------|
| Hot wallet dossier | `artifacts/forensics/hot-wallet-dossier.md` |
| Payroll/OTC verdict | `artifacts/forensics/payroll-otc-verdict.md` |
| Entity resolution | `artifacts/entity-id.json` |
| Infra trace | `artifacts/infra-trace-final.json` |
| Jenkins CVE | `artifacts/jenkins-cve-report.json` |
| Exchange LEA pack | `artifacts/exchange-forensics/` |
| Pentest (authorized) | `docs/uploads/PENTEST_FULL_REPORT` (operator copy) |

---

## 7. Заключение для инцидент-лога

> **Worst-case вердикт:** При подтверждённой полной компрометации инфраструктура **непригодна** к дальнейшей эксплуатации без greenfield rebuild. Криптографические ключи hot wallet считаются **скомпрометированными**. Требуется переход на **резервный контур выплат** (новый адрес + Vault signing).
>
> **Actual-state вердикт (2026-07-12):** Perimeter **exposed**, payroll rail **identified**, private key **not confirmed leaked**, drain **not executed**. Рекомендуется **превентивный** containment до materialization worst-case.

---

## 8. Команды HexStrike (defensive)

### Mac
```bash
cd /Volumes/Eva/mufasaai-storage/hexstrike-ai
cat artifacts/forensics/payroll-otc-verdict.md
cat docs/forensics/INCIDENT-TOTAL-COMPROMISE-POSTMORTEM.md
bash scripts/run-hot-wallet-ops.sh
```

### Server
```bash
cd /opt/hexstrike-ai
cat docs/forensics/INCIDENT-TOTAL-COMPROMISE-POSTMORTEM.md
cat artifacts/forensics/payroll-otc-verdict.md
systemctl stop hexstrike-orchestrator   # при реальном containment
```

---

*HexStrike defensive IR — read-only forensics, remediation guidance only.*
