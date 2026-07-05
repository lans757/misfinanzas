from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
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
import csv
import io
import secrets
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from typing import Optional, List
import calendar as _cal

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

ALGORITHM         = "HS256"
TOKEN_EXPIRE_DAYS = 30

# ── Gemini API Key ────────────────────────────────────────────────────────────
def _load_env():
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
ADMIN_USERNAME  = os.environ.get("ADMIN_USERNAME", "admin").strip().lower()


def _save_gemini_key(key: str):
    global GEMINI_API_KEY
    # En producción (DATABASE_URL externo) no escribir al disco
    if not os.environ.get("DATABASE_URL"):
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
_RAW_DB_URL = os.environ.get("DATABASE_URL", "sqlite:///./finanzas.db")

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


def month_label(col):
    """Expresión YYYY-MM compatible con SQLite y PostgreSQL."""
    if _is_sqlite:
        return func.strftime("%Y-%m", col)
    return func.to_char(col, "YYYY-MM")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__   = "users"
    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(150), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at      = Column(DateTime, default=datetime.now)
    is_admin        = Column(Integer, default=0)


class Transaction(Base):
    __tablename__         = "transactions"
    id                    = Column(Integer, primary_key=True, index=True)
    user_id               = Column(Integer, nullable=True)
    date                  = Column(DateTime, default=datetime.now)
    description           = Column(String(500), nullable=False)
    category              = Column(String(100), nullable=False)
    type                  = Column(String(20), nullable=False)
    amount                = Column(Float, nullable=False)
    currency              = Column(String(10), nullable=False, default="VES")
    payment_method        = Column(String(100), nullable=True)
    exchange_rate_bcv     = Column(Float, nullable=True)
    exchange_rate_binance = Column(Float, nullable=True)
    amount_ves            = Column(Float, nullable=False)
    amount_usd            = Column(Float, nullable=True)
    amount_usdt           = Column(Float, nullable=True)
    notes                 = Column(Text, nullable=True)
    tags                  = Column(String(500), nullable=True)


class Goal(Base):
    __tablename__ = "goals"
    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, nullable=False, index=True)
    name          = Column(String(200), nullable=False)
    target_usdt   = Column(Float, nullable=False)
    notes         = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=datetime.now)


class RateHistory(Base):
    __tablename__ = "rate_history"
    id            = Column(Integer, primary_key=True, index=True)
    date          = Column(DateTime, default=datetime.now, index=True)
    bcv           = Column(Float, nullable=True)
    binance_p2p   = Column(Float, nullable=True)


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"
    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, nullable=False, index=True)
    category      = Column(String(100), nullable=False)
    limit_ves     = Column(Float, nullable=False)
    active        = Column(Integer, default=1)


class CasheaPayment(Base):
    __tablename__ = "cashea_payments"
    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, nullable=False, index=True)
    due_date    = Column(DateTime, nullable=False, index=True)
    amount_usd  = Column(Float, nullable=False)
    description = Column(String(200), nullable=True)
    paid        = Column(Integer, default=0)
    created_at  = Column(DateTime, default=datetime.now)


class Feedback(Base):
    __tablename__ = "feedback"
    id          = Column(Integer, primary_key=True, index=True)
    type        = Column(String(50), nullable=False)
    name        = Column(String(150), nullable=True)
    description = Column(Text, nullable=False)
    image_data  = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.now)


Base.metadata.create_all(bind=engine)

# ── Migraciones SQLite: columnas nuevas en tablas existentes ──────────────────
from sqlalchemy.exc import OperationalError
if _is_sqlite:
    with engine.connect() as _conn:
        for _stmt in [
            "ALTER TABLE transactions ADD COLUMN user_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN tags TEXT",
            "ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0",
        ]:
            try:
                _conn.execute(text(_stmt))
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


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: str     = Depends(oauth2_scheme),
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


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(403, "Acceso restringido a administradores")
    return current_user


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
    type:                  Literal["ingreso", "gasto"]
    amount:                float
    currency:              str            = "VES"
    payment_method:        Optional[str]      = None
    exchange_rate_bcv:     Optional[float]    = None
    exchange_rate_binance: Optional[float]    = None
    notes:                 Optional[str]      = None
    date:                  Optional[datetime] = None
    tags:                  Optional[str]      = None


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
    tags:                  Optional[str]      = None


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
    tags:                  Optional[str]
    model_config = {"from_attributes": True}


class GoalCreate(BaseModel):
    name:        str
    target_usdt: float
    notes:       Optional[str] = None


class GoalOut(BaseModel):
    id:          int
    name:        str
    target_usdt: float
    notes:       Optional[str]
    created_at:  datetime
    model_config = {"from_attributes": True}


class BudgetAlertCreate(BaseModel):
    category:  str
    limit_ves: float


class BudgetAlertOut(BaseModel):
    id:        int
    category:  str
    limit_ves: float
    active:    int
    model_config = {"from_attributes": True}


class CasheaPaymentCreate(BaseModel):
    due_date:    datetime
    amount_usd:  float
    description: Optional[str] = None


class CasheaPaymentOut(BaseModel):
    id:          int
    due_date:    datetime
    amount_usd:  float
    description: Optional[str]
    paid:        int
    created_at:  datetime
    model_config = {"from_attributes": True}


class FeedbackIn(BaseModel):
    type:        str
    name:        Optional[str] = None
    description: str
    image_data:  Optional[str] = None


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="MisFinanzas")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/api/auth/register", status_code=201)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    username = body.username.strip().lower()
    if len(username) < 3:
        raise HTTPException(400, "El usuario debe tener mínimo 3 caracteres")
    if len(body.password) < 6:
        raise HTTPException(400, "La contraseña debe tener mínimo 6 caracteres")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(400, "Ese nombre de usuario ya está en uso")
    user = User(
        username=username,
        hashed_password=hash_password(body.password),
        is_admin=1 if username == ADMIN_USERNAME else 0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "access_token": create_token(user.username),
        "token_type":   "bearer",
        "username":     user.username,
    }


@app.post("/api/auth/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    if user.username == ADMIN_USERNAME and not user.is_admin:
        user.is_admin = 1
        db.commit()
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
        "is_admin":   bool(current_user.is_admin),
    }


# ── Tasas (pública) ───────────────────────────────────────────────────────────
@app.get("/api/rates")
async def get_rates(db: Session = Depends(get_db)):
    bcv, binance = await asyncio.gather(fetch_bcv_rate(), fetch_binance_p2p_rate())
    if bcv or binance:
        db.add(RateHistory(bcv=bcv, binance_p2p=binance))
        db.commit()
    return {"bcv": bcv, "binance_p2p": binance, "timestamp": datetime.now().isoformat()}


# ── Transacciones (protegidas) ────────────────────────────────────────────────
@app.get("/api/transactions", response_model=List[TransactionOut])
def list_transactions(
    skip:         int     = Query(0, ge=0),
    limit:        int     = Query(500, ge=1, le=2000),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    return (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .order_by(Transaction.date.desc())
        .offset(skip).limit(limit)
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
        user_id               = current_user.id,
        date                  = body.date or datetime.now(),
        description           = body.description,
        category              = body.category,
        type                  = body.type,
        amount                = body.amount,
        currency              = body.currency,
        payment_method        = body.payment_method,
        exchange_rate_bcv     = body.exchange_rate_bcv,
        exchange_rate_binance = body.exchange_rate_binance,
        amount_ves            = amount_ves,
        amount_usd            = amount_usd,
        amount_usdt           = amount_usdt,
        notes                 = body.notes,
        tags                  = body.tags,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


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


@app.get("/api/summary")
def get_summary(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    uid       = current_user.id
    cur_month = datetime.now().strftime("%Y-%m")

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
                month_label(Transaction.date) == cur_month).scalar()
    monthly_gastos   = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto",
                month_label(Transaction.date) == cur_month).scalar()

    cat_rows = db.query(Transaction.category, func.sum(Transaction.amount_ves)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto") \
        .group_by(Transaction.category).all()

    return {
        "total_ingresos_ves": total_ingresos,
        "total_gastos_ves":   total_gastos,
        "saldo_ves":          total_ingresos - total_gastos,
        "usdt_balance":       usdt_ingresos - usdt_gastos,
        "monthly_ingresos":   monthly_ingresos,
        "monthly_gastos":     monthly_gastos,
        "categories":         {row[0]: row[1] for row in cat_rows},
    }


@app.get("/api/monthly-flow")
def get_monthly_flow(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    uid  = current_user.id
    rows = db.query(
        month_label(Transaction.date).label("month"),
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
    role:    str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class GeminiKeyRequest(BaseModel):
    api_key: str


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

    uid       = current_user.id
    cur_month = datetime.now().strftime("%Y-%m")

    total_ingresos = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "ingreso").scalar()
    total_gastos   = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto").scalar()

    usdt_i = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "ingreso", Transaction.currency == "USDT").scalar()
    usdt_g = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto",   Transaction.currency == "USDT").scalar()

    m_i = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "ingreso",
                month_label(Transaction.date) == cur_month).scalar()
    m_g = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto",
                month_label(Transaction.date) == cur_month).scalar()

    cat_rows = db.query(Transaction.category, func.sum(Transaction.amount_ves)) \
        .filter(Transaction.user_id == uid, Transaction.type == "gasto") \
        .group_by(Transaction.category).all()

    summary = {
        "total_ingresos_ves": total_ingresos,
        "total_gastos_ves":   total_gastos,
        "saldo_ves":          total_ingresos - total_gastos,
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
    rates        = {"bcv": bcv, "binance_p2p": binance}
    system_prompt = _build_system_prompt(current_user.username, summary, last_txns, rates)

    try:
        client   = _get_genai_client()
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


# ── Metas de ahorro ───────────────────────────────────────────────────────────
@app.get("/api/goals", response_model=List[GoalOut])
def list_goals(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Goal).filter(Goal.user_id == current_user.id).all()


@app.post("/api/goals", response_model=GoalOut, status_code=201)
def create_goal(body: GoalCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    g = Goal(user_id=current_user.id, name=body.name, target_usdt=body.target_usdt, notes=body.notes)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


@app.delete("/api/goals/{gid}")
def delete_goal(gid: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    g = db.query(Goal).filter(Goal.id == gid, Goal.user_id == current_user.id).first()
    if not g:
        raise HTTPException(404, "Meta no encontrada")
    db.delete(g)
    db.commit()
    return {"ok": True}


# ── Historial de tasas ────────────────────────────────────────────────────────
@app.get("/api/rates/history")
def get_rates_history(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(RateHistory).order_by(RateHistory.date.desc()).limit(30).all()
    return [
        {"date": r.date.isoformat(), "bcv": r.bcv, "binance_p2p": r.binance_p2p}
        for r in reversed(rows)
    ]


# ── Alertas de presupuesto ────────────────────────────────────────────────────
@app.get("/api/budget-alerts", response_model=List[BudgetAlertOut])
def list_budget_alerts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(BudgetAlert).filter(BudgetAlert.user_id == current_user.id).all()


@app.get("/api/budget-alerts/check")
def check_budget_alerts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    uid       = current_user.id
    cur_month = datetime.now().strftime("%Y-%m")
    alerts    = db.query(BudgetAlert).filter(BudgetAlert.user_id == uid, BudgetAlert.active == 1).all()
    results   = []
    for alert in alerts:
        spent = db.query(func.coalesce(func.sum(Transaction.amount_ves), 0.0)) \
            .filter(
                Transaction.user_id == uid,
                Transaction.type    == "gasto",
                Transaction.category == alert.category,
                month_label(Transaction.date) == cur_month,
            ).scalar()
        results.append({
            "id":        alert.id,
            "category":  alert.category,
            "limit_ves": alert.limit_ves,
            "spent_ves": spent,
            "triggered": spent >= alert.limit_ves,
            "pct":       round(spent / alert.limit_ves * 100, 1) if alert.limit_ves else 0,
        })
    return results


@app.post("/api/budget-alerts", response_model=BudgetAlertOut, status_code=201)
def create_budget_alert(body: BudgetAlertCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    a = BudgetAlert(user_id=current_user.id, category=body.category, limit_ves=body.limit_ves)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@app.delete("/api/budget-alerts/{aid}")
def delete_budget_alert(aid: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    a = db.query(BudgetAlert).filter(BudgetAlert.id == aid, BudgetAlert.user_id == current_user.id).first()
    if not a:
        raise HTTPException(404, "Alerta no encontrada")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ── Exportar a CSV ────────────────────────────────────────────────────────────
@app.get("/api/export/csv")
def export_csv(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    txns = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .order_by(Transaction.date.desc())
        .all()
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Fecha", "Tipo", "Categoría", "Descripción",
        "Monto", "Moneda", "Monto Bs", "Monto USD", "Monto USDT",
        "Método de pago", "Tasa BCV", "Tasa Binance", "Notas", "Tags",
    ])
    for t in txns:
        writer.writerow([
            t.date.strftime("%Y-%m-%d %H:%M"), t.type, t.category, t.description,
            t.amount, t.currency, t.amount_ves, t.amount_usd, t.amount_usdt,
            t.payment_method, t.exchange_rate_bcv, t.exchange_rate_binance, t.notes, t.tags,
        ])
    filename = f"misfinanzas_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter(["﻿" + output.getvalue()]),  # BOM para que Excel abra correctamente
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Feedback ──────────────────────────────────────────────────────────────────
@app.post("/api/feedback", status_code=201)
def submit_feedback(body: FeedbackIn, db: Session = Depends(get_db)):
    fb = Feedback(
        type=body.type,
        name=body.name,
        description=body.description,
        image_data=body.image_data,
    )
    db.add(fb)
    db.commit()
    return {"ok": True}


@app.get("/api/feedback")
def get_feedback(db: Session = Depends(get_db)):
    items = db.query(Feedback).order_by(Feedback.created_at.desc()).all()
    return [
        {
            "id": f.id,
            "type": f.type,
            "name": f.name or "Anónimo",
            "description": f.description,
            "has_image": bool(f.image_data),
            "image_data": f.image_data,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in items
    ]


# ── Panel de administración ───────────────────────────────────────────────────
@app.get("/api/admin/feedback")
def admin_list_feedback(
    db:    Session = Depends(get_db),
    _admin: User  = Depends(get_current_admin),
):
    items = db.query(Feedback).order_by(Feedback.created_at.desc()).all()
    return [
        {
            "id":          f.id,
            "type":        f.type,
            "name":        f.name or "Anónimo",
            "description": f.description,
            "image_data":  f.image_data,
            "created_at":  f.created_at.isoformat() if f.created_at else None,
        }
        for f in items
    ]


@app.delete("/api/admin/feedback/{feedback_id}", status_code=200)
def admin_delete_feedback(
    feedback_id: int,
    db:    Session = Depends(get_db),
    _admin: User  = Depends(get_current_admin),
):
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(404, "Reporte no encontrado")
    db.delete(fb)
    db.commit()
    return {"ok": True}


@app.get("/api/admin/users")
def admin_list_users(
    db:    Session = Depends(get_db),
    _admin: User  = Depends(get_current_admin),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id":         u.id,
            "username":   u.username,
            "is_admin":   bool(u.is_admin),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@app.delete("/api/admin/users/{user_id}", status_code=200)
def admin_delete_user(
    user_id: int,
    db:     Session = Depends(get_db),
    admin:  User   = Depends(get_current_admin),
):
    if user_id == admin.id:
        raise HTTPException(400, "No puedes eliminarte a ti mismo")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    db.delete(user)
    db.commit()
    return {"ok": True}


# ── Cashea ───────────────────────────────────────────────────────────────────
@app.get("/api/cashea", response_model=List[CasheaPaymentOut])
def list_cashea(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(CasheaPayment)
        .filter(CasheaPayment.user_id == current_user.id)
        .order_by(CasheaPayment.due_date.asc())
        .all()
    )


@app.post("/api/cashea", response_model=CasheaPaymentOut, status_code=201)
def create_cashea(body: CasheaPaymentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    c = CasheaPayment(
        user_id=current_user.id,
        due_date=body.due_date,
        amount_usd=body.amount_usd,
        description=body.description,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


@app.put("/api/cashea/{cid}/toggle")
def toggle_cashea(cid: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    c = db.query(CasheaPayment).filter(CasheaPayment.id == cid, CasheaPayment.user_id == current_user.id).first()
    if not c:
        raise HTTPException(404, "Pago Cashea no encontrado")
    c.paid = 0 if c.paid else 1
    db.commit()
    return {"ok": True, "paid": bool(c.paid)}


@app.delete("/api/cashea/{cid}")
def delete_cashea(cid: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    c = db.query(CasheaPayment).filter(CasheaPayment.id == cid, CasheaPayment.user_id == current_user.id).first()
    if not c:
        raise HTTPException(404, "Pago Cashea no encontrado")
    db.delete(c); db.commit()
    return {"ok": True}


# ── Calendario ───────────────────────────────────────────────────────────────
@app.get("/api/calendar/{year}/{month}")
def get_calendar(
    year:         int,
    month:        int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    uid = current_user.id
    _, days_in_month = _cal.monthrange(year, month)
    start = datetime(year, month, 1)
    end   = datetime(year, month, days_in_month, 23, 59, 59)

    txns = db.query(Transaction).filter(
        Transaction.user_id == uid,
        Transaction.date    >= start,
        Transaction.date    <= end,
    ).all()

    days: dict = {}
    for t in txns:
        key = str(t.date.day)
        if key not in days:
            days[key] = {"ingresos": 0.0, "gastos": 0.0, "bcv": None, "binance_p2p": None, "count": 0}
        if t.type == "ingreso":
            days[key]["ingresos"] += t.amount_ves
        else:
            days[key]["gastos"] += t.amount_ves
        days[key]["count"] += 1
        if days[key]["bcv"] is None and t.exchange_rate_bcv:
            days[key]["bcv"] = t.exchange_rate_bcv
        if days[key]["binance_p2p"] is None and t.exchange_rate_binance:
            days[key]["binance_p2p"] = t.exchange_rate_binance

    for key, d in days.items():
        if d["bcv"] is None or d["binance_p2p"] is None:
            day_num   = int(key)
            day_start = datetime(year, month, day_num)
            day_end   = datetime(year, month, day_num, 23, 59, 59)
            rate = db.query(RateHistory).filter(
                RateHistory.date >= day_start,
                RateHistory.date <= day_end,
            ).first()
            if rate:
                if d["bcv"] is None:         d["bcv"]         = rate.bcv
                if d["binance_p2p"] is None: d["binance_p2p"] = rate.binance_p2p

    # Pagos Cashea del mes
    cashea_rows = db.query(CasheaPayment).filter(
        CasheaPayment.user_id  == uid,
        CasheaPayment.due_date >= start,
        CasheaPayment.due_date <= end,
    ).all()
    for c in cashea_rows:
        key = str(c.due_date.day)
        if key not in days:
            days[key] = {"ingresos": 0.0, "gastos": 0.0, "bcv": None, "binance_p2p": None, "count": 0}
        days[key].setdefault("cashea", [])
        days[key]["cashea"].append({
            "id": c.id, "amount_usd": c.amount_usd,
            "description": c.description, "paid": bool(c.paid),
        })

    return {"year": year, "month": month, "days_in_month": days_in_month, "days": days}


@app.get("/api/calendar/{year}/{month}/{day}")
def get_calendar_day(
    year:         int,
    month:        int,
    day:          int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    uid       = current_user.id
    day_start = datetime(year, month, day)
    day_end   = datetime(year, month, day, 23, 59, 59)

    txns = db.query(Transaction).filter(
        Transaction.user_id == uid,
        Transaction.date    >= day_start,
        Transaction.date    <= day_end,
    ).order_by(Transaction.date.asc()).all()

    rate = db.query(RateHistory).filter(
        RateHistory.date >= day_start,
        RateHistory.date <= day_end,
    ).order_by(RateHistory.date.desc()).first()

    bcv     = rate.bcv         if rate else None
    binance = rate.binance_p2p if rate else None
    for t in txns:
        if bcv     is None and t.exchange_rate_bcv:     bcv     = t.exchange_rate_bcv
        if binance is None and t.exchange_rate_binance: binance = t.exchange_rate_binance

    cashea_rows = db.query(CasheaPayment).filter(
        CasheaPayment.user_id  == uid,
        CasheaPayment.due_date >= day_start,
        CasheaPayment.due_date <= day_end,
    ).all()

    return {
        "transactions": [TransactionOut.model_validate(t).model_dump() for t in txns],
        "bcv":          bcv,
        "binance_p2p":  binance,
        "cashea": [{"id": c.id, "amount_usd": c.amount_usd, "description": c.description, "paid": bool(c.paid)} for c in cashea_rows],
    }


# ── Frontend ──────────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")
