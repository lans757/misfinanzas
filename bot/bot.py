"""
MisFinanzas Invoice Bot
Recibe fotos de facturas vía Telegram → extrae datos → inserta en MisFinanzas.
"""

import os, json, logging, asyncio
from datetime import datetime
from pathlib import Path

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

from extractor import extract_invoice, extract_from_text
from client   import MisFinanzasClient, MFError

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("mfbot")

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER = int(os.environ.get("TELEGRAM_ALLOWED_USER_ID", "0"))  # 0 = anyone
MF_BASE_URL  = os.environ.get("MF_BASE_URL", "http://localhost:5000")
MF_USERNAME  = os.environ["MF_USERNAME"]
MF_PASSWORD  = os.environ["MF_PASSWORD"]

# Categorías válidas (deben coincidir con index.html)
CATS_GASTO   = ["Comida","Transporte","Servicios","Entretenimiento","Salud",
                 "Educación","Ropa","Ahorro Binance","Hogar","Deuda","Cashea","Otro gasto"]
CATS_INGRESO = ["Sueldo","Freelance","Inversión","Bono","Comisión",
                 "Negocio","Transferencia recibida","Otro ingreso"]
PAY_METHODS  = ["Efectivo","Pago Móvil","Binance","Transferencia",
                "Zelle","Dólares efectivo","Otro"]

# Estados de conversación
AWAIT_CONFIRM = 1
EDIT_FIELD    = 2

# ── Auth guard ────────────────────────────────────────────────────────────────
def allowed(update: Update) -> bool:
    if ALLOWED_USER == 0:
        return True
    return update.effective_user.id == ALLOWED_USER

# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt_summary(data: dict) -> str:
    tipo_icon = "💚" if data["type"] == "ingreso" else "🔴"
    moneda    = data.get("currency", "VES")
    monto     = data.get("amount", 0)
    fecha     = data.get("date", datetime.now().strftime("%Y-%m-%d"))

    lines = [
        f"{tipo_icon} *{data.get('description', '—')}*",
        f"",
        f"💰 *Monto:* `{monto} {moneda}`",
        f"📂 *Categoría:* {data.get('category', '—')}",
        f"💳 *Método:* {data.get('payment_method', 'Efectivo')}",
        f"📅 *Fecha:* {fecha}",
    ]
    if data.get("notes"):
        lines.append(f"📝 *Notas:* {data['notes']}")
    return "\n".join(lines)

def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
            InlineKeyboardButton("✏️ Editar",    callback_data="edit"),
        ],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ])

def edit_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📝 Descripción",  callback_data="edit_description"),
         InlineKeyboardButton("💰 Monto",         callback_data="edit_amount")],
        [InlineKeyboardButton("📂 Categoría",     callback_data="edit_category"),
         InlineKeyboardButton("💳 Método pago",   callback_data="edit_payment_method")],
        [InlineKeyboardButton("📅 Fecha",         callback_data="edit_date"),
         InlineKeyboardButton("🔄 Tipo",          callback_data="edit_type")],
        [InlineKeyboardButton("« Volver",         callback_data="back_confirm")],
    ]
    return InlineKeyboardMarkup(buttons)

def category_keyboard(tipo: str) -> InlineKeyboardMarkup:
    cats = CATS_INGRESO if tipo == "ingreso" else CATS_GASTO
    rows = []
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(c, callback_data=f"cat_{c}") for c in cats[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("« Volver", callback_data="back_confirm")])
    return InlineKeyboardMarkup(rows)

def payment_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(PAY_METHODS), 2):
        row = [InlineKeyboardButton(m, callback_data=f"pay_{m}") for m in PAY_METHODS[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("« Volver", callback_data="back_confirm")])
    return InlineKeyboardMarkup(rows)

def type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Gasto",   callback_data="type_gasto"),
         InlineKeyboardButton("💚 Ingreso", callback_data="type_ingreso")],
        [InlineKeyboardButton("« Volver",   callback_data="back_confirm")],
    ])

# ── Handlers ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "👋 *Bot de facturas — MisFinanzas*\n\n"
        "Puedes registrar movimientos de dos formas:\n\n"
        "📷 *Foto* — mándame una imagen de la factura\n"
        "✍️ *Texto* — escríbeme lo que pasó, por ejemplo:\n"
        "  _gasté 50$ en el supermercado con pago móvil_\n"
        "  _recibí 200 USDT de freelance hoy_\n"
        "  _pagué 85.000 Bs de electricidad por transferencia_\n\n"
        "/cancelar — aborta el registro en curso",
        parse_mode="Markdown"
    )

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Registro cancelado.")
    return ConversationHandler.END

async def handle_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Procesa texto libre en lenguaje natural."""
    if not allowed(update):
        return

    texto = update.message.text.strip()
    msg   = await update.message.reply_text("🧠 Interpretando…")

    try:
        data = await extract_from_text(texto)
    except Exception as e:
        log.error("extract_from_text error: %s", e)
        await msg.edit_text(f"❌ No pude interpretar eso: {e}")
        return ConversationHandler.END

    ctx.user_data["invoice"]    = data
    ctx.user_data["edit_field"] = None

    summary = fmt_summary(data)
    await msg.edit_text(
        f"📋 *Esto es lo que entendí:*\n\n{summary}\n\n¿Lo registro así?",
        parse_mode="Markdown",
        reply_markup=confirm_keyboard(),
    )
    return AWAIT_CONFIRM


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return

    msg = await update.message.reply_text("🔍 Leyendo factura…")

    # Descargar la foto más grande
    photo  = update.message.photo[-1]
    tg_file = await photo.get_file()
    img_bytes = await tg_file.download_as_bytearray()

    try:
        data = await extract_invoice(bytes(img_bytes))
    except Exception as e:
        log.error("extract_invoice error: %s", e)
        await msg.edit_text(f"❌ No pude leer la factura: {e}")
        return ConversationHandler.END

    ctx.user_data["invoice"] = data
    ctx.user_data["edit_field"] = None

    summary = fmt_summary(data)
    await msg.edit_text(
        f"📄 *Esto es lo que encontré:*\n\n{summary}\n\n¿Lo registro así?",
        parse_mode="Markdown",
        reply_markup=confirm_keyboard(),
    )
    return AWAIT_CONFIRM

async def cb_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = ctx.user_data.get("invoice", {})

    await query.edit_message_text("⏳ Registrando…")
    try:
        client = MisFinanzasClient(MF_BASE_URL, MF_USERNAME, MF_PASSWORD)
        tx = await client.create_transaction(data)
        await query.edit_message_text(
            f"✅ *Registrado* (#{tx['id']})\n\n{fmt_summary(data)}",
            parse_mode="Markdown"
        )
    except MFError as e:
        await query.edit_message_text(f"❌ Error al guardar: {e}")

    ctx.user_data.clear()
    return ConversationHandler.END

async def cb_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("❌ Registro cancelado.")
    ctx.user_data.clear()
    return ConversationHandler.END

async def cb_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = ctx.user_data.get("invoice", {})
    await update.callback_query.edit_message_text(
        f"✏️ *¿Qué quieres cambiar?*\n\n{fmt_summary(data)}",
        parse_mode="Markdown",
        reply_markup=edit_keyboard(),
    )
    return AWAIT_CONFIRM

async def cb_edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data  # "edit_description", "edit_amount", etc.

    data = ctx.user_data.get("invoice", {})

    if field == "edit_category":
        await query.edit_message_text(
            "📂 Elige la categoría:",
            reply_markup=category_keyboard(data.get("type", "gasto"))
        )
        return AWAIT_CONFIRM

    if field == "edit_payment_method":
        await query.edit_message_text("💳 Elige el método de pago:", reply_markup=payment_keyboard())
        return AWAIT_CONFIRM

    if field == "edit_type":
        await query.edit_message_text("🔄 ¿Gasto o ingreso?", reply_markup=type_keyboard())
        return AWAIT_CONFIRM

    # Campos de texto libre
    field_name = field.replace("edit_", "")
    prompts = {
        "description":    "Escribe la nueva descripción:",
        "amount":         "Escribe el monto (ej: `150.00`):",
        "date":           "Escribe la fecha (`YYYY-MM-DD`):",
    }
    ctx.user_data["edit_field"] = field_name
    await query.edit_message_text(prompts.get(field_name, f"Escribe el valor para *{field_name}*:"), parse_mode="Markdown")
    return EDIT_FIELD

async def cb_inline_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = ctx.user_data.get("invoice", {})
    cd   = query.data

    if cd.startswith("cat_"):
        data["category"] = cd[4:]
    elif cd.startswith("pay_"):
        data["payment_method"] = cd[4:]
    elif cd.startswith("type_"):
        data["type"] = cd[5:]
        # Ajusta la categoría al nuevo tipo si no encaja
        cats = CATS_INGRESO if data["type"] == "ingreso" else CATS_GASTO
        if data.get("category") not in cats:
            data["category"] = cats[0]
    elif cd == "back_confirm":
        pass

    ctx.user_data["invoice"] = data
    summary = fmt_summary(data)
    await query.edit_message_text(
        f"📄 *Resumen actualizado:*\n\n{summary}\n\n¿Lo registro así?",
        parse_mode="Markdown",
        reply_markup=confirm_keyboard(),
    )
    return AWAIT_CONFIRM

async def handle_text_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    field = ctx.user_data.get("edit_field")
    if not field:
        return

    value = update.message.text.strip()
    data  = ctx.user_data.get("invoice", {})

    if field == "amount":
        try:
            value = float(value.replace(",", "."))
        except ValueError:
            await update.message.reply_text("❌ Monto inválido. Escribe un número (ej: `150.00`):", parse_mode="Markdown")
            return EDIT_FIELD

    data[field] = value
    ctx.user_data["invoice"]    = data
    ctx.user_data["edit_field"] = None

    summary = fmt_summary(data)
    await update.message.reply_text(
        f"📄 *Resumen actualizado:*\n\n{summary}\n\n¿Lo registro así?",
        parse_mode="Markdown",
        reply_markup=confirm_keyboard(),
    )
    return AWAIT_CONFIRM

# ── App wiring ────────────────────────────────────────────────────────────────
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.PHOTO, handle_photo),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input),
        ],
        states={
            AWAIT_CONFIRM: [
                CallbackQueryHandler(cb_confirm,    pattern="^confirm$"),
                CallbackQueryHandler(cb_cancel,     pattern="^cancel$"),
                CallbackQueryHandler(cb_edit,       pattern="^edit$"),
                CallbackQueryHandler(cb_inline_pick,pattern="^(cat_|pay_|type_|back_)"),
                CallbackQueryHandler(cb_edit_field, pattern="^edit_"),
            ],
            EDIT_FIELD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_edit),
            ],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("cancelar", cmd_cancel))
    app.add_handler(conv)

    return app

if __name__ == "__main__":
    log.info("Arrancando MisFinanzas Invoice Bot…")
    build_app().run_polling(drop_pending_updates=True)
