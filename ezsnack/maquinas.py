"""Lectura del vendor list de EzSnack (la lista de maquinas con su direccion y su socio)."""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd

from .lectores import id_maquina

# Nombre de columna en el vendor list -> nombre interno
COLUMNAS = {
    "assigned id": "id_asignado",
    "company": "locacion",
    "address": "direccion",
    "city": "ciudad",
    "state": "estado",
    "zip": "zip",
    "commision to": "comision_a",
    "commission to": "comision_a",
    "active": "activa",
}
OBLIGATORIAS = {"id_asignado", "direccion", "ciudad"}

# Correcciones de ciudades mal escritas en la lista
CIUDADES = {"stafdford": "Stafford", "sugarland": "Sugar Land", "rosemberg": "Rosenberg"}


def _ciudad(valor) -> str:
    t = re.sub(r"\s+", " ", str(valor or "")).strip()
    if t.lower() in ("", "nan", "none") or re.fullmatch(r"[\d.]+", t):
        return ""
    return CIUDADES.get(t.lower(), t.title())


def _socio(valor) -> str:
    t = str(valor or "").strip()
    if t.lower() in ("", "nan", "none"):
        return ""
    return {"procity": "ProCity"}.get(t.lower(), t)


def leer(fuente, nombre: str | None = None) -> pd.DataFrame:
    """Devuelve una fila por maquina vigente: id_maquina, locacion, direccion, ciudad, comision_a, activa.

    Las filas marcadas como "old" o "ex" son ubicaciones anteriores de la misma maquina y se ignoran,
    tal como las usa la empresa para guardar el historial de locaciones.
    """
    nombre = nombre or getattr(fuente, "name", "") or str(fuente)
    if isinstance(fuente, (str, Path)):
        fuente = io.BytesIO(Path(fuente).read_bytes())
    if hasattr(fuente, "seek"):
        fuente.seek(0)
    df = pd.read_csv(fuente, dtype=object) if str(nombre).lower().endswith(".csv") else pd.read_excel(fuente, dtype=object)
    df = df.rename(columns={c: COLUMNAS.get(re.sub(r"\s+", " ", str(c)).strip().lower(), c) for c in df.columns})
    faltan = OBLIGATORIAS - set(df.columns)
    if faltan:
        raise ValueError("La lista de máquinas no tiene las columnas Assigned id, Address y City. "
                         "Use el vendor list de la empresa.")
    for c in ("locacion", "comision_a", "activa", "estado", "zip"):
        if c not in df:
            df[c] = ""
    texto = df["id_asignado"].astype(str).str.strip()
    vigente = texto.str.fullmatch(r"(?i)ez\s*snack\s*#?\s*\d+")
    df = df[vigente].copy()
    df["id_maquina"] = df["id_asignado"].map(id_maquina)
    df["ciudad"] = df["ciudad"].map(_ciudad)
    df["comision_a"] = df["comision_a"].map(_socio)
    df["locacion"] = df["locacion"].fillna("").astype(str).str.strip()
    df["direccion"] = df["direccion"].fillna("").astype(str).str.strip()
    df["activa"] = ~df["activa"].astype(str).str.strip().str.upper().isin(["N"])
    df = df.drop_duplicates("id_maquina", keep="first")
    return df[["id_maquina", "locacion", "direccion", "ciudad", "comision_a", "activa"]].reset_index(drop=True)
