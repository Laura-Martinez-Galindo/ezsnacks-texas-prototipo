"""Lectura del vendor list de EzSnack (la lista de maquinas con su direccion)."""
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


def leer(fuente, nombre: str | None = None) -> pd.DataFrame:
    """Devuelve una fila por maquina vigente: id_maquina, locacion, direccion, ciudad, estado, zip, activa.

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
    for c in ("locacion", "activa", "estado", "zip"):
        if c not in df:
            df[c] = ""
    texto = df["id_asignado"].astype(str).str.strip()
    vigente = texto.str.fullmatch(r"(?i)ez\s*snack\s*#?\s*\d+")
    df = df[vigente].copy()
    df["id_maquina"] = df["id_asignado"].map(id_maquina)
    df["ciudad"] = df["ciudad"].map(_ciudad)
    df["locacion"] = df["locacion"].fillna("").astype(str).str.strip()
    df["direccion"] = df["direccion"].fillna("").astype(str).str.strip()
    df["activa"] = ~df["activa"].astype(str).str.strip().str.upper().isin(["N"])
    df = df.drop_duplicates("id_maquina", keep="first")
    df["estado"] = df["estado"].fillna("TX").astype(str).str.strip().replace({"": "TX", "nan": "TX"})
    df["zip"] = df["zip"].map(lambda z: "" if pd.isna(z) or str(z).strip() in ("", "nan") else str(z).split(".")[0].strip())
    return df[["id_maquina", "locacion", "direccion", "ciudad", "estado", "zip", "activa"]].reset_index(drop=True)
