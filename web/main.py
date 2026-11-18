"""Servidor web de EzSnack Impuestos.

Los archivos que sube cada persona se leen en memoria y se guardan un rato con un codigo,
para recalcular sin volver a subirlos: esos archivos no se escriben en disco ni en la base.
Lo que si queda en la base de datos (ezsnack/almacen.py) es lo que debe durar: las reglas con su
historial, las maquinas, la clasificacion de los productos, los sistemas registrados, los usuarios
y el resultado de cada cierre. La conexion con QuickBooks va cifrada en una cookie del navegador.

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
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parents[1]

from ezsnack import almacen as alm  # noqa: E402
from ezsnack import cierre as cie  # noqa: E402
from ezsnack import comparar as cmp  # noqa: E402
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


# ---------------- usuarios y roles ----------------
SESION = "ezsnack_sesion"
NIVEL = {"consulta": 0, "operador": 1, "admin": 2}
DURACION_SESION = 12 * 60 * 60
_fallos: dict[str, list[float]] = {}


def _usuario(request: Request) -> dict:
    """Quien hace la peticion. Mientras no exista ningun usuario, la aplicacion esta abierta."""
    if not alm.hay_usuarios():
        return {"id": None, "nombre": "Sin usuarios", "usuario": "", "rol": "admin", "abierto": True}
    try:
        datos = json.loads(FERNET.decrypt(request.cookies.get(SESION, "").encode()))
        u = alm.usuario_por_id(int(datos["u"])) if time.time() - float(datos["t"]) < DURACION_SESION else None
    except (InvalidToken, ValueError, KeyError, TypeError):
        u = None
    if u is None:
        raise HTTPException(401, "Inicie sesión para continuar.")
    return {**u, "abierto": False}


def _rol(minimo: str):
    def dependencia(request: Request) -> dict:
        u = _usuario(request)
        if NIVEL[u["rol"]] < NIVEL[minimo]:
            raise HTTPException(403, f"Su rol ({alm.ROLES[u['rol']]}) no permite esta acción.")
        return u
    return Depends(dependencia)


CONSULTA, OPERADOR, ADMIN = _rol("consulta"), _rol("operador"), _rol("admin")


class Entrada(BaseModel):
    usuario: str
    clave: str


@app.post("/api/sesion/entrar")
def entrar(e: Entrada):
    clave_fallos = e.usuario.strip().lower()
    recientes = [t for t in _fallos.get(clave_fallos, []) if time.time() - t < 600]
    if len(recientes) >= 5:
        raise HTTPException(429, "Demasiados intentos. Espere diez minutos.")
    u = alm.autenticar(e.usuario, e.clave)
    if u is None:
        _fallos[clave_fallos] = recientes + [time.time()]
        raise HTTPException(401, "Usuario o clave incorrectos.")
    _fallos.pop(clave_fallos, None)
    resp = JSONResponse({"ok": True, "nombre": u["nombre"], "rol": u["rol"]})
    resp.set_cookie(SESION, FERNET.encrypt(json.dumps({"u": u["id"], "t": time.time()}).encode()).decode(),
                    httponly=True, secure=SEGURO, samesite="lax", max_age=DURACION_SESION)
    return resp


@app.post("/api/sesion/salir")
def salir_sesion():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESION)
    return resp


@app.exception_handler(ValueError)
async def _error_valor(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


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


def _pagina() -> str:
    """index.html con una version en el css y el js, para que el navegador no sirva los viejos."""
    carpeta = RAIZ / "web" / "static"
    html = (carpeta / "index.html").read_text(encoding="utf-8")
    for archivo in ("app.css", "app.js"):
        version = hashlib.sha256((carpeta / archivo).read_bytes()).hexdigest()[:10]
        html = html.replace(f"/static/{archivo}", f"/static/{archivo}?v={version}")
    return html


@app.get("/")
def inicio():
    return HTMLResponse(_pagina(), headers={"Cache-Control": "no-store"})


@app.get("/auth/conectar")
def conectar(u: dict = ADMIN):
    if not QBO_LISTO:
        raise HTTPException(503, "Esta instalación no tiene las llaves de QuickBooks.")
    estado = secrets.token_urlsafe(16)
    resp = RedirectResponse(qbo_mod.url_autorizacion(estado))
    resp.set_cookie("ezsnack_estado", estado, httponly=True, secure=SEGURO, samesite="lax", max_age=600)
    return resp


@app.get("/auth/callback")
def callback(request: Request, code: str = "", realmId: str = "", state: str = "", error: str = "", u: dict = ADMIN):
    if error or not code:
        return RedirectResponse("/?conexion=cancelada")
    if state != request.cookies.get("ezsnack_estado"):
        return RedirectResponse("/?conexion=invalida")
    tokens = qbo_mod.obtener_tokens(code, realmId)
    # Al conectar se deja la empresa con las reglas de impuestos de EzSnack (tasas, productos, cliente)
    reglas_ok = "ok"
    try:
        conta.preparar(qbo_mod.QBO(tokens), cie.reglas())
        alm.anotar(u["nombre"], "Conectó QuickBooks", "Quedaron creadas las tasas, los productos, el cliente y la cuenta.")
    except Exception:  # noqa: BLE001  la conexion sirve igual; la pagina lo vuelve a intentar
        reglas_ok = "pendiente"
    resp = RedirectResponse(f"/?conexion=ok&reglas={reglas_ok}")
    _poner_cookie(resp, tokens)
    resp.delete_cookie("ezsnack_estado")
    return resp


@app.post("/auth/salir")
def salir(u: dict = ADMIN):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/api/estado")
def estado(request: Request):
    hoy = date.today()
    previo = date(hoy.year if hoy.month > 1 else hoy.year - 1, hoy.month - 1 or 12, 1)
    try:
        u = _usuario(request)
    except HTTPException:
        return {"requiere_login": True, "anio": previo.year, "mes": previo.month}
    datos = {"requiere_login": False, "usuario": {"nombre": u["nombre"], "rol": u["rol"], "abierto": u["abierto"]},
             "roles": alm.ROLES, "almacen": alm.info(),
             "qbo_disponible": QBO_LISTO, "conectado": False, "empresa": None,
             "entorno": os.getenv("QBO_ENVIRONMENT", "sandbox"), "anio": previo.year, "mes": previo.month,
             "reglas": cie.reglas(), "maquinas_guardadas": len(alm.maquinas())}
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


# ---------------- configuracion de la empresa ----------------
@app.get("/api/config")
def ver_config(u: dict = CONSULTA):
    return {"reglas": cie.reglas(), "base": alm.reglas_base(), "versiones": alm.versiones_reglas(),
            "maquinas": alm.maquinas(), "productos": alm.productos(), "formatos": alm.formatos(),
            "usuarios": alm.listar_usuarios() if u["rol"] == "admin" else [], "bitacora": alm.bitacora(),
            "almacen": alm.info()}


class CambioReglas(BaseModel):
    reglas: dict
    desde: str
    nota: str = ""


@app.post("/api/config/reglas")
def guardar_reglas(c: CambioReglas, u: dict = ADMIN):
    return {"reglas": alm.guardar_reglas(c.reglas, u["nombre"], c.desde, c.nota), "versiones": alm.versiones_reglas()}


@app.post("/api/config/maquinas")
async def subir_maquinas(lista: UploadFile = File(...), u: dict = OPERADOR):
    df = maq.leer(*(await _archivo(lista)))
    return {**alm.guardar_maquinas(df.to_dict("records"), u["nombre"]), "maquinas": alm.maquinas()}


class CambioMaquina(BaseModel):
    ciudad: str | None = None
    activa: bool | None = None


@app.post("/api/config/maquinas/{id_maquina}")
def editar_maquina(id_maquina: str, c: CambioMaquina, u: dict = OPERADOR):
    alm.editar_maquina(id_maquina, c.model_dump(exclude_none=True), u["nombre"])
    return {"maquinas": alm.maquinas()}


class CambioProducto(BaseModel):
    nombre: str
    exento: bool | None = None
    pagado_habitual: bool | None = None
    automatico: bool = False     # vuelve a dejar que decida la regla del agua


@app.post("/api/config/productos")
def clasificar_producto(c: CambioProducto, u: dict = OPERADOR):
    cambios = {}
    if c.automatico:
        cambios["exento"] = None
    elif c.exento is not None:
        cambios["exento"] = c.exento
    if c.pagado_habitual is not None:
        cambios["pagado_habitual"] = c.pagado_habitual
    alm.marcar_producto(c.nombre, u["nombre"], **cambios)
    return {"productos": alm.productos()}


class Formato(BaseModel):
    nombre: str
    mapeo: dict


@app.post("/api/config/formatos")
def registrar_formato(f: Formato, u: dict = OPERADOR):
    alm.guardar_formato(f.nombre, f.mapeo, u["nombre"])
    return {"formatos": alm.formatos()}


@app.post("/api/config/formatos/quitar")
def quitar_formato(f: Formato, u: dict = OPERADOR):
    alm.borrar_formato(f.nombre, u["nombre"])
    return {"formatos": alm.formatos()}


class UsuarioNuevo(BaseModel):
    nombre: str
    usuario: str
    clave: str
    rol: str


@app.post("/api/config/usuarios")
def crear_usuario(n: UsuarioNuevo, u: dict = ADMIN):
    alm.crear_usuario(n.nombre, n.usuario, n.clave, n.rol, u["nombre"] if not u["abierto"] else n.nombre)
    return {"usuarios": alm.listar_usuarios(), "primero": u["abierto"]}


class CambioUsuario(BaseModel):
    rol: str | None = None
    activo: bool | None = None
    clave: str | None = None


@app.post("/api/config/usuarios/{uid}")
def cambiar_usuario(uid: int, c: CambioUsuario, u: dict = ADMIN):
    alm.editar_usuario(uid, u["nombre"], c.rol, c.activo, c.clave)
    return {"usuarios": alm.listar_usuarios()}


# ---------------- historial de cierres ----------------
@app.get("/api/cierres")
def listar_cierres(u: dict = CONSULTA):
    return {"cierres": alm.cierres()}


@app.get("/api/cierres/{cid}")
def ver_cierre(cid: int, u: dict = CONSULTA):
    c = alm.cierre(cid)
    if c is None:
        raise HTTPException(404, "No existe ese cierre.")
    return c


class Estado(BaseModel):
    estado: str


@app.post("/api/cierres/{cid}/estado")
def cambiar_estado(cid: int, e: Estado, u: dict = OPERADOR):
    alm.estado_cierre(cid, e.estado, u["nombre"])
    return {"cierres": alm.cierres()}


# ---------------- cierre ----------------
def _registros(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _leer_todo(maquinas_src, reportes: list[tuple], pagados_src, mapeos: dict | None = None,
               formatos: list | None = None) -> dict:
    if not reportes:
        raise HTTPException(400, "Suba al menos un reporte de ventas.")
    if maquinas_src is None:      # sin vendor list: se usan las maquinas guardadas de la empresa
        guardadas = alm.maquinas()
        if not guardadas:
            raise HTTPException(400, "Suba la lista de máquinas: todavía no hay máquinas guardadas.")
        lista_maq = pd.DataFrame(guardadas, columns=alm.CAMPOS_MAQUINA)
    else:
        try:
            lista_maq = maq.leer(*maquinas_src)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    lecturas, sin_leer = [], []
    for src, nombre in reportes:
        try:
            lecturas.append(lec.leer(src, nombre, (mapeos or {}).get(nombre), formatos))
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


def _archivos(c: dict) -> list[dict]:
    return [{"archivo": l.archivo, "fuente": l.fuente, "usadas": int(len(l.filas)),
             "efectivo": round(float(l.filas["efectivo"].sum()), 2), "tarjeta": round(float(l.filas["tarjeta"].sum()), 2)}
            for l in c["lecturas"]]


def _resultado(c: dict, anio: int, mes: int, ajustes: dict | None) -> dict:
    res = _calcular(c, anio, mes, ajustes)
    columnas_maq = ["id_maquina", "maquina", "fuente", "locacion", "ciudad", "jurisdiccion", "en_lista",
                    "unidades", "ventas", "exentas", "pagadas", "gravable"]
    comparacion = cmp.comparar(c["original"], res, c["maquinas"]) if c.get("original") else None
    return {
        "comparacion": comparacion, "maquinas_guardadas": c.get("maquinas_guardadas"),
        "archivos": [{"archivo": l.archivo, "fuente": l.fuente, "periodo": l.periodo, "leidas": l.leidas,
                      "usadas": int(len(l.filas)), "descartadas": l.descartadas,
                      "efectivo": round(float(l.filas["efectivo"].sum()), 2),
                      "tarjeta": round(float(l.filas["tarjeta"].sum()), 2),
                      "generico": l.generico, "registrado": l.registrado, "avisos": l.avisos,
                      "columnas": l.columnas, "mapeo": l.mapeo}
                     for l in c["lecturas"]],
        "sin_leer": c["sin_leer"], "campos": lec.NOMBRES_CAMPOS, "reglas": res["reglas"],
        "lista_pagados": c["lista_pagados"],
        "pasos": res["pasos"], "declaracion": res["declaracion"],
        "maquinas": _registros(res["maquinas"][columnas_maq].round(2)),
        "cupones": res["cupones"],
        "exentos": _registros(res["exentos"].round(2)),
        "pagados": _registros(res["pagados"].round(2)),
        "revisar": res["revisar"],
        "productos": sorted(c["integ"]["producto"].dropna().unique().tolist(), key=str.lower),
        "verificacion": VERIFICACION.get(f"{anio}-{mes:02d}") if c.get("ejemplo") is False else None,
    }


def _calcular(c: dict, anio: int, mes: int, ajustes: dict | None) -> dict:
    a = cie.Ajustes.de({k: v for k, v in (ajustes or {}).items() if k in ("exentos", "pagados", "cupones_empresa")})
    a.lista_pagados = c["lista_pagados"]
    a.catalogo = alm.productos()
    return cie.calcular(c["integ"], a, anio, mes)


async def _archivo(u: UploadFile) -> tuple[io.BytesIO, str]:
    return io.BytesIO(await u.read()), u.filename or "archivo.xlsx"


@app.post("/api/cierre/archivos")
async def subir(anio: int, mes: int, maquinas: UploadFile | None = File(default=None), reportes: list[UploadFile] = File(...),
                pagados: UploadFile | None = File(default=None), mapeos: str = Form(default=""),
                ajustes: str = Form(default=""), u: dict = OPERADOR):
    reps = [await _archivo(u) for u in reportes if u.filename]
    pag = await _archivo(pagados) if pagados is not None and pagados.filename else None
    try:
        mapas = json.loads(mapeos) if mapeos else {}
        aj = json.loads(ajustes) if ajustes else None
    except ValueError:
        mapas, aj = {}, None
    lista = await _archivo(maquinas) if maquinas is not None and maquinas.filename else None
    datos = _leer_todo(lista, reps, pag, mapas, alm.formatos())
    if not datos["lecturas"]:
        return JSONResponse({"detail": "No se pudo leer ningún reporte.", "sin_leer": datos["sin_leer"],
                             "campos": lec.NOMBRES_CAMPOS}, status_code=422)
    datos["ejemplo"] = False
    if lista is not None:       # el vendor list que se sube queda guardado para los meses siguientes
        datos["maquinas_guardadas"] = alm.guardar_maquinas(datos["maquinas"].to_dict("records"), u["nombre"])
    codigo = _guardar(datos)
    return {"codigo": codigo, **_resultado(datos, anio, mes, aj)}


@app.post("/api/cierre/ejemplo")
def ejemplo(u: dict = OPERADOR):
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
def calcular(codigo: str, p: Pedido, u: dict = OPERADOR):
    return _resultado(_cierre(codigo), p.anio, p.mes, p.ajustes)


@app.post("/api/cierre/{codigo}/libro")
def descargar_libro(codigo: str, p: Pedido, u: dict = OPERADOR):
    c = _cierre(codigo)
    datos = lib.libro(_calcular(c, p.anio, p.mes, p.ajustes), c["lecturas"], p.anio, p.mes)
    nombre = f"Integrated_Sales_EzSnack_{lib.MESES[p.mes - 1]}{p.anio}.xlsx"
    return Response(datos, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@app.post("/api/cierre/{codigo}/guardar")
def guardar_cierre(codigo: str, p: Pedido, u: dict = OPERADOR):
    """Guarda el cierre del mes en el historial, con las reglas que tenia."""
    c = _cierre(codigo)
    if c.get("ejemplo"):
        raise HTTPException(400, "Los archivos de ejemplo no se guardan en el historial.")
    res = _calcular(c, p.anio, p.mes, p.ajustes)
    return {**alm.guardar_cierre(p.anio, p.mes, res, _archivos(c), u["nombre"]), "cierres": alm.cierres()}


@app.post("/api/cierre/{codigo}/comparar")
async def comparar_original(codigo: str, anio: int, mes: int, original: UploadFile = File(...), ajustes: str = Form(default=""),
                            u: dict = OPERADOR):
    """Recibe el Excel integrado hecho a mano y lo compara, renglon por renglon, con este cierre."""
    c = _cierre(codigo)
    try:
        c["original"] = cmp.leer_original(*(await _archivo(original)))
    except cmp.ExcelNoReconocido as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        aj = json.loads(ajustes) if ajustes else None
    except ValueError:
        aj = None
    return _resultado(c, anio, mes, aj)


@app.post("/api/cierre/{codigo}/comparar/quitar")
def quitar_original(codigo: str, p: Pedido, u: dict = OPERADOR):
    c = _cierre(codigo)
    c.pop("original", None)
    return _resultado(c, p.anio, p.mes, p.ajustes)


@app.get("/api/quickbooks/tasas")
def ver_tasas(request: Request, u: dict = OPERADOR):
    """Deja (si falta algo) y devuelve la configuracion de impuestos de EzSnack en QuickBooks."""
    tokens = _leer_tokens(request)
    if not tokens:
        raise HTTPException(400, "Conecte QuickBooks primero.")
    qbo = qbo_mod.QBO(tokens)
    resp = JSONResponse({**conta.preparar(qbo, cie.reglas()), "empresa": qbo.info_empresa().get("CompanyName")})
    if qbo.renovado:
        _poner_cookie(resp, qbo.tokens)
    return resp


@app.post("/api/cierre/{codigo}/quickbooks")
def enviar_quickbooks(request: Request, codigo: str, p: Pedido, u: dict = OPERADOR):
    """Envia un recibo de venta por maquina; QuickBooks calcula el impuesto con su modulo de Sales Tax."""
    c = _cierre(codigo)
    res = _calcular(c, p.anio, p.mes, p.ajustes)
    if res["reglas"]["contabilidad"]["destino"] != "quickbooks":
        raise HTTPException(400, "La empresa está configurada para no enviar a contabilidad. Cámbielo en Configuración.")
    tokens = _leer_tokens(request)
    if not tokens:
        raise HTTPException(400, "Conecte QuickBooks primero.")
    qbo = qbo_mod.QBO(tokens)
    envio = conta.enviar(qbo, res["maquinas"], p.anio, p.mes, res["declaracion"]["quickbooks_esperado"], res["reglas"])
    if not c.get("ejemplo"):    # el cierre enviado queda en el historial con lo que respondio QuickBooks
        try:
            envio["cierre"] = alm.guardar_cierre(p.anio, p.mes, res, _archivos(c), u["nombre"], {
                k: envio[k] for k in ("cuadre", "cuadra", "impuesto", "gravable", "exento", "creados", "actualizados", "errores")})
        except ValueError as exc:
            envio["aviso"] = str(exc)
    resp = JSONResponse(envio)
    if qbo.renovado:
        _poner_cookie(resp, qbo.tokens)
    return resp


class Confirmacion(BaseModel):
    confirmacion: str


@app.post("/api/sandbox/limpiar")
def limpiar_sandbox(request: Request, c: Confirmacion, u: dict = ADMIN):
    """Deja la empresa de prueba solo con los datos de EzSnack. No funciona en una empresa real."""
    if not sandbox.es_sandbox():
        raise HTTPException(403, "Solo funciona en la empresa de prueba.")
    if c.confirmacion != "BORRAR":
        raise HTTPException(400, "Falta la confirmación.")
    tokens = _leer_tokens(request)
    if not tokens:
        raise HTTPException(400, "Conecte QuickBooks primero.")
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
