-- ============================================================
-- MisFinanzas — Schema SQL
-- Compatible con SQLite (producción local) y PostgreSQL (Render/Supabase)
-- ============================================================

-- ── Tabla de usuarios ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,   -- PostgreSQL: SERIAL PRIMARY KEY
    username        TEXT    NOT NULL UNIQUE,
    hashed_password TEXT    NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_users_username ON users (username);
CREATE INDEX IF NOT EXISTS ix_users_id       ON users (id);

-- ── Tabla de transacciones ───────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,  -- PostgreSQL: SERIAL PRIMARY KEY
    user_id               INTEGER REFERENCES users(id) ON DELETE CASCADE,
    date                  DATETIME DEFAULT CURRENT_TIMESTAMP,
    description           TEXT    NOT NULL,
    category              TEXT    NOT NULL,
    type                  TEXT    NOT NULL CHECK (type IN ('ingreso', 'gasto')),
    amount                REAL    NOT NULL,
    currency              TEXT    NOT NULL DEFAULT 'VES' CHECK (currency IN ('VES', 'USD', 'USDT')),
    payment_method        TEXT,
    exchange_rate_bcv     REAL,
    exchange_rate_binance REAL,
    amount_ves            REAL    NOT NULL,
    amount_usd            REAL,
    amount_usdt           REAL,
    notes                 TEXT
);

CREATE INDEX IF NOT EXISTS ix_transactions_id      ON transactions (id);
CREATE INDEX IF NOT EXISTS ix_transactions_user_id ON transactions (user_id);
CREATE INDEX IF NOT EXISTS ix_transactions_date    ON transactions (date);
CREATE INDEX IF NOT EXISTS ix_transactions_type    ON transactions (type);

-- ============================================================
-- Datos de ejemplo (opcional — eliminar en producción)
-- ============================================================

-- Usuario demo: password = "demo123"
INSERT OR IGNORE INTO users (id, username, hashed_password, created_at) VALUES (
    1,
    'demo',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',
    CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO transactions
    (user_id, date, description, category, type, amount, currency,
     exchange_rate_bcv, amount_ves, amount_usd, notes)
VALUES
    (1, date('now','-5 days'), 'Sueldo mayo',       'Salario',    'ingreso', 200.00, 'USD', 40.50, 8100.00, 200.00, 'Pago mensual'),
    (1, date('now','-4 days'), 'Mercado semana',     'Alimentación','gasto',  2500.00,'VES', 40.50,  2500.00,  61.73, NULL),
    (1, date('now','-3 days'), 'Recarga saldo',      'Transporte', 'gasto',    800.00,'VES', 40.50,   800.00,  19.75, NULL),
    (1, date('now','-2 days'), 'Internet mensual',   'Servicios',  'gasto',   1200.00,'VES', 40.50,  1200.00,  29.63, 'Cantv'),
    (1, date('now','-1 days'), 'Freelance diseño',   'Freelance',  'ingreso',  50.00, 'USD', 40.50,  2025.00,  50.00, 'Logo cliente'),
    (1, date('now'),           'Farmacia',           'Salud',      'gasto',    350.00,'VES', 40.50,   350.00,   8.64, NULL);

-- ============================================================
-- Notas de migración para PostgreSQL
-- ============================================================
-- 1. Reemplazar INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
-- 2. Reemplazar REAL → NUMERIC(18,4)
-- 3. Reemplazar DATETIME → TIMESTAMP WITH TIME ZONE
-- 4. Reemplazar OR IGNORE → ON CONFLICT DO NOTHING
-- 5. Cambiar DATABASE_URL en app.py:
--    postgresql://usuario:password@host:5432/misfinanzas
-- ============================================================
