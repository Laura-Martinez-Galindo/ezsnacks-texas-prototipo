"""Integracion de las ventas del mes y calculo de las bases de la declaracion.

Las formulas son las mismas del Excel integrado que hoy arma el gerente:

    Total sales                       efectivo + tarjeta de todos los lectores
    Totals minus returns to customer  (Total sales + Equipment Sales) * 0.97
    Taxable sells                     lo anterior - Water Sells - Walmart buys
    Houston                           ventas de las maquinas de Houston - Walmart buys
    Houston MTA                       ventas de las maquinas de Bellaire, Katy y Spring

El impuesto no se calcula aqui: lo calcula QuickBooks con su modulo de Sales Tax.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from . import productos as prod
from .lectores import Lectura

CONFIG = Path(__file__).resolve().parents[1] / "config"
SUMAS = ["cantidad", "efectivo", "tarjeta", "cupones", "cuenta", "prepago", "otros"]


def reglas() -> dict:
    return json.loads((CONFIG / "reglas.json").read_text(encoding="utf-8"))


@dataclass
class Ajustes:
    exentos: list[str] | None = None   # None = propuesta automatica (agua sin endulzar)
    pagados: list[str] | None = None   # None = coincidencias seguras con la lista de compras
    lista_pagados: list[str] = field(default_factory=list)
    devoluciones_pct: float | None = None       # None = el de config/reglas.json
    ciudades: dict[str, list[str]] | None = None  # ciudades de cada jurisdiccion local

    @classmethod
    def de(cls, d: dict | None) -> "Ajustes":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _primero(s: pd.Series):
    s = s.dropna()
    return s.iloc[0] if len(s) else None


def integrar(lecturas: list[Lectura], maquinas: pd.DataFrame) -> pd.DataFrame:
    """Una fila por lector, maquina y producto, con la ciudad de la maquina."""
    filas = pd.concat([l.filas for l in lecturas], ignore_index=True)
    filas["id_maquina"] = filas["id_maquina"].fillna("")
    for c in ("costo", "utilidad", "impuesto"):
        filas[c] = pd.to_numeric(filas[c], errors="coerce")
    g = (filas.groupby(["fuente", "id_maquina", "maquina", "producto"], dropna=False, sort=False)
         .agg(**{c: (c, "sum") for c in SUMAS},
              barcode=("barcode", _primero), categoria=("categoria", _primero),
              costo=("costo", lambda s: s.sum(min_count=1)), utilidad=("utilidad", lambda s: s.sum(min_count=1)),
              impuesto=("impuesto", lambda s: s.sum(min_count=1)))
         .reset_index())
    g = g.merge(maquinas, on="id_maquina", how="left")
    g["en_lista"] = g["locacion"].notna()
    for c in ("locacion", "direccion", "ciudad", "estado", "zip"):
        g[c] = g[c].fillna("")
    g["activa"] = g["activa"].fillna(False).astype(bool)
    g["ventas"] = g["efectivo"] + g["tarjeta"]
    orden = pd.to_numeric(g["id_maquina"], errors="coerce")
    return (g.assign(_o=orden).sort_values(["fuente", "_o", "maquina", "producto"], kind="stable")
            .drop(columns="_o").reset_index(drop=True))


def calcular(integ: pd.DataFrame, a: Ajustes, anio: int, mes: int) -> dict:
    R = reglas()
    if a.devoluciones_pct is not None:
        R["devoluciones_pct"] = min(max(float(a.devoluciones_pct), 0.0), 50.0)
    for nombre, ciudades in (a.ciudades or {}).items():
        if nombre in R["jurisdicciones"]:
            R["jurisdicciones"][nombre]["ciudades"] = [str(c).strip() for c in ciudades if str(c).strip()]
    J = R["jurisdicciones"]
    integ = integ.assign(jurisdiccion=integ["ciudad"].map(
        lambda c: next((k for k, v in J.items() if c.lower() in [x.lower() for x in v["ciudades"]]), "")))
    vendidos = (integ.groupby("producto", as_index=False).agg(ventas=("ventas", "sum"), cantidad=("cantidad", "sum"))
                .sort_values("ventas", ascending=False))

    propuesta = [p for p in vendidos["producto"] if prod.es_exento(p)]
    exentos = set(propuesta if a.exentos is None else a.exentos)
    cruce = (prod.buscar_pagados(a.lista_pagados, vendidos) if a.lista_pagados
             else pd.DataFrame(columns=["buscado", "producto", "ventas", "estado"]))
    pagados = set(cruce.loc[cruce["estado"] == "seguro", "producto"]) if a.pagados is None else set(a.pagados)
    pagados -= exentos  # lo exento ya no paga impuesto: no se descuenta dos veces

    d = integ.copy()
    d["exento"] = d["producto"].isin(exentos)
    d["impuesto_pagado"] = d["producto"].isin(pagados)

    def par(mask) -> tuple[float, float]:
        return float(d.loc[mask, "efectivo"].sum()), float(d.loc[mask, "tarjeta"].sum())

    todo = pd.Series(True, index=d.index)
    dev = R["devoluciones_pct"] / 100
    filas = {}
    filas["total"] = par(todo)
    filas["equipos"] = (0.0, 0.0)
    filas["neto"] = tuple((filas["total"][i] + filas["equipos"][i]) * (1 - dev) for i in (0, 1))
    filas["agua"] = par(d["exento"])
    filas["walmart"] = par(d["impuesto_pagado"])
    filas["gravable"] = tuple(filas["neto"][i] - filas["agua"][i] - filas["walmart"][i] for i in (0, 1))
    filas["impuesto_walmart"] = tuple(filas["walmart"][i] * R["tasa_compras"] / 100 for i in (0, 1))
    locales = []
    for nombre, j in R["jurisdicciones"].items():
        bruto = par(d["jurisdiccion"] == nombre)
        base = tuple(bruto[i] - filas["walmart"][i] for i in (0, 1)) if j.get("resta_compras") else bruto
        filas[f"bruto_{nombre}"], filas[f"base_{nombre}"] = bruto, base
        locales.append({"jurisdiccion": nombre, "codigo": j["codigo"], "nombre_comptroller": j["nombre_comptroller"],
                        "tasa": j["tasa"], "maquinas": int(d.loc[d["jurisdiccion"] == nombre, "id_maquina"].nunique()),
                        "ventas": round(sum(bruto), 2), "base": round(sum(base))})

    pasos = {k: {"efectivo": round(v[0], 2), "tarjeta": round(v[1], 2), "total": round(v[0] + v[1], 2)}
             for k, v in filas.items()}
    pasos["devoluciones_pct"] = R["devoluciones_pct"]
    pasos["cupones"] = round(float(d["cupones"].sum()), 2)
    pasos["prepago"] = round(float(d["prepago"].sum() + d["otros"].sum()), 2)

    # Estimado con las tasas de la declaracion; el valor oficial lo da QuickBooks
    total_tx, gravable_tx = round(pasos["neto"]["total"]), round(pasos["gravable"]["total"])
    impuesto_estado = round(gravable_tx * R["tasa_estado"] / 100, 2)
    for l in locales:
        l["impuesto"] = round(l["base"] * l["tasa"] / 100, 2)
    impuesto_local = round(sum(l["impuesto"] for l in locales), 2)
    total_imp = round(impuesto_estado + impuesto_local, 2)
    desc = R["descuento_a_tiempo_pct"] / 100
    vence = date(anio + (mes == 12), mes % 12 + 1, 20)
    declaracion = {
        "vence": vence.isoformat(), "total_ventas": total_tx, "ventas_gravables": gravable_tx, "compras_gravables": 0,
        "tasa_estado": R["tasa_estado"], "impuesto_estado": impuesto_estado, "locales": locales,
        "impuesto_local": impuesto_local, "impuesto_total": total_imp, "descuento": round(total_imp * desc, 2),
        "a_pagar": round(total_imp - round(total_imp * desc, 2), 2),
        "a_pagar_estado": round(impuesto_estado * (1 - desc), 2), "a_pagar_local": round(impuesto_local * (1 - desc), 2),
    }

    # Por maquina: lo que se envia a QuickBooks (un recibo de venta por maquina)
    pm = (d.groupby("id_maquina", dropna=False)
          .apply(lambda x: pd.Series({
              "maquina": x["maquina"].iloc[0], "fuente": ", ".join(sorted(set(x["fuente"]))),
              "locacion": x["locacion"].iloc[0], "direccion": x["direccion"].iloc[0], "ciudad": x["ciudad"].iloc[0],
              "estado": x["estado"].iloc[0], "zip": x["zip"].iloc[0], "jurisdiccion": x["jurisdiccion"].iloc[0],
              "en_lista": bool(x["en_lista"].iloc[0]), "activa": bool(x["activa"].iloc[0]),
              "unidades": float(x["cantidad"].sum()), "ventas": float(x["ventas"].sum()),
              "exentas": float(x.loc[x["exento"], "ventas"].sum()),
              "pagadas": float(x.loc[x["impuesto_pagado"], "ventas"].sum()),
          }), include_groups=False).reset_index())
    pm["gravable"] = (pm["ventas"] * (1 - dev) - pm["exentas"] - pm["pagadas"]).clip(lower=0)
    pm = pm.assign(_o=pd.to_numeric(pm["id_maquina"], errors="coerce")).sort_values(["_o", "maquina"]).drop(columns="_o")

    lista_exentos = vendidos[vendidos["producto"].isin(set(propuesta) | exentos)].assign(
        marcado=lambda x: x["producto"].isin(exentos))
    cruce = cruce.assign(marcado=cruce["producto"].isin(pagados), exento=cruce["producto"].isin(exentos))

    revisar = []
    for _, m in pm[~pm["en_lista"]].iterrows():
        revisar.append({"texto": m["maquina"], "detalle": "No está en la lista de máquinas: no cuenta para Houston ni MTA."})
    for _, m in pm[pm["en_lista"] & ~pm["activa"]].iterrows():
        revisar.append({"texto": m["maquina"], "detalle": "Está inactiva en la lista, pero tuvo ventas."})
    for _, f in cruce[cruce["estado"] == "dudoso"].iterrows():
        revisar.append({"texto": f["producto"], "detalle": f"Puede ser “{f['buscado']}”, pero el nombre no dice el tamaño."})
    for _, f in cruce[cruce["estado"] == "sin_ventas"].iterrows():
        revisar.append({"texto": f["buscado"], "detalle": "Está en la lista de compras, pero no tuvo ventas este mes."})

    return {"pasos": pasos, "declaracion": declaracion, "maquinas": pm, "exentos": lista_exentos, "pagados": cruce,
            "revisar": revisar, "detalle": d, "reglas": R, "lista_exentos": sorted(exentos), "lista_pagados": sorted(pagados)}
