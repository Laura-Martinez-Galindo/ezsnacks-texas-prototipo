"""Lectura de los reportes que descarga cada lector de tarjetas.

Cada sistema exporta un Excel distinto. Aqui se reconoce el formato por sus columnas y se
convierte a una sola tabla con las mismas columnas para todos:

    fuente, archivo, maquina, id_maquina, producto, cantidad,
    efectivo, tarjeta, cupones, cuenta, prepago, otros

Formatos reconocidos (septiembre de 2026, enviados por EzSnack Texas):
    Nayax   Dynamic Transactions Monitor, una fila por transaccion.
    AV360   Sales Tax Detail, una fila por maquina y producto.
    XMAI    Item Sales, una fila por maquina y producto, solo tarjeta.
    Qingo   Product sales statistics, una fila por maquina y producto, solo tarjeta.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

COLUMNAS = ["fuente", "archivo", "maquina", "id_maquina", "producto", "cantidad",
            "efectivo", "tarjeta", "cupones", "cuenta", "prepago", "otros",
            "barcode", "categoria", "costo", "utilidad", "impuesto"]
EXTRAS = ["barcode", "categoria", "costo", "utilidad", "impuesto"]
DINERO = ["efectivo", "tarjeta", "cupones", "cuenta", "prepago", "otros"]

# Columnas que identifican cada formato (sin espacios y en minusculas)
FIRMAS = {
    "Nayax": {"machine name", "product name", "settlement value (vend price)", "payment method (source)"},
    "AV360": {"machine", "product", "quantity sold", "cash", "credit", "coupon"},
    "XMAI": {"machine", "item name", "items sold", "sales revenue"},
    "Qingo": {"machine", "product name", "sales quantity", "sales amount ($)"},
}


# Para reportes de otros sistemas o formatos nuevos: palabras con las que se reconoce cada campo
CAMPOS = {
    "maquina": ["machine name", "machine", "maquina", "máquina", "device name", "device", "kiosk", "location", "asset"],
    "producto": ["product name", "item name", "product", "item", "producto", "articulo", "artículo", "article", "description", "sku"],
    "cantidad": ["quantity sold", "sales quantity", "items sold", "quantity", "qty", "cantidad", "units", "vends"],
    "efectivo": ["cash sales", "cash", "efectivo"],
    "tarjeta": ["credit sales", "card sales", "cashless", "credit", "card", "tarjeta"],
    "cupones": ["coupon sales", "coupons", "coupon", "cupones", "cupon"],
    "total": ["settlement value", "transaction amount", "sales revenue", "sales amount", "total sales", "net sales",
              "revenue", "amount", "total", "sales", "valor", "monto", "ventas"],
    "metodo": ["payment method", "payment type", "tender", "metodo de pago", "método de pago", "payment"],
}
NOMBRES_CAMPOS = {"maquina": "Máquina", "producto": "Producto", "cantidad": "Cantidad", "efectivo": "Efectivo",
                  "tarjeta": "Tarjeta", "cupones": "Cupones", "total": "Total vendido", "metodo": "Forma de pago"}


class FormatoDesconocido(ValueError):
    def __init__(self, mensaje: str, columnas: list[str] | None = None, mapeo: dict | None = None):
        super().__init__(mensaje)
        self.columnas = columnas or []
        self.mapeo = mapeo or {}


@dataclass
class Lectura:
    archivo: str
    fuente: str
    filas: pd.DataFrame
    leidas: int = 0
    descartadas: dict = field(default_factory=dict)
    periodo: str = ""
    generico: bool = False                              # leido por reconocimiento de columnas
    columnas: list = field(default_factory=list)        # columnas del archivo
    mapeo: dict = field(default_factory=dict)           # campo -> columna usada


def id_maquina(nombre) -> str | None:
    """'EzSnack 146 - North American university' -> '146'."""
    m = re.search(r"ez\s*snack\s*#?\s*(\d+)", str(nombre or ""), re.I)
    return m.group(1) if m else None


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(r"[$,\s]", "", regex=True).replace({"": None, "nan": None, "None": None}),
                         errors="coerce").fillna(0.0)


def _limpiar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    return df


def _abrir(fuente, nombre: str) -> list[pd.DataFrame]:
    """Devuelve las primeras filas crudas de cada hoja (sin encabezado) para buscar el formato."""
    if nombre.lower().endswith(".csv"):
        if hasattr(fuente, "seek"):
            fuente.seek(0)
        return [pd.read_csv(fuente, header=None, dtype=str)]
    if hasattr(fuente, "seek"):
        fuente.seek(0)
    hojas = pd.read_excel(fuente, sheet_name=None, header=None, dtype=object)
    return list(hojas.values())


def _buscar_encabezado(crudo: pd.DataFrame) -> tuple[str, int] | None:
    for i in range(min(12, len(crudo))):
        celdas = {re.sub(r"\s+", " ", str(c)).strip().lower() for c in crudo.iloc[i].tolist() if pd.notna(c)}
        for sistema, firma in FIRMAS.items():
            if firma <= celdas:
                return sistema, i
    return None


def _periodo(crudo: pd.DataFrame, fila_encabezado: int) -> str:
    textos = " ".join(str(c) for i in range(fila_encabezado) for c in crudo.iloc[i].tolist() if pd.notna(c))
    fechas = re.findall(r"(\d{1,4}[/-]\d{1,2}[/-]\d{1,4})", textos)
    return f"{fechas[0]} a {fechas[1]}" if len(fechas) >= 2 else ""


def _norm(t) -> str:
    return re.sub(r"[^a-z0-9áéíóúñ$ ]+", " ", str(t).lower()).strip()


def proponer_mapeo(columnas: list[str]) -> dict:
    """Propone que columna corresponde a cada campo, por el parecido del nombre."""
    puntajes = []
    for col in columnas:
        n = _norm(col)
        if not n or n == "nan":
            continue
        for campo, palabras in CAMPOS.items():
            for i, palabra in enumerate(palabras):
                if n == palabra:
                    puntajes.append((300 - i, campo, col))
                elif re.search(rf"\b{re.escape(palabra)}\b", n):
                    puntajes.append((200 - i - len(n) / 10, campo, col))
    mapeo, usadas = {}, set()
    for _, campo, col in sorted(puntajes, key=lambda x: -x[0]):
        if campo not in mapeo and col not in usadas:
            mapeo[campo] = col
            usadas.add(col)
    return mapeo


def _encabezado_generico(crudo: pd.DataFrame, mapeo: dict | None) -> tuple[int, dict] | None:
    mejor = None
    for i in range(min(15, len(crudo))):
        cols = [re.sub(r"\s+", " ", str(c)).strip() for c in crudo.iloc[i].tolist() if pd.notna(c)]
        if mapeo:
            if all(v in cols for v in mapeo.values() if v):
                return i, mapeo
            continue
        m = proponer_mapeo(cols)
        if "maquina" in m and "producto" in m and (mejor is None or len(m) > len(mejor[1])):
            mejor = (i, m)
    return mejor


def _generico(df: pd.DataFrame, mapeo: dict, fuente: str) -> Lectura:
    """Lee un reporte de formato no conocido con las columnas indicadas en el mapeo."""
    m = {k: v for k, v in mapeo.items() if v and v in df.columns}
    if "maquina" not in m or "producto" not in m or not ({"total", "efectivo", "tarjeta"} & set(m)):
        raise FormatoDesconocido("Faltan columnas: máquina, producto y un valor vendido.", list(df.columns), m)
    leidas = len(df)
    df, totales = _filas_validas(df, m["maquina"], m["producto"])
    cero = pd.Series(0.0, index=df.index)
    total = _num(df[m["total"]]) if "total" in m else None
    efectivo = _num(df[m["efectivo"]]) if "efectivo" in m else None
    tarjeta = _num(df[m["tarjeta"]]) if "tarjeta" in m else None
    cupones = _num(df[m["cupones"]]) if "cupones" in m else cero
    if efectivo is None and tarjeta is None:
        if "metodo" in m:  # una fila por venta, con la forma de pago
            es_efectivo = df[m["metodo"]].astype(str).str.lower().str.contains("cash|efectivo")
            efectivo, tarjeta = total.where(es_efectivo, 0.0), total.where(~es_efectivo, 0.0)
        else:              # solo hay un total: se toma como tarjeta
            efectivo, tarjeta = cero, total
    elif efectivo is None:
        efectivo = (total - tarjeta - cupones).clip(lower=0) if total is not None else cero
    elif tarjeta is None:
        tarjeta = (total - efectivo - cupones).clip(lower=0) if total is not None else cero
    cant = _num(df[m["cantidad"]]) if "cantidad" in m else pd.Series(1.0, index=df.index)
    sin_valor = (efectivo + tarjeta + cupones) <= 0
    filas = _salida(fuente, df[m["maquina"]][~sin_valor], df[m["producto"]][~sin_valor], cant[~sin_valor],
                    efectivo=efectivo[~sin_valor], tarjeta=tarjeta[~sin_valor], cupones=cupones[~sin_valor])
    return Lectura("", fuente, filas, leidas, {"filas de total o vacias": totales, "filas sin valor": int(sin_valor.sum())},
                   generico=True, columnas=[str(c) for c in df.columns], mapeo=m)


def leer(fuente, nombre: str | None = None, mapeo: dict | None = None) -> Lectura:
    """Lee un reporte. Si no es de un lector conocido, reconoce las columnas por su nombre.

    Con `mapeo` (campo -> columna) se usa ese mapeo en lugar del reconocimiento automatico.
    """
    nombre = nombre or getattr(fuente, "name", None) or str(fuente)
    archivo = Path(str(nombre)).name
    if isinstance(fuente, (str, Path)):
        fuente = io.BytesIO(Path(fuente).read_bytes())
    hojas = _abrir(fuente, nombre)

    def terminar(lectura: Lectura, crudo, fila) -> Lectura:
        lectura.archivo = archivo
        lectura.filas["archivo"] = archivo
        lectura.periodo = _periodo(crudo, fila)
        return lectura

    def tabla(crudo, fila) -> pd.DataFrame:
        df = crudo.iloc[fila + 1:].copy()
        df.columns = crudo.iloc[fila].tolist()
        return _limpiar_columnas(df).reset_index(drop=True)

    if not mapeo:
        for crudo in hojas:
            hallado = _buscar_encabezado(crudo)
            if hallado:
                sistema, fila = hallado
                lector = {"Nayax": _nayax, "AV360": _av360, "XMAI": _xmai, "Qingo": _qingo}[sistema]
                return terminar(lector(tabla(crudo, fila)), crudo, fila)
    columnas: list[str] = []
    for crudo in hojas:
        hallado = _encabezado_generico(crudo, mapeo)
        if hallado:
            fila, m = hallado
            df = tabla(crudo, fila)
            df = df.loc[:, [c for c in df.columns if c and c != "nan"]]
            return terminar(_generico(df, m, Path(archivo).stem[:24]), crudo, fila)
        if not columnas and len(crudo):
            columnas = [str(c) for c in crudo.iloc[0].tolist() if pd.notna(c)]
    raise FormatoDesconocido(f"No se reconocieron las columnas de {archivo}. Indique cuál es cada una.",
                             columnas, proponer_mapeo(columnas))


def _salida(fuente: str, maquina, producto, cantidad, **dinero) -> pd.DataFrame:
    out = pd.DataFrame({"fuente": fuente, "maquina": maquina.astype(str).str.strip(),
                        "producto": producto.astype(str).str.strip(), "cantidad": cantidad})
    for c in DINERO:
        out[c] = dinero.get(c, 0.0)
    for c in EXTRAS:  # datos que solo traen algunos lectores
        out[c] = dinero.get(c)
    out["id_maquina"] = out["maquina"].map(id_maquina)
    out["archivo"] = ""
    return out[COLUMNAS]


def _texto(df: pd.DataFrame, col: str):
    if col not in df:
        return None
    return df[col].map(lambda v: None if pd.isna(v) or not str(v).strip() else str(v).strip())


def _filas_validas(df: pd.DataFrame, col_maquina: str, col_producto: str) -> tuple[pd.DataFrame, int]:
    """Quita filas de totales o vacias (sin maquina o sin producto)."""
    ok = df[col_maquina].notna() & df[col_producto].notna() & (df[col_maquina].astype(str).str.strip() != "")
    return df[ok], int((~ok).sum())


def _nayax(df: pd.DataFrame) -> Lectura:
    leidas = len(df)
    df, totales = _filas_validas(df, "Machine Name", "Product Name")
    valor = _num(df["Settlement Value (Vend Price)"])
    declinadas = valor <= 0  # tarjeta rechazada o venta anulada: no se cobro nada
    df, valor = df[~declinadas], valor[~declinadas]
    cant = _num(df["Quantity"]) if "Quantity" in df else pd.Series(0.0, index=df.index)
    cant = cant.where(cant > 0, 1.0)  # Nayax deja la cantidad vacia cuando es una unidad
    metodo = df["Payment Method (Source)"].astype(str).str.lower()
    es_efectivo = metodo.str.startswith("cash")
    es_prepago = metodo.str.startswith("prepaid")
    es_otro = metodo.str.startswith("monyx")
    es_tarjeta = ~(es_efectivo | es_prepago | es_otro)
    filas = _salida("Nayax", df["Machine Name"], df["Product Name"], cant,
                    efectivo=valor.where(es_efectivo, 0.0), tarjeta=valor.where(es_tarjeta, 0.0),
                    prepago=valor.where(es_prepago, 0.0), otros=valor.where(es_otro, 0.0))
    return Lectura("", "Nayax", filas, leidas, {"filas de total o vacias": totales,
                                                "transacciones rechazadas (valor 0)": int(declinadas.sum())})


def _av360(df: pd.DataFrame) -> Lectura:
    leidas = len(df)
    df, totales = _filas_validas(df, "Machine", "Product")
    filas = _salida("AV360", df["Machine"], df["Product"], _num(df["Quantity Sold"]),
                    efectivo=_num(df["Cash"]), tarjeta=_num(df["Credit"]), cupones=_num(df["Coupon"]),
                    cuenta=_num(df["Account"]) if "Account" in df else 0.0,
                    impuesto=_num(df["Tax"]) if "Tax" in df else None)
    return Lectura("", "AV360", filas, leidas, {"filas de total o vacias": totales})


def _xmai(df: pd.DataFrame) -> Lectura:
    leidas = len(df)
    df, totales = _filas_validas(df, "Machine", "Item Name")
    filas = _salida("XMAI", df["Machine"], df["Item Name"], _num(df["Items Sold"]),
                    tarjeta=_num(df["Sales revenue"]),  # XMAI solo recibe tarjeta
                    barcode=_texto(df, "Barcode"), categoria=_texto(df, "Item Category"),
                    costo=_num(df["Cost price"]) * _num(df["Items Sold"]) if "Cost price" in df else None,
                    utilidad=_num(df["Profit"]) if "Profit" in df else None)
    return Lectura("", "XMAI", filas, leidas, {"filas de total o vacias": totales})


def _qingo(df: pd.DataFrame) -> Lectura:
    leidas = len(df)
    df, totales = _filas_validas(df, "Machine", "Product Name")
    monto = _num(df["Transaction Amount ($)"]) if "Transaction Amount ($)" in df else _num(df["Sales Amount ($)"])
    filas = _salida("Qingo", df["Machine"], df["Product Name"], _num(df["Sales Quantity"]),
                    tarjeta=monto,  # Qingo solo recibe tarjeta
                    barcode=_texto(df, "Product Barcode"), categoria=_texto(df, "Product Category"),
                    costo=_num(df["Cost amount ($)"]) if "Cost amount ($)" in df else None,
                    utilidad=_num(df["Gross profit"]) if "Gross profit" in df else None)
    return Lectura("", "Qingo", filas, leidas, {"filas de total o vacias": totales})
