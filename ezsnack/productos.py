"""Reconocimiento de productos por nombre.

Los lectores escriben el mismo producto de formas distintas ("Diet Dr. Pepper 16.9 fl. oz.",
"12oz - Diet Dr. Pepper"). Aqui se normalizan los nombres, se proponen los productos exentos
(agua sin endulzar) y se buscan, entre lo vendido, los productos de la lista de compras hechas
por fuera con impuesto ya pagado.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

PALABRAS_AGUA = re.compile(r"\b(water|agua)\b", re.I)
# Bebidas que dicen "water" pero llevan azucar o endulzante y por eso pagan impuesto
NO_EXENTAS = re.compile(r"vitamin|coconut|tonic|flavored|kiwi|strawberry|lemonade|\bjuice\b|bubly", re.I)
TAMANO = re.compile(r"(\d+(?:\.\d+)?)\s*(?:fl\.?\s*)?(?:oz|onzas|ounce|ml|g)\b", re.I)
VACIAS = {"the", "and", "with", "de", "con", "fl", "oz", "pack", "bottle", "can", "cup"}


def normalizar(texto: str) -> str:
    t = str(texto or "").lower()
    t = t.replace("’", "'").replace("'s", "s").replace("'", "")
    t = re.sub(r"(\d)\s*(fl\.?\s*)?oz\.?", r"\1 oz", t)
    t = re.sub(r"[^a-z0-9.]+", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tamano(texto: str) -> float | None:
    m = TAMANO.search(str(texto or ""))
    return float(m.group(1)) if m else None


def palabras(texto: str) -> list[str]:
    return [p for p in normalizar(re.sub(TAMANO, " ", str(texto or ""))).split()
            if p not in VACIAS and not re.fullmatch(r"[\d.]+", p)]


def clave(texto: str) -> str:
    """Clave para juntar nombres que son el mismo producto escrito distinto."""
    t = tamano(texto)
    base = " ".join(sorted(set(palabras(texto))))
    return f"{base} {t:g}oz" if t else base


def es_exento(producto: str) -> bool:
    """Propone como exenta el agua sin endulzar. El usuario confirma la lista."""
    return bool(PALABRAS_AGUA.search(str(producto))) and not NO_EXENTAS.search(str(producto))


def _contiene(palabra: str, del_producto: list[str]) -> bool:
    for q in del_producto:
        if palabra == q or fuzz.ratio(palabra, q) >= 88:
            return True
        # plural o posesivo: "captain" contra "captains"
        if len(palabra) >= 4 and q.startswith(palabra) and len(q) - len(palabra) <= 2:
            return True
    return False


def coincide(buscado: str, producto: str) -> str | None:
    """Dice si un renglon de la lista de compras corresponde a un producto vendido.

    Devuelve "seguro", "dudoso" o None. Todas las palabras de la lista deben estar en el nombre
    del producto. Si la lista trae tamano ("16 oz"), el producto debe tener el mismo tamano con
    una onza de tolerancia (16 coincide con 16.9, no con 12). Si el producto no dice su tamano,
    queda como dudoso para que el usuario decida.
    """
    pb, pp = palabras(buscado), palabras(producto)
    if not pb or not all(_contiene(p, pp) for p in pb):
        return None
    tb, tp = tamano(buscado), tamano(producto)
    if tb is None:
        return "seguro"
    if tp is None:
        return "dudoso"
    return "seguro" if abs(tb - tp) <= 1.0 else None


def leer_lista(fuente, nombre: str | None = None) -> list[str]:
    """Lee el Excel con la columna Product de lo comprado por fuera con impuesto pagado."""
    nombre = nombre or getattr(fuente, "name", "") or str(fuente)
    if isinstance(fuente, (str, Path)):
        fuente = io.BytesIO(Path(fuente).read_bytes())
    if hasattr(fuente, "seek"):
        fuente.seek(0)
    df = pd.read_csv(fuente, dtype=str) if str(nombre).lower().endswith(".csv") else pd.read_excel(fuente, dtype=str)
    col = next((c for c in df.columns if str(c).strip().lower() in ("product", "products", "producto", "productos", "item")), None)
    if col is None:
        if len(df.columns) == 1:
            col = df.columns[0]
        else:
            raise ValueError("La lista de compras con impuesto pagado debe tener una columna llamada Product.")
    return [t.strip() for t in df[col].dropna().astype(str) if t.strip()]


def buscar_pagados(lista: list[str], vendidos: pd.DataFrame) -> pd.DataFrame:
    """Cruza la lista contra los productos vendidos (tabla con columna producto y ventas).

    Devuelve una fila por producto vendido que coincide: buscado, producto, ventas, estado.
    """
    filas = []
    for buscado in lista:
        hallados = 0
        for prod, ventas in zip(vendidos["producto"], vendidos["ventas"]):
            estado = coincide(buscado, prod)
            if estado:
                filas.append({"buscado": buscado, "producto": prod, "ventas": round(float(ventas), 2), "estado": estado})
                hallados += 1
        if not hallados:
            filas.append({"buscado": buscado, "producto": None, "ventas": 0.0, "estado": "sin_ventas"})
    return pd.DataFrame(filas, columns=["buscado", "producto", "ventas", "estado"])
