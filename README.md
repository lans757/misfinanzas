# 💰 MisFinanzas

Aplicación web personal para gestionar ingresos y gastos en Venezuela, con soporte para **Bolívares (VES)**, **Dólares (USD)** y **USDT (Binance)**. Incluye tasas de cambio en tiempo real y un asistente de IA con Google Gemini.

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green?logo=fastapi)
![React](https://img.shields.io/badge/React-18-blue?logo=react)
![Tailwind](https://img.shields.io/badge/Tailwind_CSS-3-06B6D4?logo=tailwindcss)
![SQLite](https://img.shields.io/badge/SQLite-local-lightgrey?logo=sqlite)

---

## ✨ Características

- 🔐 **Multi-usuario** — Registro e inicio de sesión con JWT. Cada usuario ve solo sus propios datos.
- 💱 **Tasas en tiempo real** — Dólar BCV oficial y USDT/VES desde Binance P2P.
- 📊 **Dashboard** — Gráfico de flujo mensual y distribución de gastos por categoría.
- 💵 **Multi-moneda** — Registra en VES, USD o USDT con conversión automática.
- 🪙 **Módulo de ahorros** — Saldo USDT con equivalente en Bs y USD en tiempo real.
- 🤖 **Asistente IA** — Google Gemini 1.5 Flash con acceso a tus datos financieros.
- 📱 **Responsive** — Funciona en escritorio y móvil.

---

## 🚀 Instalación

### 1. Clona el repositorio
```bash
git clone https://github.com/lans757/misfinanzas.git
cd misfinanzas
```

### 2. Instala las dependencias
```bash
pip3 install -r requirements.txt --break-system-packages
```

### 3. Crea el archivo `.env`
```bash
echo "GEMINI_API_KEY=" > .env
```
> Puedes dejarlo vacío si no vas a usar el asistente IA por ahora.

### 4. Levanta el servidor
```bash
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Abre el navegador
```
http://localhost:8000
```

---

## 🤖 Asistente IA (Google Gemini)

El asistente tiene acceso a todos tus datos financieros y puede responder preguntas como:

- *"¿Cuánto gasté este mes?"*
- *"¿Cómo están mis ahorros en USDT?"*
- *"Dame un consejo de ahorro"*
- *"¿En qué categoría gasto más?"*

### Obtener API Key gratis
1. Ve a [aistudio.google.com](https://aistudio.google.com)
2. Inicia sesión con tu cuenta Google
3. Clic en **Get API Key** → **Create API key**
4. Pégala en el tab **✨ Asistente IA** dentro de la app

> Plan gratuito: **1 millón de tokens/día** — más que suficiente para uso personal.

---

## 🌐 Exponer con ngrok (acceso desde cualquier dispositivo)

```bash
# Terminal 1 — servidor
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000

# Terminal 2 — túnel público
ngrok http 8000
```

---

## 📁 Estructura del proyecto

```
misfinanzas/
├── app.py              # Backend FastAPI + SQLite + Auth + Gemini
├── requirements.txt    # Dependencias Python
├── .env                # API Keys (no se sube al repo)
├── .gitignore
└── static/
    └── index.html      # Frontend React + Tailwind CSS
```

---

## 🔒 Seguridad

| Archivo | ¿Se sube a GitHub? | Descripción |
|---|---|---|
| `.env` | ❌ No | API key de Gemini |
| `.secret_key` | ❌ No | Clave secreta JWT |
| `finanzas.db` | ❌ No | Base de datos local |

---

## 🛠️ Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Base de datos | SQLite + SQLAlchemy |
| Autenticación | JWT (python-jose) + bcrypt (passlib) |
| Frontend | React 18 + Tailwind CSS (CDN) |
| Gráficos | Chart.js |
| IA | Google Gemini 1.5 Flash |
| API BCV | ve.dolarapi.com |
| API Binance | Binance P2P |

---

## 📄 Licencia

MIT — úsalo libremente para uso personal.
