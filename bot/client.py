"""
Cliente HTTP para la API de MisFinanzas.
Cachea el JWT en memoria y lo renueva automáticamente.
"""

import httpx
from datetime import datetime


class MFError(Exception):
    pass


class MisFinanzasClient:
    def __init__(self, base_url: str, username: str, password: str):
        self._base     = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token: str | None = None

    async def _login(self) -> str:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{self._base}/api/login",
                json={"username": self._username, "password": self._password},
                timeout=10,
            )
        if r.status_code != 200:
            raise MFError(f"Login fallido ({r.status_code}): {r.text}")
        self._token = r.json()["access_token"]
        return self._token

    async def _headers(self) -> dict:
        token = self._token or await self._login()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def create_transaction(self, data: dict) -> dict:
        """
        data debe tener: description, amount, currency, type, category,
                         payment_method, date (YYYY-MM-DD), notes (opcional)
        """
        date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
        # La API espera datetime ISO
        date_iso = f"{date_str}T12:00:00"

        payload = {
            "description":    data["description"],
            "amount":         float(data["amount"]),
            "currency":       data.get("currency", "VES"),
            "type":           data.get("type", "gasto"),
            "category":       data.get("category", "Otro gasto"),
            "payment_method": data.get("payment_method", "Efectivo"),
            "date":           date_iso,
        }
        if data.get("notes"):
            payload["notes"] = data["notes"]

        headers = await self._headers()

        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{self._base}/api/transactions",
                json=payload,
                headers=headers,
                timeout=10,
            )

        if r.status_code == 401:
            # Token expirado → renovar y reintentar una vez
            self._token = None
            headers = await self._headers()
            async with httpx.AsyncClient() as http:
                r = await http.post(
                    f"{self._base}/api/transactions",
                    json=payload,
                    headers=headers,
                    timeout=10,
                )

        if r.status_code not in (200, 201):
            raise MFError(f"Error {r.status_code}: {r.text}")

        return r.json()
