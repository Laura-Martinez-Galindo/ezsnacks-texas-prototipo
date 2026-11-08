"""Servidor web de EzSnack Impuestos.

La conexion con QuickBooks de cada persona se guarda cifrada en una cookie de su navegador,
asi el servidor no guarda tokens y cada quien solo ve la empresa que autorizo.

Local:   uvicorn web.main:app --reload --port 8000
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import io
import json
import os
import secrets
import threading
import time
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parents[1]
os.chdir(RAIZ)  # los modulos leen config/ con rutas relativas

from ezsnack import qbo as qbo_mod  # noqa: E402
from ezsnack import consolidar as cons  # noqa: E402
from ezsnack import emparejar as emp  # noqa: E402
from ezsnack import preparar as prep  # noqa: E402
from ezsnack import servicios as serv  # noqa: E402

COOKIE = "ezsnack_qbo"
# Con SESSION_SECRET las sesiones sobreviven a reinicios; sin ella se crea una clave nueva al arrancar
_secreto = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(_secreto.encode()).digest()))
CATALOGO = json.loads(Path("config/catalogo.json").read_text(encoding="utf-8"))
TARIFAS = {k: v for k, v in json.loads(Path("config/tarifas.json").read_text(encoding="utf-8")).items()
           if not k.startswith("_")}
SEGURO = os.getenv("QBO_REDIRECT_URI", "").startswith("https://")

app = FastAPI(title="EzSnack Impuestos", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=RAIZ / "web" / "static"), name="static")

TRABAJOS: dict[str, dict] = {}
PLANES: dict[str, dict] = {}


# ---------------- sesion ----------------
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


def _cliente(request: Request) -> qbo_mod.QBO:
    tokens = _leer_tokens(request)
    if not tokens:
        raise HTTPException(401, "Conecte QuickBooks para hacer esto.")
    return qbo_mod.QBO(tokens)


def _responder(datos, qbo: qbo_mod.QBO | None = None):
    resp = JSONResponse(datos)
    if qbo is not None and qbo.renovado:
        _poner_cookie(resp, qbo.tokens)
    return resp


def _df(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso", force_ascii=False))


@app.exception_handler(qbo_mod.QBOError)
async def _error_qbo(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ---------------- paginas y conexion ----------------
@app.get("/")
def inicio():
    return FileResponse(RAIZ / "web" / "static" / "index.html")


@app.get("/auth/conectar")
def conectar():
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
    datos = {"conectado": False, "empresa": None, "entorno": os.getenv("QBO_ENVIRONMENT", "sandbox"),
             "anio": previo.year, "mes": previo.month}
    tokens = _leer_tokens(request)
    if not tokens:
        return datos
    try:
        qbo = qbo_mod.QBO(tokens)
        datos.update(conectado=True, empresa=qbo.info_empresa().get("CompanyName"))
        return _responder(datos, qbo)
    except Exception:  # noqa: BLE001
        return datos


def _productos(request: Request) -> tuple[dict[str, bool], qbo_mod.QBO | None]:
    tokens = _leer_tokens(request)
    if tokens:
        try:
            qbo = qbo_mod.QBO(tokens)
            return {n: d["Taxable"] for n, d in serv.productos_qbo(qbo).items()}, qbo
        except Exception:  # noqa: BLE001
            pass
    return {p["nombre"]: p["gravable"] for p in CATALOGO["productos"]}, None


@app.get("/api/productos")
def productos(request: Request):
    grav, qbo = _productos(request)
    return _responder({"productos": sorted(grav)}, qbo)


# ---------------- 1. ventas ----------------
def _unir(vendor_src, fuentes: list[tuple], grav: dict[str, bool]) -> dict:
    importlib.reload(emp)  # toma alias recien guardados
    vendor = cons.leer_vendor_list(vendor_src)
    tablas = [cons.leer_ventas(src, sistema) for src, sistema in fuentes]
    if not tablas:
        raise HTTPException(400, "Suba al menos un reporte de ventas.")
    detalle, problemas = cons.consolidar(tablas, vendor, list(grav))
    resumen = cons.resumen_por_maquina(detalle)
    ok = detalle[detalle["producto"].notna()]
    exentas = float(ok.loc[~ok["producto"].map(lambda p: grav.get(p, True)), "valor"].sum())
    maquinas = (resumen.groupby(["id_maquina", "locacion", "ciudad"])
                .agg(productos=("producto", "count"), unidades=("cantidad", "sum"), ventas=("valor", "sum"))
                .reset_index())
    sistemas = (detalle.groupby("sistema").agg(lineas=("valor", "size"), ventas=("valor", "sum")).reset_index())
    return {
        "metricas": {"lineas": int(len(detalle)), "ventas": round(float(detalle["valor"].sum()), 2),
                     "exentas": round(exentas, 2), "por_revisar": int(len(problemas)),
                     "maquinas": int(resumen["id_maquina"].nunique())},
        "sistemas": _df(sistemas),
        "problemas": _df(problemas),
        "maquinas": _df(maquinas),
        "previa": _df(cons.vista_previa_impuesto(detalle, grav, TARIFAS)),
        "resumen": _df(resumen),
        "comisiones": _df(serv.calcular_comisiones(detalle)),
    }


@app.post("/api/ventas/unir")
async def unir(request: Request, vendor: UploadFile = File(...),
               nayax: list[UploadFile] = File(default=[]), ab360: list[UploadFile] = File(default=[]),
               otro: list[UploadFile] = File(default=[])):
    grav, qbo = _productos(request)

    async def archivo(u: UploadFile):
        b = io.BytesIO(await u.read())
        b.name = u.filename or "archivo.xlsx"  # la extension decide si se lee como CSV o Excel
        return b

    fuentes = []
    for lista, sistema in ((nayax, "Nayax"), (ab360, "AB360"), (otro, "Otro")):
        for u in lista:
            if u.filename:
                fuentes.append((await archivo(u), sistema))
    try:
        datos = _unir(await archivo(vendor), fuentes, grav)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _responder(datos, qbo)


@app.post("/api/ventas/ejemplo")
def unir_ejemplo(request: Request):
    """Une los archivos de prueba incluidos en el proyecto (para probar sin archivos propios)."""
    grav, qbo = _productos(request)
    d = Path("datos_prueba")
    datos = _unir(d / "vendor_list_PRUEBA.xlsx",
                  [(d / "nayax_ventas_2026-09_PRUEBA.xlsx", "Nayax"), (d / "ab360_ventas_2026-09_PRUEBA.xlsx", "AB360")],
                  grav)
    datos["ejemplo"] = {"anio": 2026, "mes": 9}
    return _responder(datos, qbo)


class Envio(BaseModel):
    anio: int
    mes: int
    resumen: list[dict]


@app.post("/api/ventas/enviar")
def enviar(request: Request, envio: Envio):
    qbo = _cliente(request)
    resumen = pd.DataFrame(envio.resumen)
    recibos = serv.armar_recibos(resumen, serv.productos_qbo(qbo), envio.anio, envio.mes, serv.id_cliente_ventas(qbo))
    res = serv.enviar_recibos(qbo, recibos)
    return _responder({"recibos": _df(res)}, qbo)


class Alias(BaseModel):
    texto: str
    producto: str


@app.post("/api/alias")
def guardar_alias(alias: Alias):
    emp.guardar_alias(alias.texto, alias.producto)
    return {"ok": True}


# ---------------- 2. recibos ----------------
@app.get("/api/recibos")
def recibos(request: Request, desde: date, hasta: date):
    qbo = _cliente(request)
    importlib.reload(emp)
    grav = {n: d["Taxable"] for n, d in serv.productos_qbo(qbo).items()}
    r = serv.revisar_recibos(qbo, desde, hasta, list(grav))
    ok = ["alias", "seguro", "producto registrado"]
    datos = {
        "renglones": _df(r),
        "impuesto_pagado": round(float(r.loc[r["estado"] == "impuesto", "monto"].sum()), 2) if not r.empty else 0,
        "productos_con_impuesto": round(float(r.loc[r["estado"].isin(ok), "monto"].sum()), 2) if not r.empty else 0,
        "por_revisar": int(r["estado"].isin(["dudoso", "sin_coincidencia"]).sum()) if not r.empty else 0,
    }
    return _responder(datos, qbo)


# ---------------- 3. comisiones ----------------
class Comisiones(BaseModel):
    anio: int
    mes: int
    comisiones: list[dict]


@app.post("/api/comisiones/registrar")
def registrar(request: Request, c: Comisiones):
    qbo = _cliente(request)
    res = serv.registrar_comisiones(qbo, pd.DataFrame(c.comisiones), c.anio, c.mes)
    return _responder({"resultado": _df(res)}, qbo)


# ---------------- preparar sandbox (tareas largas en segundo plano) ----------------
def _trabajo(nombre: str, fn) -> str:
    tid = uuid.uuid4().hex[:10]
    TRABAJOS[tid] = {"nombre": nombre, "estado": "corriendo", "progreso": 0.0, "resultado": None, "inicio": time.time()}

    def correr():
        try:
            TRABAJOS[tid]["resultado"] = fn(lambda p: TRABAJOS[tid].update(progreso=round(p, 3)))
            TRABAJOS[tid]["estado"] = "listo"
        except Exception as exc:  # noqa: BLE001
            TRABAJOS[tid].update(estado="error", resultado=str(exc))
        TRABAJOS[tid]["progreso"] = 1.0

    threading.Thread(target=correr, daemon=True).start()
    return tid


def _solo_sandbox():
    if not prep.es_sandbox():
        raise HTTPException(403, "Esto solo funciona en el sandbox.")


@app.post("/api/preparar/plan")
def plan(request: Request):
    _solo_sandbox()
    qbo = _cliente(request)
    p = prep.plan_limpieza(qbo)
    PLANES[qbo.tokens["realm_id"]] = p
    return _responder({"plan": prep.resumen_plan(p)}, qbo)


class Confirmacion(BaseModel):
    confirmacion: str


@app.post("/api/preparar/limpiar")
def limpiar(request: Request, c: Confirmacion):
    _solo_sandbox()
    if c.confirmacion.strip() != "BORRAR":
        raise HTTPException(400, "Escriba BORRAR para confirmar.")
    qbo = _cliente(request)
    p = PLANES.pop(qbo.tokens["realm_id"], None)
    if p is None:
        raise HTTPException(400, "Primero revise qué se quitaría.")
    tid = _trabajo("limpieza", lambda prog: prep.ejecutar_limpieza(qbo, p, prog))
    return _responder({"trabajo": tid}, qbo)


@app.post("/api/preparar/cargar")
def cargar(request: Request):
    _solo_sandbox()
    qbo = _cliente(request)
    return _responder({"trabajo": _trabajo("carga", lambda _: prep.cargar_datos(qbo))}, qbo)


@app.post("/api/preparar/recibos-prueba")
def recibos_prueba(request: Request):
    _solo_sandbox()
    qbo = _cliente(request)
    return _responder({"trabajo": _trabajo("recibos", lambda _: prep.cargar_recibos_prueba(qbo))}, qbo)


@app.get("/api/trabajos/{tid}")
def trabajo(tid: str):
    if tid not in TRABAJOS:
        raise HTTPException(404, "Esa tarea ya no existe. Vuelva a iniciarla.")
    return TRABAJOS[tid]


@app.get("/api/datos-prueba/{archivo}")
def descargar_prueba(archivo: str):
    ruta = (Path("datos_prueba") / archivo).resolve()
    if ruta.parent != (RAIZ / "datos_prueba").resolve() or not ruta.exists():
        raise HTTPException(404, "No existe ese archivo de prueba.")
    return FileResponse(ruta, filename=archivo)
