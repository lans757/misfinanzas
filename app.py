from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, text, func
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
import bcrypt as _bcrypt
from jose import JWTError, jwt
from google import genai
from google.genai import types as gtypes
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from typing import Literal
import httpx
import asyncio
import secrets
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from typing import Optional, List

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── Clave secreta persistente ─────────────────────────────────────────────────
_KEY_FILE = ".secret_key"
if os.path.exists(_KEY_FILE):
    with open(_KEY_FILE) as f:
        SECRET_KEY = f.read().strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    with open(_KEY_FILE, "w") as f:
        f.write(SECRET_KEY)

ALGORITHM        = "HS256"
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
# ── Detecta automáticamente SQLite (local) o PostgreSQL (Render/Supabase/Neon) ────
_RAW_DB_URL = os.environ.get("DATABASE_URL", "sqlite:///./finanzas.db")

# Render/Heroku/Neon entregan "postgres://..." pero SQLAlchemy 2.x requiere "postgresql://"
if _RAW_DB_URL.startswith("postgres://"):
    _RAW_DB_URL = _RAW_DB_URL.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _RAW_DB_URL
_is_sqlite   = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__   = "users"
    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(150), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at      = Column(DateTime, default=datetime.now)


class Transaction(Base):
    __tablename__        = "transactions"
    id                   = Column(Integer, primary_key=True, index=True)
    user_id              = Column(Integer, nullable=True)   # FK a users.id
    date                 = Column(DateTime, default=datetime.now)
    description          = Column(String(500), nullable=False)
    category             = Column(String(100), nullable=False)
    type                 = Column(String(20), nullable=False)   # ingreso | gasto
    amount               = Column(Float, nullable=False)
    currency             = Column(String(10), nullable=False, default="VES")
    payment_method       = Column(String(100), nullable=True)
    exchange_rate_bcv    = Column(Float, nullable=True)
    exchange_rate_binance= Column(Float, nullable=True)
    amount_ves           = Column(Float, nullable=False)
    amount_usd           = Column(Float, nullable=True)
    amount_usdt          = Column(Float, nullable=True)
    notes                = Column(Text, nullable=True)


Base.metadata.create_all(bind=engine)

# ── Migración: agregar user_id si no existe (solo SQLite) ────────────────────
from sqlalchemy.exc import OperationalError
if _is_sqlite:
    with engine.connect() as _conn:
        try:
            _conn.execute(text("ALTER TABLE transactions ADD COLUMN user_id INTEGER"))
            _conn.commit()
        except OperationalError as e:
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Utilidades de autenticación ───────────────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


# CORREGIDO: datetime.utcnow() -> datetime.now(timezone.utc)
def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: str    = Depends(oauth2_scheme),
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
    description:           str
    category:              str
    # CORREGIDO: Literal valida que solo sean "ingreso" o "gasto"
    type:                  Literal["ingreso", "gasto"]
    amount:                float
    currency:              str = "VES"
    payment_method:        Optional[str]      = None
    exchange_rate_bcv:     Optional[float]    = None
    exchange_rate_binance: Optional[float]    = None
    notes:                 Optional[str]      = None
    date:                  Optional[datetime] = None


# NUEVO: Schema para editar transacciones (PUT)
class TransactionUpdate(BaseModel):
    description:           Optional[str]      = None
    category:              Optional[str]      = None
    type:                  Optional[Literal["ingreso", "gasto"]] = None
    amount:                Optional[float]    = None
    currency:              Optional[str]      = None
    payment_method:        Optional[str]      = None
    exchange_rate_bcv:     Optional[float]    = None
    exchange_rate_binance: Optional[float]    = None
    notes:                 Optional[str]      = None
    date:                  Optional[datetime] = None


class TransactionOut(BaseModel):
    id:                    int
    date:                  datetime
    description:           str
    category:              str
    type:                  str
    amount:                float
    currency:              str
    payment_method:        Optional[str]
    exchange_rate_bcv:     Optional[float]
    exchange_rate_binance: Optional[float]
    amount_ves:            float
    amount_usd:            Optional[float]
    amount_usdt:           Optional[float]
    notes:                 Optional[str]
    model_config = {"from_attributes": True}


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="MisFinanzas")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/api/auth/register", status_code=201)
# CORREGIDO: rate limit — máx 5 registros por minuto por IP
@limiter.limit("5/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
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
        "token_type":   "bearer",
        "username":     user.username,
    }


@app.post("/api/auth/login")
# CORREGIDO: rate limit — máx 10 intentos por minuto por IP (anti fuerza bruta)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    return {
        "access_token": create_token(user.username),
        "token_type":   "bearer",
        "username":     user.username,
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


# NUEVO: endpoint PUT para editar transacciones
@app.put("/api/transactions/{tid}", response_model=TransactionOut)
def update_transaction(
    tid:          int,
    body:         TransactionUpdate,
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

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(t, field, value)

    # Recalcular montos si cambiaron campos relevantes
    currency = t.currency
    amount   = t.amount
    bcv      = t.exchange_rate_bcv
    binance  = t.exchange_rate_binance

    if currency == "USD" and bcv:
        t.amount_ves  = amount * bcv
        t.amount_usd  = amount
        t.amount_usdt = t.amount_ves / binance if binance else None
    elif currency == "USDT" and binance:
        t.amount_ves  = amount * binance
        t.amount_usdt = amount
        t.amount_usd  = t.amount_ves / bcv if bcv else None
    else:
        t.amount_ves  = amount
        t.amount_usd  = amount / bcv if bcv else None
        t.amount_usdt = amount / binance if binance else None

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


# CORREGIDO: get_summary usa func.sum() en SQL, no Python en memoria
@app.get("/api/summary")
def get_summary(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    uid = current_user.id
    now = datetime.now()

    def q_sum(type_: str, col=Transaction.amount_ves):
        return db.query(func.coalesce(func.sum(col), 0.0)) \
                 .filter(Transaction.user_id == uid, Transaction.type == type_) \
                 .scalar()

    total_ingresos = q_sum("ingreso")
    total_gastos   = q_sum("gasto")

    usdt_ingresos = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "ingreso", Transaction.currency == "USDT").scalar()
    usdt_gastos   = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto",   Transaction.currency == "USDT").scalar()

    monthly_ingresos = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "ingreso",
                func.strftime("%Y-%m", Transaction.date) == now.strftime("%Y-%m")).scalar()
    monthly_gastos   = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto",
                func.strftime("%Y-%m", Transaction.date) == now.strftime("%Y-%m")).scalar()

    # Categorías: solo gastos, agrupados en SQL
    cat_rows = db.query(Transaction.category, func.sum(Transaction.amount_ves)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto") \
        .group_by(Transaction.category).all()
    categories = {row[0]: row[1] for row in cat_rows}

    return {
        "total_ingresos_ves": total_ingresos,
        "total_gastos_ves":   total_gastos,
        "saldo_ves":          total_ingresos - total_gastos,
        "usdt_balance":       usdt_ingresos - usdt_gastos,
        "monthly_ingresos":   monthly_ingresos,
        "monthly_gastos":     monthly_gastos,
        "categories":         categories,
    }


# CORREGIDO: get_monthly_flow también usa SQL, no Python en memoria
@app.get("/api/monthly-flow")
def get_monthly_flow(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    uid = current_user.id
    rows = db.query(
        func.strftime("%Y-%m", Transaction.date).label("month"),
        Transaction.type,
        func.sum(Transaction.amount_ves).label("total"),
    ).filter(Transaction.user_id == uid) \
     .group_by("month", Transaction.type) \
     .order_by("month") \
     .all()

    monthly: dict = {}
    for month, type_, total in rows:
        if month not in monthly:
            monthly[month] = {"ingresos": 0.0, "gastos": 0.0}
        if type_ == "ingreso":
            monthly[month]["ingresos"] = round(total, 2)
        else:
            monthly[month]["gastos"]   = round(total, 2)

    sorted_months = sorted(monthly.items())[-6:]
    return {
        "labels":   [m[0] for m in sorted_months],
        "ingresos": [m[1]["ingresos"] for m in sorted_months],
        "gastos":   [m[1]["gastos"]   for m in sorted_months],
    }


# ── Asistente IA (Gemini) ─────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role:    str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class GeminiKeyRequest(BaseModel):
    api_key: str


# CORREGIDO: _build_system_prompt recibe datos pre-calculados, no filas brutas
def _build_system_prompt(username: str, summary: dict, last_txns: list, rates: dict) -> str:
    saldo      = summary["saldo_ves"]
    bcv_rate   = rates.get("bcv")
    saldo_usd  = f"${saldo/bcv_rate:.2f}" if bcv_rate else "N/A"
    usdt_bal   = summary["usdt_balance"]
    binance_r  = rates.get("binance_p2p")
    usdt_en_bs = f"Bs {usdt_bal*binance_r:,.2f}" if binance_r else "N/A"

    now = datetime.now()

    cats_str = "\n".join(
        f"  • {k}: Bs {v:,.2f}"
        for k, v in sorted(summary["categories"].items(), key=lambda x: -x[1])[:8]
    ) or "  Sin datos"

    # CORREGIDO: variable 'history' eliminada (era código muerto); se usa 'contents' directamente
    txns_str = "\n".join(
        f"  {'↑' if t['type']=='ingreso' else '↓'} {t['date']} | {t['category']} | {t['description']} | Bs {t['amount_ves']:,.2f}"
        for t in last_txns
    ) or "  Sin transacciones"

    return f"""Eres un asistente financiero personal inteligente y amigable, especializado en la economía venezolana.
Ayudas al usuario "{username}" a entender y mejorar sus finanzas personales en bolívares (VES), dólares (USD) y USDT.

━━━ DATOS FINANCIEROS ACTUALES DE {username.upper()} ━━━

💰 RESUMEN GENERAL:
  • Saldo total: Bs {saldo:,.2f} ({saldo_usd} al BCV)
  • Total ingresos históricos: Bs {summary['total_ingresos_ves']:,.2f}
  • Total gastos históricos: Bs {summary['total_gastos_ves']:,.2f}
  • Saldo USDT en Binance: {usdt_bal:.4f} USDT ({usdt_en_bs})

📅 ESTE MES ({now.strftime('%B %Y')}):
  • Ingresos: Bs {summary['monthly_ingresos']:,.2f}
  • Gastos: Bs {summary['monthly_gastos']:,.2f}
  • Balance del mes: Bs {summary['monthly_ingresos'] - summary['monthly_gastos']:,.2f}

💱 TASAS DE CAMBIO ACTUALES:
  • Dólar BCV oficial: Bs {bcv_rate or 'No disponible'}
  • USDT Binance P2P: Bs {binance_r or 'No disponible'}

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

    # CORREGIDO: obtener datos financieros via SQL (no cargar todas las filas)
    uid = current_user.id

    def q_sum(type_: str, col=Transaction.amount_ves):
        return db.query(func.coalesce(func.sum(col), 0.0)) \
                 .filter(Transaction.user_id == uid, Transaction.type == type_).scalar()

    now = datetime.now()
    usdt_i = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "ingreso", Transaction.currency == "USDT").scalar()
    usdt_g = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto",   Transaction.currency == "USDT").scalar()
    m_i = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "ingreso",
                func.strftime("%Y-%m", Transaction.date) == now.strftime("%Y-%m")).scalar()
    m_g = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto",
                func.strftime("%Y-%m", Transaction.date) == now.strftime("%Y-%m")).scalar()
    cat_rows = db.query(Transaction.category, func.sum(Transaction.amount_ves)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto") \
        .group_by(Transaction.category).all()

    summary = {
        "total_ingresos_ves": q_sum("ingreso"),
        "total_gastos_ves":   q_sum("gasto"),
        "saldo_ves":          q_sum("ingreso") - q_sum("gasto"),
        "usdt_balance":       usdt_i - usdt_g,
        "monthly_ingresos":   m_i,
        "monthly_gastos":     m_g,
        "categories":         {r[0]: r[1] for r in cat_rows},
    }

    last_txns_raw = db.query(Transaction) \
        .filter(Transaction.user_id == uid) \
        .order_by(Transaction.date.desc()).limit(10).all()
    last_txns = [
        {"type": t.type, "date": t.date.strftime("%d/%m"),
         "category": t.category, "description": t.description, "amount_ves": t.amount_ves}
        for t in last_txns_raw
    ]

    bcv, binance = await asyncio.gather(fetch_bcv_rate(), fetch_binance_p2p_rate())
    rates = {"bcv": bcv, "binance_p2p": binance}

    system_prompt = _build_system_prompt(current_user.username, summary, last_txns, rates)

    try:
        client   = _get_genai_client()
        # CORREGIDO: variable 'history' (código muerto) eliminada, se usa 'contents' directamente
        contents = []
        for msg in body.messages[:-1]:
            contents.append(gtypes.Content(
                role  = "model" if msg.role == "assistant" else "user",
                parts = [gtypes.Part(text=msg.content)],
            ))
        contents.append(gtypes.Content(
            role  = "user",
            parts = [gtypes.Part(text=body.messages[-1].content)],
        ))

        response = client.models.generate_content(
            model    = "gemini-2.0-flash",
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
