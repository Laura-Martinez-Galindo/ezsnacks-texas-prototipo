"""Calculo del cierre mensual: ventas integradas, declaracion del Texas Comptroller y comisiones.

Sigue el mismo procedimiento que hace el gerente de EzSnack en Excel:

    ventas totales      efectivo + tarjeta de todos los lectores (+ ventas de equipos)
    menos devoluciones  un porcentaje fijo (3 %) por reembolsos a clientes y producto vencido
    menos exentas       agua sin endulzar
    menos ya pagadas    ventas de los productos que se compraron por fuera con impuesto pagado
    = ventas gravables  base del impuesto del estado (6.25 %)

y para los impuestos locales (1 %) hace lo mismo solo con las maquinas de cada jurisdiccion.
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


def reglas() -> dict:
    return json.loads((CONFIG / "reglas.json").read_text(encoding="utf-8"))


@dataclass
class Ajustes:
    devoluciones_pct: float = 3.0
    equipos_efectivo: float = 0.0
    equipos_tarjeta: float = 0.0
    incluir_prepago: bool = False
    a_tiempo: bool = True
    exentos: list[str] | None = None      # None = usar la propuesta automatica
    pagados: list[str] | None = None      # None = usar las coincidencias seguras
    lista_pagados: list[str] = field(default_factory=list)
    comisiones: list[dict] | None = None  # None = reglas de config

    @classmethod
    def de(cls, d: dict | None) -> "Ajustes":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def integrar(lecturas: list[Lectura], maquinas: pd.DataFrame) -> pd.DataFrame:
    """Une las filas de todos los lectores por fuente, maquina y producto, con los datos de la lista."""
    filas = pd.concat([l.filas for l in lecturas], ignore_index=True)
    claves = ["fuente", "id_maquina", "maquina", "producto"]
    filas["id_maquina"] = filas["id_maquina"].fillna("")
    g = (filas.groupby(claves, dropna=False)
         .agg(cantidad=("cantidad", "sum"), efectivo=("efectivo", "sum"), tarjeta=("tarjeta", "sum"),
              cupones=("cupones", "sum"), cuenta=("cuenta", "sum"), prepago=("prepago", "sum"), otros=("otros", "sum"))
         .reset_index())
    g = g.merge(maquinas, on="id_maquina", how="left")
    g["en_lista"] = g["locacion"].notna()
    for c in ("locacion", "direccion", "ciudad", "comision_a"):
        g[c] = g[c].fillna("")
    g["activa"] = g["activa"].fillna(False)
    j = reglas()["jurisdicciones"]
    g["jurisdiccion"] = g["ciudad"].map(lambda c: next((k for k, v in j.items() if c.lower() in [x.lower() for x in v["ciudades"]]), ""))
    return g


def _ventas(df: pd.DataFrame, a: Ajustes) -> pd.Series:
    v = df["efectivo"] + df["tarjeta"]
    if a.incluir_prepago:
        v = v + df["prepago"] + df["otros"]
    return v


def productos_vendidos(integ: pd.DataFrame, a: Ajustes) -> pd.DataFrame:
    t = integ.assign(ventas=_ventas(integ, a))
    return (t.groupby("producto", as_index=False)
            .agg(ventas=("ventas", "sum"), cantidad=("cantidad", "sum"))
            .sort_values("ventas", ascending=False))


def calcular(integ: pd.DataFrame, a: Ajustes, anio: int, mes: int) -> dict:
    R = reglas()
    vendidos = productos_vendidos(integ, a)

    # Productos exentos y productos ya pagados
    propuesta_exentos = [p for p in vendidos["producto"] if prod.es_exento(p)]
    exentos = set(propuesta_exentos if a.exentos is None else a.exentos)
    cruce = prod.buscar_pagados(a.lista_pagados, vendidos) if a.lista_pagados else pd.DataFrame(columns=["buscado", "producto", "ventas", "estado"])
    if a.pagados is None:
        pagados = set(cruce.loc[cruce["estado"] == "seguro", "producto"])
    else:
        pagados = set(a.pagados)
    pagados -= exentos  # lo exento no paga impuesto, no se descuenta dos veces

    d = integ.copy()
    d["ventas"] = _ventas(d, a)
    d["exento"] = d["producto"].isin(exentos)
    d["impuesto_pagado"] = d["producto"].isin(pagados)
    factor = 1 - a.devoluciones_pct / 100

    # Por maquina
    pm = (d.groupby("id_maquina", dropna=False)
          .apply(lambda x: pd.Series({
              "maquina": x["maquina"].iloc[0], "fuente": ", ".join(sorted(set(x["fuente"]))),
              "locacion": x["locacion"].iloc[0], "ciudad": x["ciudad"].iloc[0], "jurisdiccion": x["jurisdiccion"].iloc[0],
              "comision_a": x["comision_a"].iloc[0], "en_lista": bool(x["en_lista"].iloc[0]), "activa": bool(x["activa"].iloc[0]),
              "unidades": float(x["cantidad"].sum()), "efectivo": float(x["efectivo"].sum()), "tarjeta": float(x["tarjeta"].sum()),
              "cupones": float(x["cupones"].sum()), "prepago": float(x["prepago"].sum() + x["otros"].sum()),
              "ventas": float(x["ventas"].sum()),
              "exentas": float(x.loc[x["exento"], "ventas"].sum()),
              "pagadas": float(x.loc[x["impuesto_pagado"], "ventas"].sum()),
          }), include_groups=False)
          .reset_index())
    pm["gravable"] = pm["ventas"] * factor - pm["exentas"] - pm["pagadas"]
    pm["orden"] = pd.to_numeric(pm["id_maquina"], errors="coerce")
    pm = pm.sort_values(["orden", "maquina"]).drop(columns="orden")

    equipos = a.equipos_efectivo + a.equipos_tarjeta
    total = float(pm["ventas"].sum()) + equipos
    devol = total * a.devoluciones_pct / 100
    neto = total - devol
    exentas = float(pm["exentas"].sum())
    pagadas = float(pm["pagadas"].sum())
    gravable = neto - exentas - pagadas

    tasa_estado = R["tasa_estado"]
    total_tx, gravable_tx = round(neto), round(gravable)
    impuesto_estado = round(gravable_tx * tasa_estado / 100, 2)

    locales = []
    for nombre, j in R["jurisdicciones"].items():
        sub = pm[pm["jurisdiccion"] == nombre]
        base = float(sub["gravable"].sum())
        locales.append({"jurisdiccion": nombre, "codigo": j["codigo"], "nombre_comptroller": j["nombre_comptroller"],
                        "tasa": j["tasa"], "maquinas": int(len(sub)), "ventas": round(float(sub["ventas"].sum()), 2),
                        "base": round(base), "impuesto": round(round(base) * j["tasa"] / 100, 2)})
    impuesto_local = round(sum(l["impuesto"] for l in locales), 2)
    impuesto_total = round(impuesto_estado + impuesto_local, 2)
    descuento = round(impuesto_total * R["descuento_a_tiempo_pct"] / 100, 2) if a.a_tiempo else 0.0
    vence = date(anio + (mes == 12), mes % 12 + 1, 20)

    declaracion = {
        "periodo": f"{mes:02d}/{anio}", "vence": vence.isoformat(),
        "total_ventas": total_tx, "ventas_gravables": gravable_tx, "compras_gravables": 0,
        "sujeto_estado": gravable_tx, "tasa_estado": tasa_estado, "impuesto_estado": impuesto_estado,
        "locales": locales, "impuesto_local": impuesto_local, "impuesto_total": impuesto_total,
        "descuento": descuento, "a_pagar": round(impuesto_total - descuento, 2),
        "a_pagar_estado": round(impuesto_estado - impuesto_estado * (R["descuento_a_tiempo_pct"] / 100 if a.a_tiempo else 0), 2),
        "a_pagar_local": round(impuesto_local - impuesto_local * (R["descuento_a_tiempo_pct"] / 100 if a.a_tiempo else 0), 2),
    }
    pasos = {
        "efectivo": round(float(pm["efectivo"].sum()) + a.equipos_efectivo, 2),
        "tarjeta": round(float(pm["tarjeta"].sum()) + a.equipos_tarjeta, 2),
        "prepago": round(float(pm["prepago"].sum()), 2), "cupones": round(float(pm["cupones"].sum()), 2),
        "equipos": round(equipos, 2), "total": round(total, 2), "devoluciones_pct": a.devoluciones_pct,
        "devoluciones": round(devol, 2), "neto": round(neto, 2), "exentas": round(exentas, 2),
        "pagadas": round(pagadas, 2), "impuesto_ya_pagado": round(pagadas * R["tasa_compras"] / 100, 2),
        "gravable": round(gravable, 2), "incluye_prepago": a.incluir_prepago,
    }

    # Productos: propuesta de exentos y cruce con la lista de compras con impuesto pagado
    lista_exentos = vendidos[vendidos["producto"].isin(set(propuesta_exentos) | exentos)].assign(
        marcado=lambda x: x["producto"].isin(exentos))
    cruce = cruce.assign(marcado=cruce["producto"].isin(pagados), exento=cruce["producto"].isin(exentos))

    revisar = []
    fuera = pm[~pm["en_lista"]]
    for _, m in fuera.iterrows():
        revisar.append({"tipo": "maquina", "texto": m["maquina"],
                        "detalle": f"No está en la lista de máquinas. Sus ventas ({m['ventas']:,.2f} USD) cuentan para el estado, "
                                   "pero no para Houston ni MTA hasta que se agregue con su ciudad."})
    for _, m in pm[pm["en_lista"] & ~pm["activa"]].iterrows():
        revisar.append({"tipo": "inactiva", "texto": m["maquina"],
                        "detalle": "Está marcada como inactiva en la lista, pero tuvo ventas este mes."})
    for _, f in cruce[cruce["estado"] == "dudoso"].iterrows():
        revisar.append({"tipo": "dudoso", "texto": f["producto"],
                        "detalle": f"Puede ser “{f['buscado']}” de la lista de compras, pero el nombre no dice el tamaño."})
    for _, f in cruce[cruce["estado"] == "sin_ventas"].iterrows():
        revisar.append({"tipo": "sin_ventas", "texto": f["buscado"],
                        "detalle": "Está en la lista de compras con impuesto pagado, pero no se encontró en las ventas del mes."})

    return {
        "pasos": pasos, "declaracion": declaracion, "maquinas": pm, "exentos": lista_exentos, "pagados": cruce,
        "revisar": revisar, "comisiones": comisiones(pm, a), "detalle": d,
    }


def comisiones(pm: pd.DataFrame, a: Ajustes) -> dict:
    """Comisiones por socio segun sus reglas.

    Para cada maquina del socio: base = ventas - descuento por tarjeta (% sobre lo vendido con tarjeta)
    - costo mensual del lector. Si las ventas de la maquina no superan el minimo, no hay comision.
    """
    reglas_c = a.comisiones if a.comisiones is not None else reglas()["comisiones"]
    socios, detalle = [], []
    for r in reglas_c:
        col, valor = r.get("columna", "comision_a"), str(r.get("valor", "")).lower()
        if col == "comision_a":
            sel = pm[pm["comision_a"].str.lower() == valor]
        else:
            sel = pm[pm[col].str.lower().str.contains(valor, regex=False) | pm["maquina"].str.lower().str.contains(valor, regex=False)]
        pct = r.get("porcentaje")
        filas = []
        for _, m in sel.iterrows():
            desc_tarjeta = m["tarjeta"] * float(r.get("descuento_tarjeta_pct") or 0) / 100
            lector = float(r.get("costo_lector_mes") or 0)
            base = m["ventas"] - desc_tarjeta - lector
            minimo = float(r.get("minimo_por_maquina") or 0)
            aplica = pct is not None and m["ventas"] > minimo
            com = round(base * float(pct) / 100, 2) if aplica else 0.0
            filas.append({"socio": r["socio"], "id_maquina": m["id_maquina"], "maquina": m["maquina"],
                          "ventas": round(m["ventas"], 2), "tarjeta": round(m["tarjeta"], 2),
                          "descuento_tarjeta": round(desc_tarjeta, 2), "costo_lector": lector,
                          "base": round(base, 2), "aplica": aplica, "comision": com})
        detalle += filas
        socios.append({"socio": r["socio"], "regla": r.get("descripcion", ""), "porcentaje": pct,
                       "maquinas": len(filas), "con_comision": sum(f["aplica"] for f in filas),
                       "ventas": round(sum(f["ventas"] for f in filas), 2),
                       "comision": round(sum(f["comision"] for f in filas), 2),
                       "por_confirmar": pct is None})
    return {"socios": socios, "detalle": detalle}
