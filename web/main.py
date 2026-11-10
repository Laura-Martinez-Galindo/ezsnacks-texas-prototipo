"""Servidor web de EzSnack Impuestos.

Los archivos que sube cada persona se leen en memoria y se guardan un rato con un codigo,
para recalcular sin volver a subirlos. No se escriben en disco ni en ninguna base de datos.
La conexion opcional con QuickBooks se guarda cifrada en una cookie del navegador.

Local:   uvicorn web.main:app --reload --port 8000
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import secrets
import threading
import time
from datetime import date
from pathlib import Path

import pandas as pd
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parents[1]

from ezsnack import cierre as cie  # noqa: E402
from ezsnack import contabilidad as conta  # noqa: E402
from ezsnack import lectores as lec  # noqa: E402
from ezsnack import libro as lib  # noqa: E402
from ezsnack import maquinas as maq  # noqa: E402
from ezsnack import productos as prod  # noqa: E402
from ezsnack import qbo as qbo_mod  # noqa: E402
from ezsnack import sandbox  # noqa: E402

COOKIE = "ezsnack_qbo"
_secreto = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(_secreto.encode()).digest()))
SEGURO = os.getenv("QBO_REDIRECT_URI", "").startswith("https://")
QBO_LISTO = bool(os.getenv("QBO_CLIENT_ID") and os.getenv("QBO_CLIENT_SECRET"))
EJEMPLOS = RAIZ / "datos_prueba"
# Cifras reales de un mes para comparar. Son datos de la empresa: no van en el repositorio,
# se leen de la variable VERIFICACION_JSON o de config/verificacion.json si existe en el equipo.
_verif = os.getenv("VERIFICACION_JSON") or (
    (RAIZ / "config" / "verificacion.json").read_text(encoding="utf-8")
    if (RAIZ / "config" / "verificacion.json").exists() else "{}")
try:
    VERIFICACION = json.loads(_verif)
except ValueError:
    VERIFICACION = {}

app = FastAPI(title="EzSnack Impuestos", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=RAIZ / "web" / "static"), name="static")

# Cierres en memoria: codigo -> archivos ya leidos
CIERRES: dict[str, dict] = {}
_CANDADO = threading.Lock()
VIGENCIA = 3 * 60 * 60


def _guardar(datos: dict) -> str:
    codigo = secrets.token_urlsafe(12)
    with _CANDADO:
        ahora = time.time()
        for k in [k for k, v in CIERRES.items() if ahora - v["creado"] > VIGENCIA]:
            CIERRES.pop(k, None)
        while len(CIERRES) >= 30:
            CIERRES.pop(min(CIERRES, key=lambda k: CIERRES[k]["creado"]))
        CIERRES[codigo] = {**datos, "creado": ahora}
    return codigo


def _cierre(codigo: str) -> dict:
    c = CIERRES.get(codigo)
    if not c:
        raise HTTPException(410, "Los archivos ya no están en memoria. Vuelva a subirlos.")
    return c


# ---------------- sesion de QuickBooks ----------------
def _leer_tokens(request: Request) -> dict | None:
    valor = request.cookies.get(COOKIE)
    if not valor:
        return None
    try:
        return json.loads(FERNET.decrypt(valor.encode()))
    except (InvalidToken, ValueError):
        return None


def _poner_cookie(resp, tokens: dict) -> None:
    resp.set_cookie(COOKIE, FERNET.encrypt(json.dumps(tokens).encode()).decode(),
                    httponly=True, secure=SEGURO, samesite="lax", max_age=60 * 60 * 24 * 90)


@app.exception_handler(qbo_mod.QBOError)
async def _error_qbo(_, exc):
    return JSONResponse({"detail": f"QuickBooks respondió: {exc}"}, status_code=400)


@app.get("/")
def inicio():
    return FileResponse(RAIZ / "web" / "static" / "index.html")


@app.get("/auth/conectar")
def conectar():
    if not QBO_LISTO:
        raise HTTPException(503, "Esta instalación no tiene las llaves de QuickBooks.")
    estado = secrets.token_urlsafe(16)
    resp = RedirectResponse(qbo_mod.url_autorizacion(estado))
    resp.set_cookie("ezsnack_estado", estado, httponly=True, secure=SEGURO, samesite="lax", max_age=600)
    return resp


@app.get("/auth/callback")
def callback(request: Request, code: str = "", realmId: str = "", state: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse("/?conexion=cancelada")
    if state != request.cookies.get("ezsnack_estado"):
        return RedirectResponse("/?conexion=invalida")
    tokens = qbo_mod.obtener_tokens(code, realmId)
    resp = RedirectResponse("/?conexion=ok")
    _poner_cookie(resp, tokens)
    resp.delete_cookie("ezsnack_estado")
    return resp


@app.post("/auth/salir")
def salir():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/api/estado")
def estado(request: Request):
    hoy = date.today()
    previo = date(hoy.year if hoy.month > 1 else hoy.year - 1, hoy.month - 1 or 12, 1)
    datos = {"qbo_disponible": QBO_LISTO, "conectado": False, "empresa": None,
             "entorno": os.getenv("QBO_ENVIRONMENT", "sandbox"), "anio": previo.year, "mes": previo.month,
             "reglas": cie.reglas()}
    tokens = _leer_tokens(request)
    if not tokens:
        return datos
    try:
        qbo = qbo_mod.QBO(tokens)
        datos.update(conectado=True, empresa=qbo.info_empresa().get("CompanyName"))
        resp = JSONResponse(datos)
        if qbo.renovado:
            _poner_cookie(resp, qbo.tokens)
        return resp
    except Exception:  # noqa: BLE001
        return datos


# ---------------- cierre ----------------
def _registros(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _leer_todo(maquinas_src, reportes: list[tuple], pagados_src, mapeos: dict | None = None) -> dict:
    if not reportes:
        raise HTTPException(400, "Suba al menos un reporte de ventas.")
    try:
        lista_maq = maq.leer(*maquinas_src)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    lecturas, sin_leer = [], []
    for src, nombre in reportes:
        try:
            lecturas.append(lec.leer(src, nombre, (mapeos or {}).get(nombre)))
        except lec.FormatoDesconocido as exc:
            sin_leer.append({"archivo": nombre, "error": str(exc), "columnas": exc.columnas, "mapeo": exc.mapeo})
        except Exception as exc:  # noqa: BLE001
            sin_leer.append({"archivo": nombre, "error": f"No se pudo leer: {exc}", "columnas": [], "mapeo": {}})
    if not lecturas:
        return {"lecturas": [], "sin_leer": sin_leer}
    lista_pag = []
    if pagados_src:
        try:
            lista_pag = prod.leer_lista(*pagados_src)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"lecturas": lecturas, "maquinas": lista_maq, "integ": cie.integrar(lecturas, lista_maq),
            "lista_pagados": lista_pag, "sin_leer": sin_leer}


def _resultado(c: dict, anio: int, mes: int, ajustes: dict | None) -> dict:
    res = _calcular(c, anio, mes, ajustes)
    columnas_maq = ["id_maquina", "maquina", "fuente", "locacion", "ciudad", "jurisdiccion", "en_lista",
                    "unidades", "ventas", "exentas", "pagadas", "gravable"]
    return {
        "archivos": [{"archivo": l.archivo, "fuente": l.fuente, "periodo": l.periodo, "leidas": l.leidas,
                      "usadas": int(len(l.filas)), "descartadas": l.descartadas,
                      "efectivo": round(float(l.filas["efectivo"].sum()), 2),
                      "tarjeta": round(float(l.filas["tarjeta"].sum()), 2),
                      "generico": l.generico, "columnas": l.columnas, "mapeo": l.mapeo}
                     for l in c["lecturas"]],
        "sin_leer": c["sin_leer"], "campos": lec.NOMBRES_CAMPOS, "reglas": res["reglas"],
        "lista_pagados": c["lista_pagados"],
        "pasos": res["pasos"], "declaracion": res["declaracion"],
        "maquinas": _registros(res["maquinas"][columnas_maq].round(2)),
        "exentos": _registros(res["exentos"].round(2)),
        "pagados": _registros(res["pagados"].round(2)),
        "revisar": res["revisar"],
        "productos": sorted(c["integ"]["producto"].dropna().unique().tolist(), key=str.lower),
        "verificacion": VERIFICACION.get(f"{anio}-{mes:02d}") if c.get("ejemplo") is False else None,
    }


def _calcular(c: dict, anio: int, mes: int, ajustes: dict | None) -> dict:
    a = cie.Ajustes.de(ajustes)
    a.lista_pagados = c["lista_pagados"]
    return cie.calcular(c["integ"], a, anio, mes)


async def _archivo(u: UploadFile) -> tuple[io.BytesIO, str]:
    return io.BytesIO(await u.read()), u.filename or "archivo.xlsx"


@app.post("/api/cierre/archivos")
async def subir(anio: int, mes: int, maquinas: UploadFile = File(...), reportes: list[UploadFile] = File(...),
                pagados: UploadFile | None = File(default=None), mapeos: str = Form(default=""),
                ajustes: str = Form(default="")):
    reps = [await _archivo(u) for u in reportes if u.filename]
    pag = await _archivo(pagados) if pagados is not None and pagados.filename else None
    try:
        mapas = json.loads(mapeos) if mapeos else {}
        aj = json.loads(ajustes) if ajustes else None
    except ValueError:
        mapas, aj = {}, None
    datos = _leer_todo(await _archivo(maquinas), reps, pag, mapas)
    if not datos["lecturas"]:
        return JSONResponse({"detail": "No se pudo leer ningún reporte.", "sin_leer": datos["sin_leer"],
                             "campos": lec.NOMBRES_CAMPOS}, status_code=422)
    datos["ejemplo"] = False
    codigo = _guardar(datos)
    return {"codigo": codigo, **_resultado(datos, anio, mes, aj)}


@app.post("/api/cierre/ejemplo")
def ejemplo():
    reps = [(p, p.name) for p in sorted(EJEMPLOS.glob("reporte_*.xlsx"))]
    datos = _leer_todo((EJEMPLOS / "vendor_list_EJEMPLO.xlsx", "vendor_list_EJEMPLO.xlsx"), reps,
                       (EJEMPLOS / "compras_impuesto_pagado_EJEMPLO.xlsx", "compras_impuesto_pagado_EJEMPLO.xlsx"))
    datos["ejemplo"] = True
    codigo = _guardar(datos)
    return {"codigo": codigo, "anio": 2026, "mes": 9, **_resultado(datos, 2026, 9, None)}


class Pedido(BaseModel):
    anio: int
    mes: int
    ajustes: dict | None = None


@app.post("/api/cierre/{codigo}/calcular")
def calcular(codigo: str, p: Pedido):
    return _resultado(_cierre(codigo), p.anio, p.mes, p.ajustes)


@app.post("/api/cierre/{codigo}/libro")
def descargar_libro(codigo: str, p: Pedido):
    c = _cierre(codigo)
    datos = lib.libro(_calcular(c, p.anio, p.mes, p.ajustes), c["lecturas"], p.anio, p.mes)
    nombre = f"Integrated_Sales_EzSnack_{lib.MESES[p.mes - 1]}{p.anio}.xlsx"
    return Response(datos, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@app.post("/api/cierre/{codigo}/quickbooks")
def enviar_quickbooks(request: Request, codigo: str, p: Pedido):
    """Envia un recibo de venta por maquina; QuickBooks calcula el impuesto con su modulo de Sales Tax."""
    tokens = _leer_tokens(request)
    if not tokens:
        raise HTTPException(401, "Conecte QuickBooks primero.")
    res = _calcular(_cierre(codigo), p.anio, p.mes, p.ajustes)
    qbo = qbo_mod.QBO(tokens)
    resp = JSONResponse(conta.enviar(qbo, res["maquinas"], p.anio, p.mes))
    if qbo.renovado:
        _poner_cookie(resp, qbo.tokens)
    return resp


class Confirmacion(BaseModel):
    confirmacion: str


@app.post("/api/sandbox/limpiar")
def limpiar_sandbox(request: Request, c: Confirmacion):
    """Deja la empresa de prueba solo con los datos de EzSnack. No funciona en una empresa real."""
    if not sandbox.es_sandbox():
        raise HTTPException(403, "Solo funciona en la empresa de prueba.")
    if c.confirmacion != "BORRAR":
        raise HTTPException(400, "Falta la confirmación.")
    tokens = _leer_tokens(request)
    if not tokens:
        raise HTTPException(401, "Conecte QuickBooks primero.")
    qbo = qbo_mod.QBO(tokens)
    resp = JSONResponse(sandbox.limpiar(qbo))
    if qbo.renovado:
        _poner_cookie(resp, qbo.tokens)
    return resp


@app.get("/api/datos-prueba/{archivo}")
def descargar_prueba(archivo: str):
    ruta = (EJEMPLOS / archivo).resolve()
    if ruta.parent != EJEMPLOS.resolve() or not ruta.exists():
        raise HTTPException(404, "No existe ese archivo de prueba.")
    return FileResponse(ruta, filename=archivo)
