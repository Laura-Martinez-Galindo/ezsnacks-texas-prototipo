"""Conexión con QuickBooks Online (sandbox o producción) usando OAuth 2.0.

- El Client Secret se lee de variables de entorno (archivo .env), nunca del código.
- Los tokens se guardan en tokens.json (excluido de git) y se renuevan solos.
- Basado en la librería oficial de Intuit (intuit-oauth) y en la API v3 de contabilidad.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

load_dotenv()

MINOR_VERSION = "75"  # Intuit trata toda petición como minorversion >= 75
TOKENS_FILE = Path(os.getenv("QBO_TOKENS_FILE", "tokens.json"))
BASE_URLS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}


class QBOError(Exception):
    """Error devuelto por la API de QuickBooks, con el detalle legible."""


def _env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise QBOError(
            f"Falta la variable {name}. Copie .env.example a .env y complételo."
        )
    return value


def nuevo_auth_client() -> AuthClient:
    return AuthClient(
        client_id=_env("QBO_CLIENT_ID"),
        client_secret=_env("QBO_CLIENT_SECRET"),
        redirect_uri=_env("QBO_REDIRECT_URI"),
        environment=os.getenv("QBO_ENVIRONMENT", "sandbox"),
    )


def url_autorizacion(state: str = "ezsnack") -> str:
    """URL de la pantalla de consentimiento de Intuit (solo permiso de contabilidad)."""
    return nuevo_auth_client().get_authorization_url([Scopes.ACCOUNTING], state_token=state)


def _tokens_de(auth: AuthClient) -> dict:
    return {
        "access_token": auth.access_token,
        "refresh_token": auth.refresh_token,
        "realm_id": auth.realm_id,
        "expira_en": time.time() + int(auth.expires_in or 3600) - 60,
    }


def guardar_tokens(auth: AuthClient) -> None:
    TOKENS_FILE.write_text(json.dumps(_tokens_de(auth), indent=2))


def obtener_tokens(code: str, realm_id: str) -> dict:
    """Paso 2 de OAuth: cambia el codigo de autorizacion por tokens y los devuelve."""
    auth = nuevo_auth_client()
    auth.get_bearer_token(code, realm_id=realm_id)
    return _tokens_de(auth)


def cambiar_codigo_por_tokens(code: str, realm_id: str) -> None:
    """Igual que obtener_tokens, pero los guarda en tokens.json (uso local y scripts)."""
    TOKENS_FILE.write_text(json.dumps(obtener_tokens(code, realm_id), indent=2))


def esta_conectado() -> bool:
    return TOKENS_FILE.exists()


def desconectar() -> None:
    if TOKENS_FILE.exists():
        TOKENS_FILE.unlink()


class QBO:
    """Cliente mínimo de la API de contabilidad de QuickBooks Online."""

    def __init__(self, tokens: dict | None = None) -> None:
        """Con tokens: los usa y los deja actualizados en self.tokens (la web los guarda en la sesion).
        Sin tokens: los lee y los guarda en tokens.json (scripts y uso local)."""
        self.en_archivo = tokens is None
        if tokens is None:
            if not TOKENS_FILE.exists():
                raise QBOError("No hay conexión con QuickBooks. Conéctese primero.")
            tokens = json.loads(TOKENS_FILE.read_text())
        self.tokens = dict(tokens)
        self.renovado = False
        env = os.getenv("QBO_ENVIRONMENT", "sandbox")
        self.base = f"{BASE_URLS[env]}/v3/company/{self.tokens['realm_id']}"

    # ---------- tokens ----------
    def _renovar_si_hace_falta(self, forzar: bool = False) -> None:
        if not forzar and time.time() < self.tokens["expira_en"]:
            return
        auth = nuevo_auth_client()
        auth.realm_id = self.tokens["realm_id"]
        auth.refresh(refresh_token=self.tokens["refresh_token"])
        self.tokens = _tokens_de(auth)
        self.renovado = True
        if self.en_archivo:
            TOKENS_FILE.write_text(json.dumps(self.tokens, indent=2))

    # ---------- peticiones ----------
    def _peticion(self, metodo: str, ruta: str, *, params=None, json_body=None, reintento=True):
        self._renovar_si_hace_falta()
        params = {"minorversion": MINOR_VERSION, **(params or {})}
        resp = requests.request(
            metodo,
            f"{self.base}/{ruta}",
            params=params,
            json=json_body,
            headers={
                "Authorization": f"Bearer {self.tokens['access_token']}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        if resp.status_code == 401 and reintento:
            self._renovar_si_hace_falta(forzar=True)
            return self._peticion(metodo, ruta, params=params, json_body=json_body, reintento=False)
        if resp.status_code >= 400:
            try:
                errores = resp.json()["Fault"]["Error"]
                detalle = "; ".join(f"{e.get('Message')}: {e.get('Detail')}" for e in errores)
            except Exception:  # noqa: BLE001
                detalle = resp.text[:500]
            raise QBOError(f"QuickBooks respondió {resp.status_code}: {detalle}")
        return resp.json()

    def query(self, sql: str) -> list[dict]:
        """Ejecuta una consulta y pagina hasta traer todos los registros."""
        entidad = sql.split()[3] if sql.lower().startswith("select") else None
        resultados, inicio, paso = [], 1, 1000
        while True:
            datos = self._peticion(
                "GET", "query", params={"query": f"{sql} STARTPOSITION {inicio} MAXRESULTS {paso}"}
            )
            bloque = datos.get("QueryResponse", {})
            filas = next((v for k, v in bloque.items() if isinstance(v, list)), [])
            resultados.extend(filas)
            if len(filas) < paso:
                return resultados
            inicio += paso

    def crear(self, entidad: str, cuerpo: dict) -> dict:
        datos = self._peticion("POST", entidad.lower(), json_body=cuerpo)
        return datos[entidad]

    def actualizar(self, entidad: str, cuerpo: dict) -> dict:
        """Actualización parcial (sparse). El cuerpo debe incluir Id y SyncToken."""
        datos = self._peticion("POST", entidad.lower(), json_body={**cuerpo, "sparse": True})
        return datos[entidad]

    def borrar(self, entidad: str, id_: str, sync_token: str) -> None:
        """Borra una transacción (facturas, recibos, gastos, pagos...). No sirve para listas."""
        self._peticion(
            "POST", entidad.lower(), params={"operation": "delete"},
            json_body={"Id": id_, "SyncToken": sync_token},
        )

    def inactivar(self, entidad: str, registro: dict) -> None:
        """Clientes, proveedores y productos no se borran: se marcan como inactivos."""
        self.actualizar(entidad, {"Id": registro["Id"], "SyncToken": registro["SyncToken"], "Active": False})

    def info_empresa(self) -> dict:
        realm = self.tokens["realm_id"]
        return self._peticion("GET", f"companyinfo/{realm}")["CompanyInfo"]
