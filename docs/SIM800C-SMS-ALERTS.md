# SIM800C SMS alert channel

Optional SMS-notification channel for HexStrike IR / hot-wallet alerts using
SIM800C GSM module over UART.

## Hardware wiring

| SIM800C pin | To |
|-------------|-----|
| VCC | 4.0 V / 5 V @ 2 A (module can spike 2 A on transmit) |
| GND | Common ground |
| TXD | RX of USB-UART / Pi UART |
| RXD | TX of USB-UART / Pi UART |
| RST (opt.) | GPIO or pull to VCC via 10k |

Power supply must handle ≥2 A pulses; underpowered SIM800C reboots on TX.

## Serial port

| Host | Typical port |
|------|--------------|
| macOS + USB-UART | `/dev/tty.usbserial-*`, `/dev/tty.SLAB_USBtoUART` |
| Linux USB-UART | `/dev/ttyUSB0` |
| Raspberry Pi header | `/dev/serial0` or `/dev/ttyAMA0` (disable serial console first) |

Set `SIM800C_PORT` in `.env` or pass `--port`.

## Install deps

```bash
python3 -m pip install pyserial
```

## Diagnostics

```bash
# list candidate serial ports
./hexstrike sim800c ports

# module identity + firmware + IMEI
./hexstrike sim800c --port /dev/tty.usbserial-A50285BI probe

# network + signal + SIM state (RSSI, dBm, +CREG, +CPIN)
./hexstrike sim800c --port /dev/ttyUSB0 status --pin 1234

# interactive AT shell
./hexstrike sim800c --port /dev/ttyUSB0 shell
AT> AT+CSQ
AT> AT+CREG?
AT> quit
```

Signal quality (`AT+CSQ` → `+CSQ: <rssi>,<ber>`):

| RSSI | dBm | Quality |
|------|-----|---------|
| 2-9 | -109..-95 | poor |
| 10-14 | -93..-85 | fair |
| 15-19 | -83..-75 | good |
| 20-30 | -73..-53 | excellent |
| 31 | ≥-51 | max |
| 99 | — | unknown / no signal |

Network registration (`AT+CREG?`):

| Stat | Meaning |
|------|---------|
| 0 | not searching |
| 1 | registered home |
| 2 | searching |
| 3 | denied |
| 5 | registered roaming |

## Send SMS

```bash
export SIM800C_PORT=/dev/tty.usbserial-A50285BI
export SIM800C_PIN=1234                # if SIM locked
export SIM800C_TO='+70000000000'       # your phone

./hexstrike sim800c sms --to "$SIM800C_TO" --text "hexstrike ping"
```

## IR alert channel

```bash
# manual
./hexstrike sms --to +7... --message "HW_ALERT hot wallet outflow"

# tail unseen entries from artifacts/alerts.log (autonomous_monitor writes these)
./hexstrike sms --to +7... --tail-alerts 5

# dry-run (no hardware)
./hexstrike sms --dry-run --to +7... --message "test"
```

Rate-limits: default 5 SMS/hour (change with `--max-per-hour`). State in
`artifacts/sms_alerts_state.json`.

## Wire into cron / autonomous monitor

```bash
# /etc/cron.d/hexstrike-sms
*/5 * * * * ubuntu cd /opt/hexstrike-ai && \
  ./hexstrike sms --to +7... --tail-alerts 3 >> /var/log/hexstrike/sms.log 2>&1
```

Or systemd timer alongside `hexstrike-fastmcp-ops.timer`.

## Common AT reference

| Command | Purpose |
|---------|---------|
| `AT` | Attention |
| `ATE0` | Disable echo |
| `ATI` | Module id |
| `AT+CGMR` | Firmware |
| `AT+GSN` | IMEI |
| `AT+CPIN?` | PIN state |
| `AT+CPIN="1234"` | Enter PIN |
| `AT+CSQ` | Signal quality |
| `AT+CREG?` | Network registration |
| `AT+COPS?` | Operator |
| `AT+CBC` | Battery |
| `AT+CCLK?` | RTC |
| `AT+CMGF=1` | SMS text mode |
| `AT+CSCS="GSM"` | Charset |
| `AT+CMGS="+7..."` | Start SMS (returns `>` prompt) |
| `<text>\x1a` | SMS body + Ctrl-Z |
| `AT+CMGL="ALL"` | List received SMS |
| `AT+CMGD=1` | Delete SMS at index 1 |

## Security notes

- SIM PIN via `SIM800C_PIN` env; do not commit to `.env` if repo is public
- Rate limit prevents flooding operator during storm of alerts
- Physical access to SIM800C = ability to send SMS from your number — keep the
  device in a locked enclosure alongside the operator Mac
