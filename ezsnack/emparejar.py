"""Emparejar textos (de reportes o recibos) con los productos registrados."""
from __future__ import annotations

import json
import re
from pathlib import Path

from rapidfuzz import fuzz, process

ALIAS_FILE = Path("config/alias.json")
UMBRAL_SEGURO = 90   # desde aqui se acepta solo
UMBRAL_DUDOSO = 65   # entre este y el seguro: se pregunta a Humberto

PATRON_IMPUESTO = re.compile(r"\b(SALES\s*TAX|TAX|TFL\s*TAX|IVA|IMPUESTO)\b", re.IGNORECASE)


def normalizar(texto: str) -> str:
    texto = str(texto or "").upper()
    texto = re.sub(r"\b\d{6,}\b", " ", texto)      # codigos de barras / SKU largos
    texto = re.sub(r"[$#*]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def cargar_alias() -> dict[str, str]:
    if not ALIAS_FILE.exists():
        return {}
    datos = json.loads(ALIAS_FILE.read_text(encoding="utf-8"))
    return {normalizar(k): v for k, v in datos.items() if not k.startswith("_")}


def guardar_alias(texto: str, producto: str) -> None:
    datos = json.loads(ALIAS_FILE.read_text(encoding="utf-8")) if ALIAS_FILE.exists() else {}
    datos[normalizar(texto)] = producto
    ALIAS_FILE.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")


def es_impuesto(texto: str) -> bool:
    return bool(PATRON_IMPUESTO.search(str(texto or "")))


def emparejar(texto: str, productos: list[str], alias: dict[str, str] | None = None) -> tuple[str | None, int, str]:
    """Devuelve (producto, puntaje 0-100, estado) con estado en: alias, seguro, dudoso, sin_coincidencia."""
    alias = alias if alias is not None else cargar_alias()
    clave = normalizar(texto)
    if clave in alias:
        return alias[clave], 100, "alias"
    if not productos or not clave:
        return None, 0, "sin_coincidencia"
    mapa = {normalizar(p): p for p in productos}
    mejor = process.extractOne(clave, list(mapa), scorer=fuzz.WRatio)
    if not mejor:
        return None, 0, "sin_coincidencia"
    nombre_norm, puntaje, _ = mejor
    puntaje = int(round(puntaje))
    # La marca (primera palabra) debe parecerse: evita confundir "Cheetos 1 oz" con "Doritos 1 oz"
    if fuzz.ratio(clave.split()[0], nombre_norm.split()[0]) < 70:
        puntaje = min(puntaje, UMBRAL_DUDOSO - 1)
    if puntaje >= UMBRAL_SEGURO:
        return mapa[nombre_norm], puntaje, "seguro"
    if puntaje >= UMBRAL_DUDOSO:
        return mapa[nombre_norm], puntaje, "dudoso"
    return None, puntaje, "sin_coincidencia"
