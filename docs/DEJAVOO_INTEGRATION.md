# Dejavoo Payment Terminal Integration (SPIn)

Status: **Phase 1 scaffolding done (optional + graceful). Live card transactions
pending the Dejavoo SPIn SDK + Auth Key.**

The terminal on hand is a **Dejavoo Z8** (Castles Technology OEM). It enumerates
as a USB CDC serial device: **VID `0x0CA6` / PID `0xA050`**, "EFT-POS Terminal",
on **COM5** of the POS laptop.

## Design principle: optional and graceful

Nothing changes when the terminal is absent. The integration is **off by default**
(`PAYMENT_TERMINAL_ENABLED=false`). When disabled or no terminal is detected,
`run_sale()` raises `TerminalNotConfigured` and the UI falls back to today's manual
card entry (`payment_method=CARD`, `card_last4` typed by the cashier). The live
transaction call is a deliberate stub, so no card can be run before the protocol
is implemented and tested.

## What's built (Phase 1)

| Piece | Path | Notes |
|---|---|---|
| Terminal service | `backend/app/services/payment_terminal.py` | `terminal_status()` detect (serial by VID/PID, or network reachability); `run_sale()` stub that never charges yet |
| API | `backend/app/api/v1/endpoints/payments.py` | `GET /payments/terminal/status`; `POST /payments/terminal/sale` (503 until SPIn wired) |
| Config | `backend/app/core/config.py` | `PAYMENT_TERMINAL_*` settings (see below) |
| Probe tool | `scripts/payments/dejavoo_probe.py` | POS-side, READ-ONLY detection (`--monitor`, `--json`). Never writes to the terminal |
| Receipt preview | `backend/app/api/v1/endpoints/receipts.py` | `GET /receipts/preview/sample`, `GET /receipts/{token}/preview` (plaintext, no printer) |
| Receipt customization | `backend/app/services/receipt_printer.py` | `RECEIPT_STORE_NAME`, `RECEIPT_FOOTER`; `render_receipt_text()` preview |

### Settings (`.env`)
```
PAYMENT_TERMINAL_ENABLED=false        # true to turn the integration on
PAYMENT_TERMINAL_TRANSPORT=serial     # serial | network
PAYMENT_TERMINAL_PORT=                 # e.g. COM5; blank = auto-detect by VID/PID
PAYMENT_TERMINAL_HOST=                 # SPIn host when transport=network
PAYMENT_TERMINAL_NET_PORT=8080
PAYMENT_TERMINAL_AUTH_KEY=             # SPIn Auth Key / Register ID -- secret, never commit
RECEIPT_STORE_NAME=Main Street Fireworks
RECEIPT_FOOTER=Thank you!\nAll fireworks sales final
```

## Deployment note (important)

The FIMS backend runs in Docker on **KianPotPi**, which **cannot see COM5 on the
laptop**. So for production there are two real options:

1. **Network SPIn** — put the Z8 on the LAN/WiFi and set `PAYMENT_TERMINAL_TRANSPORT=network`
   + `PAYMENT_TERMINAL_HOST`. KianPotPi drives it directly. Cleanest fit for the
   centralized backend.
2. **Local POS agent** — a tiny helper on the POS station that owns COM5 and relays
   to the backend. More moving parts; only needed if the terminal must stay USB.

For now (testing phase) everything runs on the laptop against COM5 via the probe
tool and the transport-agnostic service.

## What to request from the processor / Dejavoo (to finish Phase 2)

Send the SPIn API request form (dejavoosystems.com) or ask whoever provisioned the
terminal for:

1. **SPIn SDK + protocol docs** (the XML/JSON dev tool + message spec).
2. **Auth Key / Register ID** bound to this terminal's merchant account (required
   for the terminal to accept integrated transactions). Keep it in `.env`
   (`PAYMENT_TERMINAL_AUTH_KEY`) — never in git.
3. **Transport confirmation** — confirm the Z8 is licensed for SPIn over USB
   serial vs. requiring IP/network, and the port/baud or HTTP endpoint.
4. **Card-slip customization** — how header/footer lines on the *terminal's own
   printed slip* are set (SPIn request fields vs. terminal config menu), so we can
   match the FIMS receipt branding.

## Phase 2 (after SDK + Auth Key)

- Implement `run_sale()`: build the SPIn sale/auth request (amount, ref, auth key),
  send over the chosen transport, parse approval -> `{approved, card_last4,
  card_type, auth_code, reference}`.
- Wire checkout: if `terminal/status` is available, offer "Charge on terminal";
  on approval auto-fill `payment_method=CARD` + `card_last4` and post the sale as
  today. On decline/timeout, fall back to manual.
- Customize the Dejavoo card slip header/footer to match the FIMS receipt.

## Testing now

```bash
# POS laptop: confirm detection (safe, read-only)
python scripts/payments/dejavoo_probe.py
python scripts/payments/dejavoo_probe.py --monitor   # plug/unplug live

# Receipt layout iteration (no printer needed), against the backend:
curl http://100.73.208.99/api/v1/receipts/preview/sample
curl "http://100.73.208.99/api/v1/receipts/preview/sample?copy_type=merchant"

# Terminal status via API (reports available only where a terminal is reachable):
curl http://100.73.208.99/api/v1/payments/terminal/status
```
