"""Base de datos de la aplicacion: lo que debe sobrevivir de un mes a otro.

    empresas          la empresa duena de los datos (hoy una sola, EzSnack Texas)
    usuarios          quien entra y con que rol: admin, operador o consulta
    reglas            versiones de las reglas del cierre, cada una con el mes desde el que aplica
    maquinas          la lista de maquinas (el vendor list), editable
    productos         la clasificacion que el gerente ya decidio para cada producto
    equivalencias     nombres distintos del mismo producto en los distintos sistemas de ventas
    formatos          los sistemas de ventas registrados y como se leen sus columnas
    cierres           cada cierre guardado, con las reglas que tenia en ese momento
    cierre_maquinas   el detalle por maquina de cada cierre (un renglon = un recibo de venta)
    bitacora          quien cambio que y cuando

Con la variable DATABASE_URL usa PostgreSQL (asi queda en Render). Sin ella usa un archivo SQLite
en la carpeta datos/, que sirve en un computador pero en Render se pierde al reiniciar el servicio.
Los archivos que se suben cada mes no se guardan: solo los resultados del cierre.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa

RAIZ = Path(__file__).resolve().parents[1]
ROLES = {"admin": "Administrador", "operador": "Operador", "consulta": "Consulta"}
EMPRESA = 1

meta = sa.MetaData()
empresas = sa.Table("empresas", meta,
                    sa.Column("id", sa.Integer, primary_key=True), sa.Column("nombre", sa.String(120), nullable=False),
                    sa.Column("direccion", sa.String(200)), sa.Column("creado", sa.String(32)))
usuarios = sa.Table("usuarios", meta,
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.id"), nullable=False),
                    sa.Column("nombre", sa.String(80), nullable=False),
                    sa.Column("usuario", sa.String(40), nullable=False, unique=True),
                    sa.Column("clave_hash", sa.String(200), nullable=False),
                    sa.Column("rol", sa.String(12), nullable=False), sa.Column("activo", sa.Boolean, nullable=False, default=True),
                    sa.Column("creado", sa.String(32)))
reglas_t = sa.Table("reglas", meta,
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.id"), nullable=False),
                    sa.Column("desde", sa.String(7), nullable=False),      # "2026-09": primer mes al que aplica
                    sa.Column("contenido", sa.JSON, nullable=False),
                    sa.Column("nota", sa.String(300)), sa.Column("creado_por", sa.String(80)),
                    sa.Column("creado", sa.String(32)))
maquinas_t = sa.Table("maquinas", meta,
                      sa.Column("id", sa.Integer, primary_key=True),
                      sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.id"), nullable=False),
                      sa.Column("id_maquina", sa.String(20), nullable=False),
                      sa.Column("locacion", sa.String(200)), sa.Column("direccion", sa.String(200)),
                      sa.Column("ciudad", sa.String(80)), sa.Column("estado", sa.String(8)), sa.Column("zip", sa.String(12)),
                      sa.Column("activa", sa.Boolean, nullable=False, default=True),
                      sa.Column("actualizado", sa.String(32)),
                      sa.UniqueConstraint("empresa_id", "id_maquina"))
productos_t = sa.Table("productos", meta,
                       sa.Column("id", sa.Integer, primary_key=True),
                       sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.id"), nullable=False),
                       sa.Column("nombre", sa.String(200), nullable=False),
                       sa.Column("exento", sa.Boolean),                      # None = que decida la regla del agua
                       sa.Column("pagado_habitual", sa.Boolean, nullable=False, default=False),
                       sa.Column("actualizado_por", sa.String(80)), sa.Column("actualizado", sa.String(32)),
                       sa.UniqueConstraint("empresa_id", "nombre"))
formatos_t = sa.Table("formatos", meta,
                      sa.Column("id", sa.Integer, primary_key=True),
                      sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.id"), nullable=False),
                      sa.Column("nombre", sa.String(24), nullable=False), sa.Column("mapeo", sa.JSON, nullable=False),
                      sa.Column("creado_por", sa.String(80)), sa.Column("creado", sa.String(32)),
                      sa.UniqueConstraint("empresa_id", "nombre"))
equivalencias_t = sa.Table("equivalencias", meta,
                           sa.Column("id", sa.Integer, primary_key=True),
                           sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.id"), nullable=False),
                           sa.Column("alias", sa.String(200), nullable=False),        # como lo llama un sistema
                           sa.Column("producto", sa.String(200), nullable=False),     # el nombre principal
                           sa.Column("estado", sa.String(10), nullable=False),        # unido o distinto
                           sa.Column("por", sa.String(80)), sa.Column("fecha", sa.String(32)),
                           sa.UniqueConstraint("empresa_id", "alias", "producto"))
cierres_t = sa.Table("cierres", meta,
                     sa.Column("id", sa.Integer, primary_key=True),
                     sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.id"), nullable=False),
                     sa.Column("anio", sa.Integer, nullable=False), sa.Column("mes", sa.Integer, nullable=False),
                     sa.Column("estado", sa.String(12), nullable=False),     # guardado, enviado, declarado
                     sa.Column("reglas_id", sa.Integer), sa.Column("reglas", sa.JSON),
                     sa.Column("resumen", sa.JSON), sa.Column("declaracion", sa.JSON),
                     sa.Column("archivos", sa.JSON), sa.Column("envio", sa.JSON),
                     sa.Column("guardado_por", sa.String(80)), sa.Column("guardado", sa.String(32)),
                     sa.UniqueConstraint("empresa_id", "anio", "mes"))
cierre_maquinas = sa.Table("cierre_maquinas", meta,
                           sa.Column("id", sa.Integer, primary_key=True),
                           sa.Column("cierre_id", sa.Integer, sa.ForeignKey("cierres.id", ondelete="CASCADE"), nullable=False),
                           sa.Column("id_maquina", sa.String(20)), sa.Column("maquina", sa.String(200)),
                           sa.Column("ciudad", sa.String(80)), sa.Column("jurisdiccion", sa.String(60)),
                           sa.Column("ventas", sa.Float), sa.Column("exentas", sa.Float),
                           sa.Column("pagadas", sa.Float), sa.Column("gravable", sa.Float))
bitacora_t = sa.Table("bitacora", meta,
                      sa.Column("id", sa.Integer, primary_key=True),
                      sa.Column("empresa_id", sa.Integer, sa.ForeignKey("empresas.id"), nullable=False),
                      sa.Column("fecha", sa.String(32), nullable=False), sa.Column("usuario", sa.String(80)),
                      sa.Column("accion", sa.String(60), nullable=False), sa.Column("detalle", sa.String(600)))

_engine: sa.Engine | None = None


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        for viejo in ("postgres://", "postgresql://"):
            if url.startswith(viejo):
                return "postgresql+psycopg://" + url[len(viejo):]
        return url
    carpeta = Path(os.getenv("DATOS_DIR") or RAIZ / "datos")
    carpeta.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{carpeta / 'ezsnack.db'}"


def reglas_base() -> dict:
    """Las reglas con las que arranca una instalacion nueva (config/reglas.json)."""
    return completar(json.loads((RAIZ / "config" / "reglas.json").read_text(encoding="utf-8")))


def completar(R: dict) -> dict:
    """Agrega a unas reglas los campos que aparecieron despues, para leer versiones viejas."""
    R = dict(R)
    R.setdefault("devoluciones", {"metodo": "cupones", "porcentaje": 3.0})
    R.setdefault("cupones_empresa_minimo", 100)
    R.setdefault("cupones_empresas", [])        # maquinas donde una empresa compra cupones para sus empleados
    R.setdefault("cupones_empresa_cuentan", False)   # los cupones de empresas no son venta ni devolucion
    R.setdefault("agua_palabras", ["water", "agua"])
    R.setdefault("agua_excepciones", ["vitamin", "coconut", "tonic", "flavored", "kiwi", "strawberry", "lemonade", "juice", "bubly"])
    R.setdefault("contabilidad", {})
    R["contabilidad"] = {"destino": "quickbooks", "cuenta": "Ventas en maquinas", "cliente": "Consumidores en maquinas",
                         **R["contabilidad"]}
    return R


def motor() -> sa.Engine:
    global _engine
    if _engine is None:
        url = _url()
        _engine = sa.create_engine(url, pool_pre_ping=True, future=True,
                                   **({"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}))
        meta.create_all(_engine)
        with _engine.begin() as c:
            if c.execute(sa.select(sa.func.count()).select_from(empresas)).scalar() == 0:
                c.execute(empresas.insert().values(id=EMPRESA, nombre="EzSnack Texas", direccion="4520 W 34th St Ste G, Houston, TX 77092",
                                                   creado=_ahora()))
            if c.execute(sa.select(sa.func.count()).select_from(reglas_t)).scalar() == 0:
                c.execute(reglas_t.insert().values(empresa_id=EMPRESA, desde="2000-01", contenido=reglas_base(),
                                                   nota="Reglas iniciales", creado_por="Instalación", creado=_ahora()))
    return _engine


def reiniciar() -> None:
    """Solo para las pruebas: olvida la conexion para abrir otra base."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def info() -> dict:
    url = _url()
    return {"motor": "PostgreSQL" if url.startswith("postgresql") else "SQLite",
            "persistente": url.startswith("postgresql") or bool(os.getenv("DATOS_DIR"))}


def anotar(usuario: str, accion: str, detalle: str = "") -> None:
    with motor().begin() as c:
        c.execute(bitacora_t.insert().values(empresa_id=EMPRESA, fecha=_ahora(), usuario=usuario, accion=accion,
                                             detalle=str(detalle)[:600]))


def bitacora(limite: int = 80) -> list[dict]:
    with motor().connect() as c:
        filas = c.execute(sa.select(bitacora_t).order_by(bitacora_t.c.id.desc()).limit(limite)).mappings().all()
    return [{k: f[k] for k in ("fecha", "usuario", "accion", "detalle")} for f in filas]


# ---------------- reglas ----------------
def reglas(periodo: str | None = None) -> dict:
    """Las reglas que aplican a un mes ("2026-09"). Sin mes, las mas recientes."""
    with motor().connect() as c:
        q = sa.select(reglas_t).where(reglas_t.c.empresa_id == EMPRESA)
        if periodo:
            q = q.where(reglas_t.c.desde <= periodo)
        fila = c.execute(q.order_by(reglas_t.c.desde.desc(), reglas_t.c.id.desc()).limit(1)).mappings().first()
        if fila is None:   # el mes es anterior a todas las versiones: se usa la primera
            fila = c.execute(sa.select(reglas_t).order_by(reglas_t.c.desde, reglas_t.c.id).limit(1)).mappings().first()
    R = completar(fila["contenido"])
    R["_version"] = {"id": fila["id"], "desde": fila["desde"], "por": fila["creado_por"], "creado": fila["creado"]}
    return R


def validar_reglas(R: dict) -> dict:
    """Limpia y valida lo que llega del panel. Lanza ValueError con un mensaje para la pagina."""
    def pct(v, nombre, maximo=30.0):
        try:
            v = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{nombre} debe ser un número.") from exc
        if not 0 <= v <= maximo:
            raise ValueError(f"{nombre} debe estar entre 0 y {maximo:g}.")
        return round(v, 4)

    def textos(v) -> list[str]:
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    base = reglas_base()
    limpio = {"tasa_estado": pct(R.get("tasa_estado"), "La tasa del estado"),
              "tasa_compras": pct(R.get("tasa_compras", R.get("tasa_estado")), "La tasa de las compras"),
              "descuento_a_tiempo_pct": pct(R.get("descuento_a_tiempo_pct", 0), "El descuento por pago a tiempo", 10),
              "cupones_empresa_minimo": max(float(R.get("cupones_empresa_minimo") or 0), 0.0),
              "cupones_empresas": textos(R.get("cupones_empresas")),
              "cupones_empresa_cuentan": bool(R.get("cupones_empresa_cuentan", False)),
              "agua_palabras": [t.lower() for t in textos(R.get("agua_palabras"))] or base["agua_palabras"],
              "agua_excepciones": [t.lower() for t in textos(R.get("agua_excepciones"))]}
    dev = R.get("devoluciones") or {}
    limpio["devoluciones"] = {"metodo": "porcentaje" if dev.get("metodo") == "porcentaje" else "cupones",
                              "porcentaje": pct(dev.get("porcentaje", 3), "El porcentaje de devoluciones", 100)}
    jur, vistas = {}, set()
    for nombre, j in (R.get("jurisdicciones") or {}).items():
        nombre = str(nombre).strip()
        if not nombre:
            raise ValueError("Cada jurisdicción necesita un nombre.")
        ciudades = textos(j.get("ciudades"))
        repetidas = {c.lower() for c in ciudades} & vistas
        if repetidas:
            raise ValueError(f"La ciudad {sorted(repetidas)[0].title()} está en dos jurisdicciones.")
        vistas |= {c.lower() for c in ciudades}
        jur[nombre] = {"codigo": str(j.get("codigo") or "").strip(),
                       "nombre_comptroller": str(j.get("nombre_comptroller") or nombre).strip().upper(),
                       "tasa": pct(j.get("tasa"), f"La tasa de {nombre}"), "ciudades": ciudades}
    if len({j["nombre_comptroller"] for j in jur.values()}) != len(jur):
        raise ValueError("Dos jurisdicciones tienen el mismo nombre del Comptroller.")
    limpio["jurisdicciones"] = jur
    conta = R.get("contabilidad") or {}
    destino = conta.get("destino") if conta.get("destino") in ("quickbooks", "excel") else "quickbooks"
    limpio["contabilidad"] = {"destino": destino,
                              "cuenta": str(conta.get("cuenta") or "Ventas en maquinas").strip()[:90],
                              "cliente": str(conta.get("cliente") or "Consumidores en maquinas").strip()[:90]}
    return limpio


def guardar_reglas(R: dict, usuario: str, desde: str, nota: str = "") -> dict:
    limpio = validar_reglas(R)
    if not (len(desde) == 7 and desde[4] == "-" and desde[:4].isdigit() and desde[5:].isdigit() and 1 <= int(desde[5:]) <= 12):
        raise ValueError("El mes desde el que aplican debe ser como 2026-09.")
    with motor().begin() as c:
        c.execute(reglas_t.insert().values(empresa_id=EMPRESA, desde=desde, contenido=limpio, nota=nota[:300],
                                           creado_por=usuario, creado=_ahora()))
    anotar(usuario, "Cambió las reglas", f"Aplican desde {desde}. {nota}".strip())
    return reglas()


def versiones_reglas() -> list[dict]:
    with motor().connect() as c:
        filas = c.execute(sa.select(reglas_t).order_by(reglas_t.c.id.desc()).limit(40)).mappings().all()
    return [{"id": f["id"], "desde": f["desde"], "por": f["creado_por"], "creado": f["creado"], "nota": f["nota"]} for f in filas]


# ---------------- maquinas ----------------
CAMPOS_MAQUINA = ["id_maquina", "locacion", "direccion", "ciudad", "estado", "zip", "activa"]


def maquinas() -> list[dict]:
    with motor().connect() as c:
        filas = c.execute(sa.select(maquinas_t).where(maquinas_t.c.empresa_id == EMPRESA)).mappings().all()
    orden = lambda f: (0, int(f["id_maquina"])) if str(f["id_maquina"]).isdigit() else (1, 0)  # noqa: E731
    return [{k: f[k] for k in CAMPOS_MAQUINA} for f in sorted(filas, key=orden)]


def guardar_maquinas(lista: list[dict], usuario: str) -> dict:
    """Recibe el vendor list ya leido. Agrega las nuevas y actualiza las que cambiaron."""
    nuevas = cambiadas = 0
    with motor().begin() as c:
        actuales = {f["id_maquina"]: f for f in
                    c.execute(sa.select(maquinas_t).where(maquinas_t.c.empresa_id == EMPRESA)).mappings().all()}
        for m in lista:
            largo = {"id_maquina": 20, "locacion": 200, "direccion": 200, "ciudad": 80, "estado": 8, "zip": 12}
            valores = {k: ("" if m.get(k) is None else str(m[k]))[:n] for k, n in largo.items()}
            valores["activa"] = bool(m.get("activa", True))
            previa = actuales.get(valores["id_maquina"])
            if previa is None:
                c.execute(maquinas_t.insert().values(empresa_id=EMPRESA, actualizado=_ahora(), **valores))
                nuevas += 1
            elif any(previa[k] != valores[k] for k in CAMPOS_MAQUINA):
                c.execute(maquinas_t.update().where(maquinas_t.c.id == previa["id"]).values(actualizado=_ahora(), **valores))
                cambiadas += 1
    if nuevas or cambiadas:
        anotar(usuario, "Actualizó la lista de máquinas", f"{nuevas} nuevas, {cambiadas} con cambios.")
    return {"nuevas": nuevas, "cambiadas": cambiadas, "total": len(maquinas())}


def editar_maquina(id_maquina: str, cambios: dict, usuario: str) -> None:
    valores = {k: v for k, v in cambios.items() if k in ("ciudad", "activa", "locacion", "direccion", "zip")}
    if "ciudad" in valores:
        valores["ciudad"] = str(valores["ciudad"]).strip().title()
    if "activa" in valores:
        valores["activa"] = bool(valores["activa"])
    if not valores:
        return
    with motor().begin() as c:
        hecho = c.execute(maquinas_t.update().where((maquinas_t.c.empresa_id == EMPRESA) & (maquinas_t.c.id_maquina == id_maquina))
                          .values(actualizado=_ahora(), **valores)).rowcount
    if not hecho:
        raise ValueError("No existe esa máquina.")
    anotar(usuario, "Editó una máquina", f"Máquina {id_maquina}: " + ", ".join(f"{k} = {v}" for k, v in valores.items()))


# ---------------- productos ----------------
def productos() -> dict[str, dict]:
    with motor().connect() as c:
        filas = c.execute(sa.select(productos_t).where(productos_t.c.empresa_id == EMPRESA)).mappings().all()
    return {f["nombre"]: {"exento": f["exento"], "pagado_habitual": bool(f["pagado_habitual"]),
                          "por": f["actualizado_por"], "actualizado": f["actualizado"]} for f in filas}


def marcar_producto(nombre: str, usuario: str, **cambios) -> None:
    """cambios: exento=True/False/None (None vuelve a la regla del agua), pagado_habitual=True/False."""
    nombre = str(nombre).strip()[:200]
    valores = {k: v for k, v in cambios.items() if k in ("exento", "pagado_habitual")}
    if not nombre or not valores:
        return
    with motor().begin() as c:
        previa = c.execute(sa.select(productos_t).where((productos_t.c.empresa_id == EMPRESA) & (productos_t.c.nombre == nombre))).mappings().first()
        if previa is None:
            c.execute(productos_t.insert().values(empresa_id=EMPRESA, nombre=nombre, actualizado_por=usuario,
                                                      actualizado=_ahora(), **{"pagado_habitual": False, **valores}))
        else:
            nuevo = {"exento": previa["exento"], "pagado_habitual": previa["pagado_habitual"], **valores}
            c.execute(productos_t.update().where(productos_t.c.id == previa["id"])
                      .values(actualizado_por=usuario, actualizado=_ahora(), **valores))
    textos = {"exento": {True: "sin impuesto", False: "con impuesto", None: "automático"},
              "pagado_habitual": {True: "se compra por fuera", False: "ya no se compra por fuera"}}
    anotar(usuario, "Clasificó un producto", f"{nombre}: " + ", ".join(textos[k][v] for k, v in valores.items()))


def registrar_productos(nombres) -> int:
    """Agrega al catalogo los productos vendidos que todavia no estaban, en automatico.

    Asi el catalogo tiene todos los productos de la empresa y, al conectar un QuickBooks nuevo,
    se le pueden crear todos con su marca de gravable sin esperar al primer envio.
    """
    nombres = {str(n).strip()[:200] for n in nombres if str(n).strip()}
    with motor().begin() as c:
        ya = {f[0] for f in c.execute(sa.select(productos_t.c.nombre).where(productos_t.c.empresa_id == EMPRESA))}
        nuevos = sorted(nombres - ya)
        if nuevos:
            c.execute(productos_t.insert(), [{"empresa_id": EMPRESA, "nombre": n, "exento": None, "pagado_habitual": False,
                                              "actualizado_por": "Reportes de ventas", "actualizado": _ahora()} for n in nuevos])
    return len(nuevos)


def equivalencias() -> dict:
    """{"unidos": {alias: producto}, "descartados": {frozenset((a, b))}}"""
    with motor().connect() as c:
        filas = c.execute(sa.select(equivalencias_t).where(equivalencias_t.c.empresa_id == EMPRESA)).mappings().all()
    unidos = {f["alias"]: f["producto"] for f in filas if f["estado"] == "unido"}
    # si "A" se unio a "B" y luego "B" a "C", "A" va directo a "C"
    for alias in list(unidos):
        vistos, destino = {alias}, unidos[alias]
        while destino in unidos and destino not in vistos:
            vistos.add(destino)
            destino = unidos[destino]
        unidos[alias] = destino
    return {"unidos": unidos, "lista": [dict(f) for f in filas if f["estado"] == "unido"],
            "descartados": {frozenset((f["alias"], f["producto"])) for f in filas if f["estado"] == "distinto"}}


def decidir_equivalencia(alias: str, producto: str, unir: bool, usuario: str) -> None:
    alias, producto = str(alias).strip()[:200], str(producto).strip()[:200]
    if not alias or not producto or alias == producto:
        raise ValueError("Indique dos nombres distintos.")
    if unir and equivalencias()["unidos"].get(producto) == alias:
        raise ValueError(f"“{producto}” ya está unido a “{alias}”.")
    with motor().begin() as c:
        c.execute(equivalencias_t.delete().where((equivalencias_t.c.empresa_id == EMPRESA) & (
            ((equivalencias_t.c.alias == alias) & (equivalencias_t.c.producto == producto))
            | ((equivalencias_t.c.alias == producto) & (equivalencias_t.c.producto == alias))
            | ((equivalencias_t.c.alias == alias) & (equivalencias_t.c.estado == "unido") & sa.literal(unir)))))
        c.execute(equivalencias_t.insert().values(empresa_id=EMPRESA, alias=alias, producto=producto,
                                                  estado="unido" if unir else "distinto", por=usuario, fecha=_ahora()))
    anotar(usuario, "Unió dos nombres de producto" if unir else "Marcó dos productos como distintos", f"{alias} → {producto}")


def separar_equivalencia(alias: str, usuario: str) -> None:
    with motor().begin() as c:
        c.execute(equivalencias_t.delete().where((equivalencias_t.c.empresa_id == EMPRESA) & (equivalencias_t.c.alias == alias)
                                                 & (equivalencias_t.c.estado == "unido")))
    anotar(usuario, "Separó un nombre de producto", alias)


# ---------------- sistemas de ventas ----------------
def formatos() -> list[dict]:
    with motor().connect() as c:
        filas = c.execute(sa.select(formatos_t).where(formatos_t.c.empresa_id == EMPRESA).order_by(formatos_t.c.nombre)).mappings().all()
    return [{"nombre": f["nombre"], "mapeo": f["mapeo"], "por": f["creado_por"]} for f in filas]


def guardar_formato(nombre: str, mapeo: dict, usuario: str) -> None:
    nombre = str(nombre).strip()[:24]
    mapeo = {str(k): str(v) for k, v in (mapeo or {}).items() if v}
    if not nombre:
        raise ValueError("Póngale un nombre al sistema.")
    if nombre.lower() in ("nayax", "av360", "xmai", "qingo"):
        raise ValueError("Ese sistema ya viene con la aplicación.")
    if not mapeo.get("maquina") or not mapeo.get("producto") or not ({"total", "efectivo", "tarjeta"} & set(mapeo)):
        raise ValueError("Indique la máquina, el producto y un valor vendido.")
    with motor().begin() as c:
        c.execute(formatos_t.delete().where((formatos_t.c.empresa_id == EMPRESA) & (sa.func.lower(formatos_t.c.nombre) == nombre.lower())))
        c.execute(formatos_t.insert().values(empresa_id=EMPRESA, nombre=nombre, mapeo=mapeo, creado_por=usuario, creado=_ahora()))
    anotar(usuario, "Registró un sistema de ventas", nombre)


def borrar_formato(nombre: str, usuario: str) -> None:
    with motor().begin() as c:
        c.execute(formatos_t.delete().where((formatos_t.c.empresa_id == EMPRESA) & (formatos_t.c.nombre == nombre)))
    anotar(usuario, "Quitó un sistema de ventas", nombre)


# ---------------- usuarios ----------------
def _hash(clave: str, sal: str | None = None) -> str:
    sal = sal or secrets.token_hex(16)
    return f"pbkdf2${sal}${hashlib.pbkdf2_hmac('sha256', clave.encode(), bytes.fromhex(sal), 240_000).hex()}"


def _coincide(clave: str, guardado: str) -> bool:
    try:
        _, sal, _ = guardado.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(_hash(clave, sal), guardado)


def hay_usuarios() -> bool:
    with motor().connect() as c:
        return bool(c.execute(sa.select(sa.func.count()).select_from(usuarios).where(usuarios.c.activo.is_(True))).scalar())


def listar_usuarios() -> list[dict]:
    with motor().connect() as c:
        filas = c.execute(sa.select(usuarios).order_by(usuarios.c.id)).mappings().all()
    return [{"id": f["id"], "nombre": f["nombre"], "usuario": f["usuario"], "rol": f["rol"], "activo": bool(f["activo"])} for f in filas]


def usuario_por_id(uid: int) -> dict | None:
    with motor().connect() as c:
        f = c.execute(sa.select(usuarios).where((usuarios.c.id == uid) & usuarios.c.activo.is_(True))).mappings().first()
    return {"id": f["id"], "nombre": f["nombre"], "usuario": f["usuario"], "rol": f["rol"]} if f else None


def crear_usuario(nombre: str, usuario: str, clave: str, rol: str, por: str) -> None:
    nombre, usuario = str(nombre).strip()[:80], str(usuario).strip().lower()[:40]
    if not nombre or not usuario:
        raise ValueError("Faltan el nombre y el usuario.")
    if rol not in ROLES:
        raise ValueError("Ese rol no existe.")
    if len(clave or "") < 8:
        raise ValueError("La clave debe tener al menos 8 caracteres.")
    if not hay_usuarios() and rol != "admin":
        raise ValueError("El primer usuario debe ser administrador.")
    with motor().begin() as c:
        if c.execute(sa.select(usuarios.c.id).where(usuarios.c.usuario == usuario)).first():
            raise ValueError("Ese usuario ya existe.")
        c.execute(usuarios.insert().values(empresa_id=EMPRESA, nombre=nombre, usuario=usuario, clave_hash=_hash(clave),
                                           rol=rol, activo=True, creado=_ahora()))
    anotar(por, "Creó un usuario", f"{nombre} ({usuario}), {ROLES[rol]}")


def editar_usuario(uid: int, por: str, rol: str | None = None, activo: bool | None = None, clave: str | None = None) -> None:
    valores = {}
    if rol is not None:
        if rol not in ROLES:
            raise ValueError("Ese rol no existe.")
        valores["rol"] = rol
    if activo is not None:
        valores["activo"] = bool(activo)
    if clave:
        if len(clave) < 8:
            raise ValueError("La clave debe tener al menos 8 caracteres.")
        valores["clave_hash"] = _hash(clave)
    if not valores:
        return
    with motor().begin() as c:
        previa = c.execute(sa.select(usuarios).where(usuarios.c.id == uid)).mappings().first()
        if previa is None:
            raise ValueError("No existe ese usuario.")
        queda_admin = c.execute(sa.select(sa.func.count()).select_from(usuarios).where(
            (usuarios.c.rol == "admin") & usuarios.c.activo.is_(True) & (usuarios.c.id != uid))).scalar()
        deja_de_ser = previa["rol"] == "admin" and (valores.get("rol", "admin") != "admin" or valores.get("activo") is False)
        if deja_de_ser and not queda_admin:
            raise ValueError("Debe quedar al menos un administrador activo.")
        c.execute(usuarios.update().where(usuarios.c.id == uid).values(**valores))
    cambios = [f"rol {ROLES[valores['rol']]}" if "rol" in valores else "", "clave nueva" if "clave_hash" in valores else "",
               ("activado" if valores["activo"] else "desactivado") if "activo" in valores else ""]
    anotar(por, "Cambió un usuario", f"{previa['nombre']}: " + ", ".join(x for x in cambios if x))


def autenticar(usuario: str, clave: str) -> dict | None:
    with motor().connect() as c:
        f = c.execute(sa.select(usuarios).where((usuarios.c.usuario == str(usuario).strip().lower()) & usuarios.c.activo.is_(True))).mappings().first()
    if f is None:
        _hash(clave or "x", "00" * 16)   # mismo tiempo de respuesta exista o no el usuario
        return None
    return {"id": f["id"], "nombre": f["nombre"], "usuario": f["usuario"], "rol": f["rol"]} if _coincide(clave or "", f["clave_hash"]) else None


# ---------------- cierres ----------------
def guardar_cierre(anio: int, mes: int, res: dict, archivos: list[dict], usuario: str, envio: dict | None = None) -> dict:
    """Guarda (o reemplaza) el cierre de un mes con las reglas que tenia. Un cierre declarado no se toca."""
    R = {k: v for k, v in res["reglas"].items() if k != "_version"}
    version = res["reglas"].get("_version", {})
    pm = res["maquinas"]
    with motor().begin() as c:
        previo = c.execute(sa.select(cierres_t).where((cierres_t.c.empresa_id == EMPRESA) & (cierres_t.c.anio == anio)
                                                      & (cierres_t.c.mes == mes))).mappings().first()
        if previo is not None and previo["estado"] == "declarado":
            raise ValueError("Ese mes ya está marcado como declarado. Reábralo en Historial para cambiarlo.")
        # si se vuelve a guardar sin enviar, lo que hay en contabilidad ya no corresponde a este cierre
        valores = dict(estado="enviado" if envio else "guardado",
                       reglas_id=version.get("id"), reglas=R, resumen=res["pasos"], declaracion=res["declaracion"],
                       archivos=archivos, envio=envio, guardado_por=usuario, guardado=_ahora())
        if previo is None:
            cid = c.execute(cierres_t.insert().values(empresa_id=EMPRESA, anio=anio, mes=mes, **valores)).inserted_primary_key[0]
        else:
            cid = previo["id"]
            c.execute(cierres_t.update().where(cierres_t.c.id == cid).values(**valores))
            c.execute(cierre_maquinas.delete().where(cierre_maquinas.c.cierre_id == cid))
        c.execute(cierre_maquinas.insert(), [
            {"cierre_id": cid, "id_maquina": str(m.id_maquina or ""), "maquina": str(m.maquina)[:200], "ciudad": str(m.ciudad or ""),
             "jurisdiccion": str(m.jurisdiccion or ""), "ventas": float(m.ventas), "exentas": float(m.exentas),
             "pagadas": float(m.pagadas), "gravable": float(m.gravable)} for m in pm.itertuples(index=False)])
    anotar(usuario, "Envió un cierre a contabilidad" if envio else "Guardó un cierre", f"{mes:02d}/{anio}")
    return {"id": cid, "estado": valores["estado"]}


def cierres() -> list[dict]:
    with motor().connect() as c:
        filas = c.execute(sa.select(cierres_t).where(cierres_t.c.empresa_id == EMPRESA)
                          .order_by(cierres_t.c.anio.desc(), cierres_t.c.mes.desc())).mappings().all()
    salida = []
    for f in filas:
        d, envio = f["declaracion"] or {}, f["envio"] or {}
        salida.append({"id": f["id"], "anio": f["anio"], "mes": f["mes"], "estado": f["estado"],
                       "total_ventas": d.get("total_ventas"), "ventas_gravables": d.get("ventas_gravables"),
                       "impuesto": d.get("impuesto_total"), "locales": d.get("locales", []),
                       "impuesto_contabilidad": envio.get("impuesto"), "cuadra": envio.get("cuadra"),
                       "por": f["guardado_por"], "guardado": f["guardado"]})
    return salida


def cierre(cid: int) -> dict | None:
    with motor().connect() as c:
        f = c.execute(sa.select(cierres_t).where(cierres_t.c.id == cid)).mappings().first()
        if f is None:
            return None
        maqs = c.execute(sa.select(cierre_maquinas).where(cierre_maquinas.c.cierre_id == cid)).mappings().all()
    return {**{k: f[k] for k in ("id", "anio", "mes", "estado", "reglas", "resumen", "declaracion", "archivos", "envio")},
            "por": f["guardado_por"], "guardado": f["guardado"],
            "maquinas": [{k: m[k] for k in ("id_maquina", "maquina", "ciudad", "jurisdiccion", "ventas", "exentas", "pagadas", "gravable")} for m in maqs]}


def estado_cierre(cid: int, estado: str, usuario: str) -> None:
    if estado not in ("guardado", "enviado", "declarado"):
        raise ValueError("Ese estado no existe.")
    with motor().begin() as c:
        f = c.execute(sa.select(cierres_t).where(cierres_t.c.id == cid)).mappings().first()
        if f is None:
            raise ValueError("No existe ese cierre.")
        c.execute(cierres_t.update().where(cierres_t.c.id == cid).values(estado=estado))
    anotar(usuario, "Marcó un cierre como declarado" if estado == "declarado" else "Reabrió un cierre", f"{f['mes']:02d}/{f['anio']}")
