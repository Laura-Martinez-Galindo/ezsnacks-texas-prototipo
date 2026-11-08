"""Une los reportes de ventas de los distintos lectores (Nayax, AB360, otros)
con el vendor list, y deja las ventas listas por maquina y producto.

No calcula el impuesto oficial: eso lo hace QuickBooks con la direccion de cada maquina.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .emparejar import cargar_alias, emparejar

COLUMNAS_FILE = Path("config/columnas.json")


def _mapa(sistema: str) -> dict[str, str]:
    columnas = json.loads(COLUMNAS_FILE.read_text(encoding="utf-8"))
    if sistema not in columnas:
        raise ValueError(f"No hay mapeo de columnas para '{sistema}' en {COLUMNAS_FILE}")
    return columnas[sistema]


def _leer_tabla(archivo) -> pd.DataFrame:
    nombre = getattr(archivo, "name", str(archivo)).lower()
    if nombre.endswith(".csv"):
        return pd.read_csv(archivo)
    return pd.read_excel(archivo)


def extraer_id_maquina(texto) -> str | None:
    """'EzSnack 158 - 1823 Haden Rd - Triac Electric' -> '158'."""
    texto = str(texto or "")
    m = re.search(r"EzSnack\s*#?\s*([A-Za-z]?\d+)", texto, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.match(r"\s*#?([A-Za-z]?\d+)\b", texto)
    return m.group(1).upper() if m else None


def leer_vendor_list(archivo) -> pd.DataFrame:
    mapa = _mapa("vendor_list")
    df = _leer_tabla(archivo)
    faltan = [c for c in mapa.values() if c not in df.columns]
    if faltan:
        raise ValueError(f"Al vendor list le faltan las columnas: {faltan}")
    df = df.rename(columns={v: k for k, v in mapa.items()}).rename(columns={"sistema": "sistema_lista"})
    df["id_maquina"] = df["id_maquina"].astype(str).str.strip().str.upper()
    df["pct_comision"] = pd.to_numeric(df["pct_comision"], errors="coerce").fillna(0)
    df["socio"] = df["socio"].fillna("").astype(str).str.strip()
    if "Jurisdiccion" in df.columns:  # columna opcional, solo para la vista previa
        df = df.rename(columns={"Jurisdiccion": "jurisdiccion"})
    return df


def leer_ventas(archivo, sistema: str) -> pd.DataFrame:
    mapa = _mapa(sistema)
    df = _leer_tabla(archivo)
    obligatorias = ["maquina", "producto", "cantidad", "valor"]
    faltan = [mapa[c] for c in obligatorias if mapa[c] not in df.columns]
    if faltan:
        raise ValueError(
            f"El archivo de {sistema} no tiene las columnas {faltan}. "
            f"Columnas encontradas: {list(df.columns)}. Ajuste config/columnas.json."
        )
    out = pd.DataFrame({
        "sistema": sistema,
        "maquina_texto": df[mapa["maquina"]].astype(str),
        "producto_reporte": df[mapa["producto"]].astype(str).str.strip(),
        "cantidad": pd.to_numeric(df[mapa["cantidad"]], errors="coerce").fillna(0),
        "valor": pd.to_numeric(
            df[mapa["valor"]].astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce"
        ).fillna(0),
    })
    out["medio_pago"] = df[mapa["medio_pago"]].astype(str) if mapa.get("medio_pago") in df.columns else ""
    out["fecha"] = pd.to_datetime(df[mapa["fecha"]], errors="coerce") if mapa.get("fecha") in df.columns else pd.NaT
    out["id_maquina"] = out["maquina_texto"].map(extraer_id_maquina)
    return out


def consolidar(ventas: list[pd.DataFrame], vendor: pd.DataFrame, productos: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (detalle, problemas).

    detalle: una fila por venta, con la maquina del vendor list y el producto registrado.
    problemas: maquinas que no estan en el vendor list y productos que no se reconocen.
    """
    todo = pd.concat(ventas, ignore_index=True)
    detalle = todo.merge(vendor, on="id_maquina", how="left", indicator=True)

    alias = cargar_alias()
    unicos = detalle["producto_reporte"].dropna().unique()
    empate = {t: emparejar(t, productos, alias) for t in unicos}
    detalle["producto"] = detalle["producto_reporte"].map(lambda t: empate[t][0])
    detalle["puntaje"] = detalle["producto_reporte"].map(lambda t: empate[t][1])
    detalle["estado_producto"] = detalle["producto_reporte"].map(lambda t: empate[t][2])

    problemas = []
    sin_maquina = detalle[detalle["_merge"] == "left_only"]
    for texto, grupo in sin_maquina.groupby("maquina_texto"):
        problemas.append({
            "tipo": "Maquina no esta en el vendor list", "texto": texto,
            "sugerencia": "", "lineas": len(grupo), "valor": round(grupo["valor"].sum(), 2),
        })
    revisar = detalle[detalle["estado_producto"].isin(["dudoso", "sin_coincidencia"])]
    for texto, grupo in revisar.groupby("producto_reporte"):
        problemas.append({
            "tipo": "Producto no reconocido" if grupo["estado_producto"].iloc[0] == "sin_coincidencia" else "Producto dudoso",
            "texto": texto, "sugerencia": grupo["producto"].iloc[0] or "",
            "lineas": len(grupo), "valor": round(grupo["valor"].sum(), 2),
        })
    detalle = detalle.drop(columns="_merge")
    return detalle, pd.DataFrame(problemas, columns=["tipo", "texto", "sugerencia", "lineas", "valor"])


def resumen_por_maquina(detalle: pd.DataFrame) -> pd.DataFrame:
    """Ventas listas para enviar: una fila por maquina y producto reconocido."""
    ok = detalle[detalle["producto"].notna() & detalle["direccion"].notna()]
    return (
        ok.groupby(["id_maquina", "locacion", "direccion", "ciudad", "estado", "zip", "producto"], dropna=False)
        .agg(cantidad=("cantidad", "sum"), valor=("valor", "sum"))
        .reset_index()
    )


def vista_previa_impuesto(detalle: pd.DataFrame, gravables: dict[str, bool], tarifas: dict[str, float]) -> pd.DataFrame:
    """Estimado para que Humberto compare. El impuesto oficial lo calcula QuickBooks."""
    if "jurisdiccion" not in detalle.columns:
        return pd.DataFrame()
    d = detalle[detalle["producto"].notna()].copy()
    d["gravable"] = d["producto"].map(lambda p: gravables.get(p, True))
    filas = []
    for jur, g in d.groupby("jurisdiccion"):
        total = g["valor"].sum()
        grav = g.loc[g["gravable"], "valor"].sum()
        tasa = tarifas.get(str(jur), 0.0)
        filas.append({
            "jurisdiccion": jur, "ventas_totales": round(total, 2),
            "ventas_exentas": round(total - grav, 2), "ventas_gravables": round(grav, 2),
            "tarifa_%": tasa, "impuesto_estimado": round(grav * tasa / 100, 2),
        })
    return pd.DataFrame(filas)
