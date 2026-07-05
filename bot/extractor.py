"""
Extrae campos de transacciones desde imagen (OCR) o texto libre usando Claude.
"""

import os, base64, json
from datetime import datetime
import anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

def _system_prompt() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""Eres un asistente que estructura movimientos financieros venezolanos.
Devuelves SOLO un objeto JSON válido, sin texto adicional, con exactamente estos campos:

{{
  "description":    "nombre del negocio o descripción breve",
  "amount":         123.45,
  "currency":       "VES" | "USD" | "USDT",
  "type":           "gasto" | "ingreso",
  "category":       una de estas: Comida|Transporte|Servicios|Entretenimiento|Salud|Educación|Ropa|Ahorro Binance|Hogar|Deuda|Cashea|Otro gasto|Sueldo|Freelance|Inversión|Bono|Comisión|Negocio|Transferencia recibida|Otro ingreso,
  "payment_method": una de estas: Efectivo|Pago Móvil|Binance|Transferencia|Zelle|Dólares efectivo|Otro,
  "date":           "YYYY-MM-DD",
  "notes":          "detalle extra o null"
}}

Reglas:
- Si el monto está en bolívares (Bs. / BsF / VES), usa currency="VES".
- Si hay $ sin indicación, asume USD si el monto es pequeño (<1000), VES si es grande.
- Palabras clave para tipo: "pagué/gasté/compré" → gasto; "recibí/cobré/entró" → ingreso.
- Palabras clave para método: "pago móvil/PM" → Pago Móvil; "binance/USDT" → Binance; "efectivo/cash" → Efectivo.
- Si no hay fecha, usa hoy: {today}.
- Si no puedes determinar algo, usa el valor más razonable."""

def _parse_raw(raw: str) -> dict:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    data = json.loads(raw)
    if not data.get("date"):
        data["date"] = datetime.now().strftime("%Y-%m-%d")
    data.setdefault("description",    "Sin descripción")
    data.setdefault("amount",         0.0)
    data.setdefault("currency",       "VES")
    data.setdefault("type",           "gasto")
    data.setdefault("category",       "Otro gasto")
    data.setdefault("payment_method", "Efectivo")
    data.setdefault("notes",          None)
    return data


async def extract_from_text(text: str) -> dict:
    """Parsea texto libre en lenguaje natural a un dict de transacción."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    message = await client.messages.create(
        model      = "claude-haiku-4-5-20251001",
        max_tokens = 512,
        system     = _system_prompt(),
        messages   = [{"role": "user", "content": text}],
    )
    return _parse_raw(message.content[0].text.strip())


async def extract_invoice(image_bytes: bytes) -> dict:
    img_b64    = base64.standard_b64encode(image_bytes).decode()
    # Detectar formato (JPEG es el más común de cámaras de teléfono)
    media_type = "image/jpeg"
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        media_type = "image/png"
    elif image_bytes[:4] == b'%PDF':
        raise ValueError("PDF no soportado directamente; envía una foto del recibo.")

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    message = await client.messages.create(
        model      = "claude-haiku-4-5-20251001",
        max_tokens = 512,
        system     = _system_prompt(),
        messages   = [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": media_type,
                        "data":       img_b64,
                    },
                },
                {"type": "text", "text": "Extrae los datos de esta factura/recibo y devuelve el JSON."},
            ],
        }],
    )
    return _parse_raw(message.content[0].text.strip())
