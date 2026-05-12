-- =====================================================
-- MisFinanzas - Script de base de datos para XAMPP
-- Ejecutar en phpMyAdmin o MySQL Workbench
-- =====================================================

CREATE DATABASE IF NOT EXISTS misfinanzas
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE misfinanzas;

-- Tabla de usuarios
CREATE TABLE IF NOT EXISTS users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(150) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla de transacciones
CREATE TABLE IF NOT EXISTS transactions (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    user_id               INT,
    date                  DATETIME DEFAULT CURRENT_TIMESTAMP,
    description           VARCHAR(500) NOT NULL,
    category              VARCHAR(100) NOT NULL,
    type                  VARCHAR(20)  NOT NULL,      -- 'ingreso' | 'gasto'
    amount                DOUBLE       NOT NULL,
    currency              VARCHAR(10)  NOT NULL DEFAULT 'VES',
    payment_method        VARCHAR(100),
    exchange_rate_bcv     DOUBLE,
    exchange_rate_binance DOUBLE,
    amount_ves            DOUBLE NOT NULL,
    amount_usd            DOUBLE,
    amount_usdt           DOUBLE,
    notes                 TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_date    (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
