# Bulk Auto Bot v7 — Aggressive Faucet Competition Automation

Bot automation Python untuk kompetisi faucet-equity Bulk Trade. Bot ini **bukan LLM agent** dan tidak memakai news screening real-time. Fokusnya adalah scan pair, cari confluence teknikal, entry agresif, lalu exit cepat agar PnL menjadi realized.

Default bot adalah **DRY RUN**. Tidak ada order live sampai kamu mengubah `.env` menjadi:

```env
ENABLE_LIVE_TRADING=true
DRY_RUN=false
```

Gunakan hanya untuk faucet/paper competition sesuai aturan platform. Jangan hubungkan ke dana asli.

---

## Fitur utama

- Satu mode: **AGGRESSIVE**.
- Scan pair Bulk via `exchangeInfo` jika tersedia.
- Jika `exchangeInfo=[]`, bot melakukan **auto-discovery fallback** dengan mencoba kandidat pair umum seperti `BTC-USD`, `ETH-USD`, `SOL-USD`, dan lainnya.
- Pair valid disimpan ke `data/symbols_cache.json`.
- Tetap bisa manual override via `.env` atau CLI.
- Strategi teknikal:
  - Supply & Demand sederhana
  - RSI
  - Candlestick pattern
  - Momentum EMA
  - Spread/liquidity filter
- Dry-run virtual position tracking.
- Entry/exit otomatis.
- Anti-duplicate posisi per symbol.
- Signal reversal close.
- SQLite logging.
- Telegram cockpit dengan tampilan lebih rapi.
- Debug scores per pair.

---

## Struktur folder

```text
bulk_auto_bot/
├─ bulk_auto_bot/
│  ├─ main.py
│  ├─ settings.py
│  ├─ discovery.py
│  ├─ bulk_client_adapter.py
│  ├─ market.py
│  ├─ strategy.py
│  ├─ execution.py
│  ├─ db.py
│  ├─ telegram.py
│  └─ logging_setup.py
├─ .env.example
├─ config.yaml
├─ requirements.txt
├─ run_bot.sh
├─ run_bot.ps1
└─ README.md
```

---

## Instalasi Windows PowerShell

```powershell
cd C:\Users\maula\Downloads\bulk_auto_bot_v7
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Test sekali:

```powershell
python -m bulk_auto_bot.main --once --debug-scores
```

Jalankan loop:

```powershell
python -m bulk_auto_bot.main --debug-scores
```

---

## Instalasi Linux / Mac

```bash
cd ~/Downloads/bulk_auto_bot_v7
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Test:

```bash
python -m bulk_auto_bot.main --once --debug-scores
```

---

## Symbol discovery

Bulk environment kamu sebelumnya mengembalikan:

```text
exchangeInfo = []
```

Karena itu v7 punya fallback otomatis.

### Opsi 1 — Auto-discovery kandidat pair

Kosongkan `MANUAL_SYMBOLS`:

```env
MANUAL_SYMBOLS=
AUTO_DISCOVER_SYMBOLS=true
```

Lalu jalankan:

```powershell
python -m bulk_auto_bot.main --discover-symbols --debug-scores
```

Bot akan mencoba kandidat pair umum, memvalidasi `ticker` + `l2book`, lalu menyimpan pair valid ke:

```text
data/symbols_cache.json
```

Run berikutnya akan memakai cache itu.

### Opsi 2 — Manual symbols

Kalau kamu mau cepat dan stabil:

```env
MANUAL_SYMBOLS=BTC-USD,ETH-USD,SOL-USD
```

Atau override dari CLI:

```powershell
python -m bulk_auto_bot.main --once --symbols BTC-USD,ETH-USD --debug-scores
```

### Opsi 3 — Candidate universe custom

Kalau kamu punya daftar market Bulk dari Discord/Twitter/UI, masukkan ke `.env`:

```env
DISCOVERY_CANDIDATES=BTC-USD,ETH-USD,SOL-USD,HYPE-USD,DOGE-USD,XRP-USD
```

Lalu:

```powershell
python -m bulk_auto_bot.main --discover-symbols --debug-scores
```

---

## Telegram setup

### 1. Buat bot

1. Buka Telegram.
2. Chat `@BotFather`.
3. Kirim `/newbot`.
4. Ikuti instruksi.
5. Copy token bot.

### 2. Ambil chat ID

Cara termudah:

1. Kirim pesan apa pun ke bot kamu.
2. Buka di browser:

```text
https://api.telegram.org/bot<TOKEN_KAMU>/getUpdates
```

3. Cari bagian `chat` lalu ambil `id`.

### 3. Isi `.env`

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=isi_token_botfather
TELEGRAM_CHAT_ID=isi_chat_id_kamu
TELEGRAM_PRETTY=true
TELEGRAM_SCAN_SUMMARY=false
TELEGRAM_SUMMARY_EVERY_SCANS=20
```

### 4. Test Telegram

```powershell
python -m bulk_auto_bot.main --telegram-test
```

Kalau berhasil, Telegram akan menampilkan card:

- Bot started
- Demo entry
- Demo close

---

## Tampilan Telegram

Alert entry akan terlihat seperti:

```text
⚡ NEW ENTRY
━━━━━━━━━━━━━━━━━━━━
Pair: ETH-USD
Side: 🟢 LONG
Score: 0.72 ███████░░░
Entry ref: 2225.12
Size mode: AGGRESSIVE
Reason: demand zone + RSI recovery + strong bullish close
```

Alert close:

```text
🟢 POSITION CLOSED
━━━━━━━━━━━━━━━━━━━━
Pair: ETH-USD
Closed side: BUY
Exit ref: 2229.42
PnL approx: +0.123456
Reason: take_profit
```

Optional scan summary:

```env
TELEGRAM_SCAN_SUMMARY=true
TELEGRAM_SUMMARY_EVERY_SCANS=10
```

Jangan terlalu sering mengaktifkan summary kalau banyak pair, supaya Telegram tidak spam.

---

## Setting agresif testing

Untuk dry-run cepat:

```env
MIN_SIGNAL_SCORE=0.45
TAKE_PROFIT_PCT=0.0015
STOP_LOSS_PCT=0.0010
TIMEOUT_SECONDS=60
MAX_SPREAD_PCT=0.005
MIN_CANDLES=30
ALLOW_PYRAMIDING_SAME_SYMBOL=false
CLOSE_ON_SIGNAL_REVERSAL=true
```

Untuk live faucet awal, gunakan sedikit lebih selektif:

```env
MIN_SIGNAL_SCORE=0.50
TAKE_PROFIT_PCT=0.0020
STOP_LOSS_PCT=0.0015
TIMEOUT_SECONDS=90
```

---

## Menjalankan bot

Run sekali:

```powershell
python -m bulk_auto_bot.main --once --debug-scores
```

Run loop:

```powershell
python -m bulk_auto_bot.main --debug-scores
```

Run dengan pair tertentu:

```powershell
python -m bulk_auto_bot.main --symbols BTC-USD,ETH-USD --debug-scores
```

Discover symbols:

```powershell
python -m bulk_auto_bot.main --discover-symbols --debug-scores
```

Telegram test:

```powershell
python -m bulk_auto_bot.main --telegram-test
```

---

## Live faucet mode

Pastikan kamu sudah test dry-run dan Telegram dulu.

Isi `.env`:

```env
BULK_PRIVATE_KEY=private_key_agent_wallet_kamu
ENABLE_LIVE_TRADING=true
DRY_RUN=false
```

Lalu jalankan:

```powershell
python -m bulk_auto_bot.main --debug-scores
```

Bot akan memakai `bulk-client` SDK untuk order. Kalau method SDK berubah atau order ditolak, bot akan log error. Jangan gunakan untuk dana asli.

---

## Troubleshooting

### `exchangeInfo returned empty list`

Normal di environment Bulk early. Gunakan:

```powershell
python -m bulk_auto_bot.main --discover-symbols --debug-scores
```

Atau isi:

```env
MANUAL_SYMBOLS=BTC-USD,ETH-USD
```

### `no signal this scan`

Artinya bot berjalan tapi tidak ada skor yang tembus threshold. Untuk testing:

```env
MIN_SIGNAL_SCORE=0.45
MAX_SPREAD_PCT=0.005
```

Lalu jalankan dengan:

```powershell
python -m bulk_auto_bot.main --once --debug-scores
```

### `scan fail BTC-USD: get_klines failed ... Read timed out`

API candle timeout. Bot akan skip symbol itu dan lanjut pair lain. Coba run lagi atau kurangi jumlah pair.

### Telegram tidak terkirim

Cek:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Lalu:

```powershell
python -m bulk_auto_bot.main --telegram-test
```

### Bot membuka posisi berulang di symbol sama

Pastikan:

```env
ALLOW_PYRAMIDING_SAME_SYMBOL=false
```

### Signal reversal tidak menutup posisi

Pastikan:

```env
CLOSE_ON_SIGNAL_REVERSAL=true
```

---

## Checklist sebelum live faucet

```text
[ ] `python -m bulk_auto_bot.main --once --debug-scores` berhasil
[ ] Symbol discovery atau MANUAL_SYMBOLS sudah valid
[ ] Telegram test berhasil
[ ] Dry-run entry muncul
[ ] Dry-run close muncul
[ ] Tidak ada duplicate stacking
[ ] `logs/bot.log` terbaca
[ ] `data/bulk_bot.sqlite3` terbentuk
[ ] Baru isi private key agent wallet
[ ] Baru set ENABLE_LIVE_TRADING=true dan DRY_RUN=false
```


## v8: Anti-crash Symbol Fallback

Jika Bulk metadata sedang error seperti `502 Bad Gateway` atau `exchangeInfo=[]`, bot tidak akan berhenti total. Urutan symbol source sekarang:

1. `--symbols` dari command line
2. `MANUAL_SYMBOLS` di `.env`
3. Bulk metadata jika tersedia
4. `data/symbols_cache.json`
5. `STATIC_FALLBACK_SYMBOLS`

Untuk kompetisi, cara paling stabil adalah mengisi `MANUAL_SYMBOLS` dengan pair yang sudah terbukti valid:

```env
MANUAL_SYMBOLS=BTC-USD,ETH-USD,SOL-USD,XRP-USD,DOGE-USD,BNB-USD,SUI-USD
AUTO_DISCOVER_SYMBOLS=true
STATIC_FALLBACK_SYMBOLS=BTC-USD,ETH-USD,SOL-USD,XRP-USD,DOGE-USD,BNB-USD,SUI-USD
USE_STATIC_FALLBACK_SYMBOLS=true
```

Dengan ini, jika API discovery Bulk bermasalah, bot tetap bisa mulai dan scan loop akan skip pair yang sedang gagal tanpa crash.

## v9 notes: Telegram cockpit + leverage test

### Telegram UI
v9 improves Telegram cards for start, discovery, scan report, entry, close, warning, and leverage configuration. Test it with:

```powershell
python -m bulk_auto_bot.main --telegram-test
```

### Perpetual leverage
The bot now supports best-effort leverage update through the installed `bulk-client` SDK method `update_leverage`.

Add to `.env`:

```env
TARGET_LEVERAGE=5
APPLY_LEVERAGE_ON_START=false
USE_ISOLATED=false
```

Test in dry-run first:

```powershell
python -m bulk_auto_bot.main --leverage-test --symbols BTC-USD,ETH-USD
```

For live faucet only, after private key and permissions are confirmed:

```env
ENABLE_LIVE_TRADING=true
DRY_RUN=false
TARGET_LEVERAGE=5
APPLY_LEVERAGE_ON_START=true
```

Do not assume live leverage is configured until the Bulk API accepts the `update_leverage` call. If the installed SDK signature differs, the adapter will fail clearly instead of pretending success.

## v10: Strict exchangeInfo parser + leverage caps

Bulk `/exchangeInfo` returns market objects that include `symbol`, `tickSize`, `lotSize`, `minNotional`, `maxLeverage`, `orderTypes`, and `timeInForces`. Earlier versions of this bot walked every string in the metadata and could mistakenly treat enum values such as `LIMIT`, `MARKET`, `GTC`, and `IOC` as symbols. v10 fixes that by accepting only strict market symbols such as `BTC-USD` and by parsing market specs separately.

Recommended first run after upgrading:

```powershell
Remove-Item .\data\symbols_cache.json -ErrorAction SilentlyContinue
python -m bulk_auto_bot.main --dump-market-specs
python -m bulk_auto_bot.main --debug-scores
```

Leverage behavior:

- `TARGET_LEVERAGE` is capped per symbol using exchangeInfo `maxLeverage`.
- Order price is rounded to `tickSize`.
- Order size is rounded to `lotSize`.
- If desired notional is below `minNotional`, `ALLOW_MIN_NOTIONAL_UPSIZE=true` will upsize to the minimum valid order. Set it to `false` if you prefer skipping undersized orders.
- `USE_LEVERAGE_IN_SIZING=true` multiplies notional sizing by the effective capped leverage. Keep this enabled only for faucet/paper competition testing, not real funds.


## v12 leverage note

The installed Bulk Python SDK may expose `update_leverage(leverage_settings: List[tuple]) -> Dict`.
This version sends leverage as `[(symbol, leverage)]` first, then falls back to older helper shapes.
Set `TARGET_LEVERAGE=5` before running `--leverage-test`. If exchange metadata is empty, max leverage per symbol cannot be auto-capped, so use a conservative target leverage for faucet testing until `/exchangeInfo` returns full market specs.
