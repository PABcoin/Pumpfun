import os
import logging
import asyncio
from io import BytesIO

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from pump_fun import upload_metadata_to_ipfs, create_token_transaction

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
(
    ASK_NAME,
    ASK_TICKER,
    ASK_DESCRIPTION,
    ASK_IMAGE,
    ASK_TWITTER,
    ASK_TELEGRAM,
    ASK_WEBSITE,
    ASK_BUY_AMOUNT,
    CONFIRM,
) = range(9)

# ── Helpers ───────────────────────────────────────────────────────────────────

def build_preview(data: dict) -> str:
    lines = [
        "📋 *Preview Coin Kamu*",
        "",
        f"🪙 *Nama   :* `{data.get('name', '-')}`",
        f"🔤 *Ticker :* `{data.get('ticker', '-')}`",
        f"📝 *Deskripsi :* {data.get('description', '-')}",
    ]
    if data.get("twitter"):
        lines.append(f"🐦 *Twitter :* {data['twitter']}")
    if data.get("telegram"):
        lines.append(f"✈️ *Telegram :* {data['telegram']}")
    if data.get("website"):
        lines.append(f"🌐 *Website :* {data['website']}")
    lines += [
        "",
        f"💰 *Dev Buy :* `{data.get('buy_amount', 0)} SOL`",
    ]
    return "\n".join(lines)


# ── Command Handlers ──────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("🚀 Buat Coin Baru", callback_data="create")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Selamat datang di *PumpFun Bot*!\n\n"
        "Bot ini membantu kamu membuat token di pump.fun langsung dari Telegram.\n\n"
        "Gunakan perintah di bawah:\n"
        "• /create — Buat coin baru\n"
        "• /cancel — Batalkan proses\n"
        "• /help  — Bantuan",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🛠 *Panduan PumpFun Bot*\n\n"
        "1️⃣ Ketik /create untuk mulai membuat coin\n"
        "2️⃣ Ikuti langkah-langkah yang diminta\n"
        "3️⃣ Upload gambar logo coin kamu\n"
        "4️⃣ Konfirmasi dan bot akan deploy ke pump.fun\n\n"
        "⚠️ *Pastikan* kamu sudah set `WALLET_PRIVATE_KEY` di environment.\n"
        "Setiap pembuatan coin membutuhkan sedikit SOL untuk gas fee.",
        parse_mode="Markdown",
    )


# ── Create Coin Conversation ──────────────────────────────────────────────────

async def create_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point — bisa dari /create atau tombol inline."""
    ctx.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "🪙 *Langkah 1/8 — Nama Coin*\n\n"
            "Ketik nama coin kamu (contoh: `Moon Rocket`):",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🪙 *Langkah 1/8 — Nama Coin*\n\n"
            "Ketik nama coin kamu (contoh: `Moon Rocket`):",
            parse_mode="Markdown",
        )
    return ASK_NAME


async def received_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 32:
        await update.message.reply_text("❌ Nama harus antara 2–32 karakter. Coba lagi:")
        return ASK_NAME
    ctx.user_data["name"] = name
    await update.message.reply_text(
        "🔤 *Langkah 2/8 — Ticker*\n\n"
        "Ketik ticker coin kamu (maks 10 huruf, contoh: `MOON`):",
        parse_mode="Markdown",
    )
    return ASK_TICKER


async def received_ticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ticker = update.message.text.strip().upper()
    if len(ticker) < 2 or len(ticker) > 10:
        await update.message.reply_text("❌ Ticker harus antara 2–10 karakter. Coba lagi:")
        return ASK_TICKER
    ctx.user_data["ticker"] = ticker
    await update.message.reply_text(
        "📝 *Langkah 3/8 — Deskripsi*\n\n"
        "Tulis deskripsi singkat coin kamu (atau ketik /skip untuk lewati):",
        parse_mode="Markdown",
    )
    return ASK_DESCRIPTION


async def received_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["description"] = "" if text == "/skip" else text
    await update.message.reply_text(
        "🖼 *Langkah 4/8 — Logo/Gambar*\n\n"
        "Kirim gambar logo coin kamu (JPG/PNG, min 1000×1000px):",
        parse_mode="Markdown",
    )
    return ASK_IMAGE


async def received_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo and not update.message.document:
        await update.message.reply_text("❌ Harap kirim file gambar yang valid (JPG/PNG).")
        return ASK_IMAGE

    await update.message.reply_text("⏳ Mengunduh gambar...")

    if update.message.photo:
        file = await update.message.photo[-1].get_file()
    else:
        file = await update.message.document.get_file()

    buf = BytesIO()
    await file.download_to_memory(buf)
    buf.seek(0)
    ctx.user_data["image_bytes"] = buf.read()
    ctx.user_data["image_name"] = "logo.jpg"

    await update.message.reply_text(
        "✅ Gambar diterima!\n\n"
        "🐦 *Langkah 5/8 — Twitter* (opsional)\n\n"
        "Ketik link Twitter kamu atau /skip:",
        parse_mode="Markdown",
    )
    return ASK_TWITTER


async def received_twitter(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["twitter"] = "" if text == "/skip" else text
    await update.message.reply_text(
        "✈️ *Langkah 6/8 — Telegram* (opsional)\n\n"
        "Ketik link grup Telegram atau /skip:",
        parse_mode="Markdown",
    )
    return ASK_TELEGRAM


async def received_telegram_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["telegram"] = "" if text == "/skip" else text
    await update.message.reply_text(
        "🌐 *Langkah 7/8 — Website* (opsional)\n\n"
        "Ketik URL website atau /skip:",
        parse_mode="Markdown",
    )
    return ASK_WEBSITE


async def received_website(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["website"] = "" if text == "/skip" else text
    await update.message.reply_text(
        "💰 *Langkah 8/8 — Dev Buy (SOL)*\n\n"
        "Berapa SOL yang ingin kamu beli saat launch?\n"
        "Ketik `0` untuk tidak membeli, atau angka seperti `0.5`:",
        parse_mode="Markdown",
    )
    return ASK_BUY_AMOUNT


async def received_buy_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text.strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Masukkan angka yang valid (contoh: `0` atau `0.5`):")
        return ASK_BUY_AMOUNT

    ctx.user_data["buy_amount"] = amount

    preview = build_preview(ctx.user_data)
    keyboard = [
        [
            InlineKeyboardButton("✅ Deploy Sekarang!", callback_data="confirm_deploy"),
            InlineKeyboardButton("❌ Batalkan", callback_data="cancel_deploy"),
        ]
    ]
    await update.message.reply_text(
        preview + "\n\n⚠️ Data di atas tidak bisa diubah setelah deploy. Lanjutkan?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CONFIRM


async def confirm_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_deploy":
        await query.message.reply_text(
            "❌ Pembuatan coin dibatalkan. Ketik /create untuk mulai lagi."
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    await query.message.reply_text("🚀 Memproses... Mohon tunggu sebentar.")

    data = ctx.user_data
    try:
        # 1. Upload metadata & image ke IPFS via pump.fun
        await query.message.reply_text("📤 Uploading metadata ke IPFS...")
        metadata_uri = await upload_metadata_to_ipfs(
            name=data["name"],
            symbol=data["ticker"],
            description=data.get("description", ""),
            twitter=data.get("twitter", ""),
            telegram=data.get("telegram", ""),
            website=data.get("website", ""),
            image_bytes=data["image_bytes"],
            image_name=data.get("image_name", "logo.jpg"),
        )

        # 2. Buat dan kirim transaksi ke Solana
        await query.message.reply_text("⛓ Membuat transaksi di Solana...")
        result = await create_token_transaction(
            metadata_uri=metadata_uri,
            buy_sol=data.get("buy_amount", 0),
        )

        if result.get("success"):
            mint = result.get("mint", "")
            sig  = result.get("signature", "")
            await query.message.reply_text(
                "🎉 *Coin berhasil dibuat!*\n\n"
                f"🪙 *Mint Address:*\n`{mint}`\n\n"
                f"🔗 [Lihat di Pump.fun](https://pump.fun/{mint})\n"
                f"🔍 [Lihat Transaksi](https://solscan.io/tx/{sig})\n\n"
                "Selamat! Coin kamu sudah live 🚀",
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        else:
            error = result.get("error", "Unknown error")
            await query.message.reply_text(
                f"❌ *Gagal membuat coin:*\n`{error}`\n\nCoba lagi dengan /create",
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.exception("Error saat deploy coin")
        await query.message.reply_text(
            f"❌ *Error:* `{str(e)}`\n\nPastikan WALLET_PRIVATE_KEY sudah di-set dan wallet kamu punya cukup SOL.",
            parse_mode="Markdown",
        )

    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text(
        "❌ Proses dibatalkan. Ketik /create untuk mulai lagi.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN tidak ditemukan di environment!")

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("create", create_start),
            CallbackQueryHandler(create_start, pattern="^create$"),
        ],
        states={
            ASK_NAME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, received_name)],
            ASK_TICKER:      [MessageHandler(filters.TEXT & ~filters.COMMAND, received_ticker)],
            ASK_DESCRIPTION: [MessageHandler(filters.TEXT, received_description)],
            ASK_IMAGE:       [MessageHandler(filters.PHOTO | filters.Document.IMAGE, received_image)],
            ASK_TWITTER:     [MessageHandler(filters.TEXT, received_twitter)],
            ASK_TELEGRAM:    [MessageHandler(filters.TEXT, received_telegram_link)],
            ASK_WEBSITE:     [MessageHandler(filters.TEXT, received_website)],
            ASK_BUY_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, received_buy_amount)],
            CONFIRM:         [CallbackQueryHandler(confirm_deploy, pattern="^(confirm_deploy|cancel_deploy)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(conv_handler)

    logger.info("Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
