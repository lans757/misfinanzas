from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from passlib.context import CryptContext
from jose import JWTError, jwt
from google import genai
from google.genai import types as gtypes
import httpx
import asyncio
import secrets
import os
from pathlib import Path
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional, List

# ── Clave secreta persistente ─────────────────────────────────────────────────
_KEY_FILE = ".secret_key"
if os.path.exists(_KEY_FILE):
    with open(_KEY_FILE) as f:
        SECRET_KEY = f.read().strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    with open(_KEY_FILE, "w") as f:
        f.write(SECRET_KEY)

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30

# ── Gemini API Key (cargado desde .env) ───────────────────────────────────────
def _load_env():
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def _save_gemini_key(key: str):
    global GEMINI_API_KEY
    env = Path(".env")
    lines = env.read_text().splitlines() if env.exists() else []
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("GEMINI_API_KEY="):
            lines[i] = f"GEMINI_API_KEY={key}"
            updated = True
            break
    if not updated:
        lines.append(f"GEMINI_API_KEY={key}")
    env.write_text("\n".join(lines) + "\n")
    GEMINI_API_KEY = key
    os.environ["GEMINI_API_KEY"] = key


def _get_genai_client():
    if not GEMINI_API_KEY:
        raise HTTPException(400, "Configura tu API key de Gemini primero")
    return genai.Client(api_key=GEMINI_API_KEY)

# ── Base de datos ─────────────────────────────────────────────────────────────
DATABASE_URL = "sqlite:///./finanzas.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at      = Column(DateTime, default=datetime.now)


class Transaction(Base):
    __tablename__ = "transactions"
    id                   = Column(Integer, primary_key=True, index=True)
    user_id              = Column(Integer, nullable=True)   # FK a users.id
    date                 = Column(DateTime, default=datetime.now)
    description          = Column(String, nullable=False)
    category             = Column(String, nullable=False)
    type                 = Column(String, nullable=False)   # ingreso | gasto
    amount               = Column(Float, nullable=False)
    currency             = Column(String, nullable=False, default="VES")
    payment_method       = Column(String, nullable=True)
    exchange_rate_bcv    = Column(Float, nullable=True)
    exchange_rate_binance= Column(Float, nullable=True)
    amount_ves           = Column(Float, nullable=False)
    amount_usd           = Column(Float, nullable=True)
    amount_usdt          = Column(Float, nullable=True)
    notes                = Column(String, nullable=True)


Base.metadata.create_all(bind=engine)

# ── Migración: agregar user_id si no existe ───────────────────────────────────
with engine.connect() as _conn:
    try:
        _conn.execute(text("ALTER TABLE transactions ADD COLUMN user_id INTEGER"))
        _conn.commit()
    except Exception:
        pass  # columna ya existe


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Utilidades de autenticación ───────────────────────────────────────────────
pwd_context   = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db:    Session = Depends(get_db),
) -> User:
    try:
        payload  = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(401, "Token inválido")
    except JWTError:
        raise HTTPException(401, "Token inválido o expirado")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(401, "Usuario no encontrado")
    return user


# ── Tasas externas ────────────────────────────────────────────────────────────
async def fetch_bcv_rate() -> Optional[float]:
    sources = [
        ("https://ve.dolarapi.com/v1/dolares/oficial",
         lambda d: d.get("promedio") or d.get("promedioPonderado")),
        ("https://pydolarve.org/api/v1/dollar?page=bcv",
         lambda d: (d.get("monitors") or {}).get("bcv", {}).get("price")
                   or (d.get("USD") or {}).get("price")),
    ]
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for url, extractor in sources:
            try:
                resp  = await client.get(url)
                resp.raise_for_status()
                value = extractor(resp.json())
                if value:
                    return float(value)
            except Exception as e:
                print(f"[BCV] {url} falló: {e}")
    return None


async def fetch_binance_p2p_rate() -> Optional[float]:
    payload = {
        "asset": "USDT", "fiat": "VES", "merchantCheck": False,
        "page": 1, "publisherType": None, "rows": 10,
        "side": "BUY", "tradeType": "BUY",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(
                "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                json=payload,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            ads = resp.json().get("data", [])
            if ads:
                prices = [float(ad["adv"]["price"]) for ad in ads[:5]]
                return round(sum(prices) / len(prices), 2)
    except Exception as e:
        print(f"[Binance P2P] falló: {e}")
    return None


# ── Schemas Pydantic ──────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TransactionCreate(BaseModel):
    description:          str
    category:             str
    type:                 str
    amount:               float
    currency:             str = "VES"
    payment_method:       Optional[str]   = None
    exchange_rate_bcv:    Optional[float] = None
    exchange_rate_binance:Optional[float] = None
    notes:                Optional[str]   = None
    date:                 Optional[datetime] = None


class TransactionOut(BaseModel):
    id:                   int
    date:                 datetime
    description:          str
    category:             str
    type:                 str
    amount:               float
    currency:             str
    payment_method:       Optional[str]
    exchange_rate_bcv:    Optional[float]
    exchange_rate_binance:Optional[float]
    amount_ves:           float
    amount_usd:           Optional[float]
    amount_usdt:          Optional[float]
    notes:                Optional[str]
    model_config = {"from_attributes": True}


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="MisFinanzas")


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/api/auth/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    if len(username) < 3:
        raise HTTPException(400, "El usuario debe tener mínimo 3 caracteres")
    if len(body.password) < 6:
        raise HTTPException(400, "La contraseña debe tener mínimo 6 caracteres")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(400, "Ese nombre de usuario ya está en uso")
    user = User(username=username, hashed_password=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "access_token": create_token(user.username),
        "token_type": "bearer",
        "username": user.username,
    }


@app.post("/api/auth/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    return {
        "access_token": create_token(user.username),
        "token_type": "bearer",
        "username": user.username,
    }


@app.get("/api/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id":         current_user.id,
        "username":   current_user.username,
        "created_at": current_user.created_at.isoformat(),
    }


# ── Tasas (pública) ───────────────────────────────────────────────────────────
@app.get("/api/rates")
async def get_rates():
    bcv, binance = await asyncio.gather(fetch_bcv_rate(), fetch_binance_p2p_rate())
    return {"bcv": bcv, "binance_p2p": binance, "timestamp": datetime.now().isoformat()}


# ── Transacciones (protegidas) ────────────────────────────────────────────────
@app.get("/api/transactions", response_model=List[TransactionOut])
def list_transactions(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    return (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .order_by(Transaction.date.desc())
        .all()
    )


@app.post("/api/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(
    body:         TransactionCreate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    amount_ves  = body.amount
    amount_usd  = None
    amount_usdt = None

    if body.currency == "USD":
        if not body.exchange_rate_bcv:
            raise HTTPException(400, "exchange_rate_bcv requerido para USD")
        amount_ves  = body.amount * body.exchange_rate_bcv
        amount_usd  = body.amount
        if body.exchange_rate_binance:
            amount_usdt = amount_ves / body.exchange_rate_binance

    elif body.currency == "USDT":
        if not body.exchange_rate_binance:
            raise HTTPException(400, "exchange_rate_binance requerido para USDT")
        amount_ves  = body.amount * body.exchange_rate_binance
        amount_usdt = body.amount
        if body.exchange_rate_bcv:
            amount_usd = amount_ves / body.exchange_rate_bcv

    else:  # VES
        if body.exchange_rate_bcv:
            amount_usd  = amount_ves / body.exchange_rate_bcv
        if body.exchange_rate_binance:
            amount_usdt = amount_ves / body.exchange_rate_binance

    t = Transaction(
        user_id              = current_user.id,
        date                 = body.date or datetime.now(),
        description          = body.description,
        category             = body.category,
        type                 = body.type,
        amount               = body.amount,
        currency             = body.currency,
        payment_method       = body.payment_method,
        exchange_rate_bcv    = body.exchange_rate_bcv,
        exchange_rate_binance= body.exchange_rate_binance,
        amount_ves           = amount_ves,
        amount_usd           = amount_usd,
        amount_usdt          = amount_usdt,
        notes                = body.notes,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@app.delete("/api/transactions/{tid}")
def delete_transaction(
    tid:          int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    t = (
        db.query(Transaction)
        .filter(Transaction.id == tid, Transaction.user_id == current_user.id)
        .first()
    )
    if not t:
        raise HTTPException(404, "Movimiento no encontrado")
    db.delete(t)
    db.commit()
    return {"ok": True}


@app.get("/api/summary")
def get_summary(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    rows = db.query(Transaction).filter(Transaction.user_id == current_user.id).all()

    total_ingresos = sum(r.amount_ves for r in rows if r.type == "ingreso")
    total_gastos   = sum(r.amount_ves for r in rows if r.type == "gasto")
    usdt_ingresos  = sum(r.amount for r in rows if r.type == "ingreso" and r.currency == "USDT")
    usdt_gastos    = sum(r.amount for r in rows if r.type == "gasto"   and r.currency == "USDT")

    now     = datetime.now()
    monthly = [r for r in rows if r.date.month == now.month and r.date.year == now.year]

    categories: dict = {}
    for r in rows:
        if r.type == "gasto":
            categories[r.category] = categories.get(r.category, 0) + r.amount_ves

    return {
        "total_ingresos_ves": total_ingresos,
        "total_gastos_ves":   total_gastos,
        "saldo_ves":          total_ingresos - total_gastos,
        "usdt_balance":       usdt_ingresos - usdt_gastos,
        "monthly_ingresos":   sum(r.amount_ves for r in monthly if r.type == "ingreso"),
        "monthly_gastos":     sum(r.amount_ves for r in monthly if r.type == "gasto"),
        "categories":         categories,
    }


@app.get("/api/monthly-flow")
def get_monthly_flow(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    rows    = db.query(Transaction).filter(Transaction.user_id == current_user.id).all()
    monthly: dict = {}
    for r in rows:
        key = f"{r.date.year}-{r.date.month:02d}"
        if key not in monthly:
            monthly[key] = {"ingresos": 0, "gastos": 0}
        if r.type == "ingreso":
            monthly[key]["ingresos"] += r.amount_ves
        else:
            monthly[key]["gastos"]   += r.amount_ves

    sorted_months = sorted(monthly.items())[-6:]
    return {
        "labels":   [m[0] for m in sorted_months],
        "ingresos": [round(m[1]["ingresos"], 2) for m in sorted_months],
        "gastos":   [round(m[1]["gastos"],   2) for m in sorted_months],
    }


# ── Asistente IA (Gemini) ─────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str     # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class GeminiKeyRequest(BaseModel):
    api_key: str


def _build_system_prompt(username: str, rows: list, rates: dict) -> str:
    total_ingresos = sum(r.amount_ves for r in rows if r.type == "ingreso")
    total_gastos   = sum(r.amount_ves for r in rows if r.type == "gasto")
    saldo          = total_ingresos - total_gastos
    usdt_balance   = sum(r.amount for r in rows if r.type == "ingreso" and r.currency == "USDT") \
                   - sum(r.amount for r in rows if r.type == "gasto"   and r.currency == "USDT")

    now = datetime.now()
    monthly = [r for r in rows if r.date.month == now.month and r.date.year == now.year]
    mes_ingresos = sum(r.amount_ves for r in monthly if r.type == "ingreso")
    mes_gastos   = sum(r.amount_ves for r in monthly if r.type == "gasto")

    cats: dict = {}
    for r in rows:
        if r.type == "gasto":
            cats[r.category] = cats.get(r.category, 0) + r.amount_ves
    cats_str = "\n".join(f"  • {k}: Bs {v:,.2f}" for k, v in sorted(cats.items(), key=lambda x: -x[1])[:8]) or "  Sin datos"

    last_txns = rows[:10]
    txns_str  = "\n".join(
        f"  {'↑' if t.type=='ingreso' else '↓'} {t.date.strftime('%d/%m')} | {t.category} | {t.description} | Bs {t.amount_ves:,.2f}"
        for t in last_txns
    ) or "  Sin transacciones"

    saldo_usd  = f"${saldo/rates['bcv']:.2f}" if rates.get("bcv") else "N/A"
    usdt_en_bs = f"Bs {usdt_balance*rates['binance_p2p']:,.2f}" if rates.get("binance_p2p") else "N/A"

    return f"""Eres un asistente financiero personal inteligente y amigable, especializado en la economía venezolana.
Ayudas al usuario "{username}" a entender y mejorar sus finanzas personales en bolívares (VES), dólares (USD) y USDT.

━━━ DATOS FINANCIEROS ACTUALES DE {username.upper()} ━━━

💰 RESUMEN GENERAL:
  • Saldo total: Bs {saldo:,.2f} ({saldo_usd} al BCV)
  • Total ingresos históricos: Bs {total_ingresos:,.2f}
  • Total gastos históricos: Bs {total_gastos:,.2f}
  • Saldo USDT en Binance: {usdt_balance:.4f} USDT ({usdt_en_bs})

📅 ESTE MES ({now.strftime('%B %Y')}):
  • Ingresos: Bs {mes_ingresos:,.2f}
  • Gastos: Bs {mes_gastos:,.2f}
  • Balance del mes: Bs {mes_ingresos - mes_gastos:,.2f}

💱 TASAS DE CAMBIO ACTUALES:
  • Dólar BCV oficial: Bs {rates.get('bcv') or 'No disponible'}
  • USDT Binance P2P: Bs {rates.get('binance_p2p') or 'No disponible'}

🗂️ GASTOS POR CATEGORÍA (acumulado):
{cats_str}

📋 ÚLTIMOS 10 MOVIMIENTOS:
{txns_str}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Responde SIEMPRE en español, de forma clara, amigable y práctica.
Da consejos específicos y realistas basados en los datos reales del usuario.
Si no hay suficientes datos, indícalo amablemente y sugiere cómo empezar a registrar.
Cuando hagas cálculos, muestra los números claramente.
Sé conciso: respuestas de 2-4 párrafos máximo salvo que el usuario pida más detalle."""


@app.get("/api/ai/status")
def ai_status(_: User = Depends(get_current_user)):
    return {"configured": bool(GEMINI_API_KEY)}


@app.post("/api/ai/key")
def set_ai_key(body: GeminiKeyRequest, _: User = Depends(get_current_user)):
    if not body.api_key.strip():
        raise HTTPException(400, "La API key no puede estar vacía")
    _save_gemini_key(body.api_key.strip())
    return {"ok": True, "message": "API key guardada correctamente"}


@app.post("/api/ai/chat")
async def ai_chat(
    body:         ChatRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    if not GEMINI_API_KEY:
        raise HTTPException(400, "Configura tu API key de Gemini primero")
    if not body.messages:
        raise HTTPException(400, "Sin mensajes")

    # Construir contexto financiero
    rows = db.query(Transaction).filter(Transaction.user_id == current_user.id).all()
    bcv, binance = await asyncio.gather(fetch_bcv_rate(), fetch_binance_p2p_rate())
    rates = {"bcv": bcv, "binance_p2p": binance}

    system_prompt = _build_system_prompt(current_user.username, rows, rates)

    # Mapear roles: "assistant" → "model" (requerido por Gemini)
    history = []
    for msg in body.messages[:-1]:
        history.append({
            "role":  "model" if msg.role == "assistant" else "user",
            "parts": [msg.content],
        })

    last_message = body.messages[-1].content

    try:
        client = _get_genai_client()

        # Construir historial en formato del nuevo SDK
        contents = []
        for msg in body.messages[:-1]:
            contents.append(gtypes.Content(
                role  = "model" if msg.role == "assistant" else "user",
                parts = [gtypes.Part(text=msg.content)],
            ))
        contents.append(gtypes.Content(
            role  = "user",
            parts = [gtypes.Part(text=last_message)],
        ))

        response = client.models.generate_content(
            model    = "gemini-1.5-flash",
            contents = contents,
            config   = gtypes.GenerateContentConfig(
                system_instruction = system_prompt,
                temperature        = 0.7,
                max_output_tokens  = 1024,
            ),
        )
        return {"response": response.text}
    except HTTPException:
        raise
    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err or "invalid" in err.lower():
            raise HTTPException(401, "API key de Gemini inválida. Verifica tu clave en aistudio.google.com")
        if "quota" in err.lower() or "429" in err:
            raise HTTPException(429, "Límite de uso de Gemini alcanzado. Intenta en unos minutos.")
        raise HTTPException(500, f"Error de Gemini: {err[:200]}")


# ── Frontend ──────────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")
