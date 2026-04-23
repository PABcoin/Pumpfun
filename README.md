# 🚀 PumpFun Telegram Bot

Bot Telegram untuk membuat token di [pump.fun](https://pump.fun) langsung dari chat Telegram — tanpa perlu buka browser.

---

## ✨ Fitur

- 🪙 Buat token pump.fun via wizard step-by-step
- 🖼 Upload logo langsung dari Telegram
- 🔗 Tambah social links (Twitter, Telegram, Website)
- 💰 Dev buy saat launch (opsional)
- 🔒 Private key aman di environment variable Railway

---

## 📋 Prasyarat

| Kebutuhan | Keterangan |
|---|---|
| Akun Telegram | Untuk membuat bot via @BotFather |
| Wallet Solana | Sudah ada SOL untuk gas fee |
| Akun GitHub | Untuk push kode |
| Akun Railway | Untuk hosting bot 24/7 (gratis) |

---

## ⚙️ Setup Langkah demi Langkah

### 1. Buat Bot Telegram

1. Buka [@BotFather](https://t.me/BotFather) di Telegram
2. Ketik `/newbot`
3. Ikuti instruksi — beri nama dan username bot
4. Salin **Token** yang diberikan BotFather (format: `123456:ABC-DEF...`)

---

### 2. Siapkan Wallet Solana

- Pastikan wallet kamu punya **minimal 0.02 SOL** untuk gas fee pembuatan token
- Salin **private key** wallet dalam format base58 atau JSON array
- ⚠️ **Gunakan wallet khusus bot** — jangan wallet utama kamu!

---

### 3. Push ke GitHub

```bash
# Clone / download folder ini, lalu:
git init
git add .
git commit -m "init pumpfun bot"

# Buat repo baru di github.com, lalu:
git remote add origin https://github.com/USERNAME/REPO_NAME.git
git branch -M main
git push -u origin main
```

---

### 4. Deploy ke Railway

#### 4a. Hubungkan GitHub ke Railway

1. Buka [railway.app](https://railway.app) → Login dengan GitHub
2. Klik **New Project** → **Deploy from GitHub repo**
3. Pilih repo yang baru kamu push
4. Railway akan otomatis mendeteksi konfigurasi dari `railway.json`

#### 4b. Set Environment Variables

Di Railway, masuk ke project → **Variables** → tambahkan:

| Variable | Nilai |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token dari BotFather |
| `WALLET_PRIVATE_KEY` | Private key Solana kamu |
| `SOLANA_RPC_URL` | *(Opsional)* Default: mainnet publik |

#### 4c. Deploy

- Klik **Deploy** — Railway akan install dependencies dan menjalankan bot
- Cek **Logs** untuk memastikan bot berjalan: `Bot berjalan...`

---

## 🤖 Cara Pakai Bot

| Perintah | Fungsi |
|---|---|
| `/start` | Tampilkan menu utama |
| `/create` | Mulai wizard pembuatan coin |
| `/cancel` | Batalkan proses |
| `/help` | Panduan singkat |

### Flow pembuatan coin:
```
/create
  → Nama coin
  → Ticker
  → Deskripsi (opsional)
  → Upload gambar logo
  → Twitter link (opsional)
  → Telegram link (opsional)
  → Website (opsional)
  → Dev buy amount (SOL)
  → Konfirmasi → DEPLOY! 🚀
```

---

## 🛠 Struktur Project

```
pumpfun-tgbot/
├── main.py          # Telegram bot & conversation handler
├── pump_fun.py      # Integrasi pump.fun & Solana
├── requirements.txt # Dependencies Python
├── railway.json     # Konfigurasi Railway
├── Procfile         # Entrypoint
├── .env.example     # Template environment variables
├── .gitignore
└── README.md
```

---

## 🔧 Jalankan Lokal (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Salin dan isi .env
cp .env.example .env
nano .env

# Jalankan bot
python main.py
```

---

## ⚠️ Catatan Penting

- **Jangan** commit file `.env` ke GitHub (sudah ada di `.gitignore`)
- Setiap pembuatan token membutuhkan ~0.01 SOL gas fee
- Gunakan RPC privat (Helius/QuickNode) untuk performa lebih baik
- Data coin (nama, ticker, gambar) **tidak bisa diubah** setelah deploy

---

## 📄 Lisensi

MIT License — bebas digunakan dan dimodifikasi.
