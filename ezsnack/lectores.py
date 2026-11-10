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
            "efectivo", "tarjeta", "cupones", "cuenta", "prepago", "otros"]
DINERO = ["efectivo", "tarjeta", "cupones", "cuenta", "prepago", "otros"]

# Columnas que identifican cada formato (sin espacios y en minusculas)
FIRMAS = {
    "Nayax": {"machine name", "product name", "settlement value (vend price)", "payment method (source)"},
    "AV360": {"machine", "product", "quantity sold", "cash", "credit", "coupon"},
    "XMAI": {"machine", "item name", "items sold", "sales revenue"},
    "Qingo": {"machine", "product name", "sales quantity", "sales amount ($)"},
}


class FormatoDesconocido(ValueError):
    pass


@dataclass
class Lectura:
    archivo: str
    fuente: str
    filas: pd.DataFrame
    leidas: int = 0
    descartadas: dict = field(default_factory=dict)
    periodo: str = ""


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


def leer(fuente, nombre: str | None = None) -> Lectura:
    """Lee un reporte de cualquier lector reconocido."""
    nombre = nombre or getattr(fuente, "name", None) or str(fuente)
    if isinstance(fuente, (str, Path)):
        fuente = io.BytesIO(Path(fuente).read_bytes())
    for crudo in _abrir(fuente, nombre):
        hallado = _buscar_encabezado(crudo)
        if not hallado:
            continue
        sistema, fila = hallado
        df = crudo.iloc[fila + 1:].copy()
        df.columns = crudo.iloc[fila].tolist()
        df = _limpiar_columnas(df).reset_index(drop=True)
        lectura = {"Nayax": _nayax, "AV360": _av360, "XMAI": _xmai, "Qingo": _qingo}[sistema](df)
        lectura.archivo = Path(str(nombre)).name
        lectura.filas["archivo"] = lectura.archivo
        lectura.periodo = _periodo(crudo, fila)
        return lectura
    raise FormatoDesconocido(
        f"No se reconoce el formato de {Path(str(nombre)).name}. Se leen los reportes de Nayax "
        "(Dynamic Transactions Monitor), AV360 (Sales Tax Detail), XMAI (Item Sales) y Qingo (Product sales statistics).")


def _salida(fuente: str, maquina, producto, cantidad, **dinero) -> pd.DataFrame:
    out = pd.DataFrame({"fuente": fuente, "maquina": maquina.astype(str).str.strip(),
                        "producto": producto.astype(str).str.strip(), "cantidad": cantidad})
    for c in DINERO:
        out[c] = dinero.get(c, 0.0)
    out["id_maquina"] = out["maquina"].map(id_maquina)
    out["archivo"] = ""
    return out[COLUMNAS]


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
                    cuenta=_num(df["Account"]) if "Account" in df else 0.0)
    return Lectura("", "AV360", filas, leidas, {"filas de total o vacias": totales})


def _xmai(df: pd.DataFrame) -> Lectura:
    leidas = len(df)
    df, totales = _filas_validas(df, "Machine", "Item Name")
    filas = _salida("XMAI", df["Machine"], df["Item Name"], _num(df["Items Sold"]),
                    tarjeta=_num(df["Sales revenue"]))  # XMAI solo recibe tarjeta
    return Lectura("", "XMAI", filas, leidas, {"filas de total o vacias": totales})


def _qingo(df: pd.DataFrame) -> Lectura:
    leidas = len(df)
    df, totales = _filas_validas(df, "Machine", "Product Name")
    monto = _num(df["Transaction Amount ($)"]) if "Transaction Amount ($)" in df else _num(df["Sales Amount ($)"])
    filas = _salida("Qingo", df["Machine"], df["Product Name"], _num(df["Sales Quantity"]),
                    tarjeta=monto)  # Qingo solo recibe tarjeta
    return Lectura("", "Qingo", filas, leidas, {"filas de total o vacias": totales})
