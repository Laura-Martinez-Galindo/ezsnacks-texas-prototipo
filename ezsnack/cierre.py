"""Integracion de las ventas del mes y calculo de las bases de la declaracion.

Las formulas siguen el Excel integrado que hoy arma el gerente:

    Total sales       efectivo + tarjeta (+ cupones que compran las empresas)
    menos             devoluciones a clientes
    Taxable sells     lo anterior - agua - productos comprados con impuesto ya pagado
    Houston           ventas gravables de las maquinas de Houston
    Houston MTA       ventas gravables de las maquinas de Bellaire, Katy y Spring

Las devoluciones se pueden calcular de dos maneras (regla "devoluciones"):

    cupones      Los cupones salen de la columna Coupon de AV360 y son de dos clases. Los que compra
                 una empresa para sus empleados son venta y pagan impuesto. Los demas son los que se
                 mandan a quien reclama que la maquina no le entrego: son devolucion y se restan.
    porcentaje   Como el Excel del gerente: se resta un porcentaje fijo (3 %) de lo vendido en
                 efectivo y tarjeta, y los cupones no se tocan.

Todo se calcula primero por maquina y al centavo, y los totales son la suma de las maquinas. Asi
el resumen, el Excel y los recibos que se envian a QuickBooks salen de los mismos numeros y
QuickBooks no puede dar una base distinta a la de la aplicacion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from . import almacen
from . import productos as prod
from .lectores import Lectura

CONFIG = Path(__file__).resolve().parents[1] / "config"
SUMAS = ["cantidad", "efectivo", "tarjeta", "cupones", "cuenta", "prepago", "otros"]


def reglas(periodo: str | None = None) -> dict:
    """Las reglas de la empresa que aplican a un mes ("2026-09"). Salen de la base de datos."""
    return almacen.reglas(periodo)


@dataclass
class Ajustes:
    exentos: list[str] | None = None   # None = propuesta automatica (agua sin endulzar)
    pagados: list[str] | None = None   # None = coincidencias seguras con la lista de compras
    lista_pagados: list[str] = field(default_factory=list)
    ciudades: dict[str, list[str]] | None = None   # ciudades de cada jurisdiccion local
    cupones_empresa: list[str] | None = None       # maquinas cuyos cupones compro una empresa
    cupones_empresa_minimo: float | None = None    # desde cuanto se considera venta a empresa
    devoluciones: dict | None = None               # {"metodo": "cupones" | "porcentaje", "porcentaje": 3}
    catalogo: dict | None = None                   # producto -> {"exento": bool | None, "pagado_habitual": bool}

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
    # Las maquinas marcadas TBD son de prueba: lo que registran no es una venta real y no entra
    # al cierre ni aparece para revisar.
    filas = filas[~filas["maquina"].astype(str).str.contains(r"\bTBD\b", case=False, regex=True, na=False)]
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


def _c(x) -> float:
    """Redondeo al centavo, con el medio centavo hacia arriba (como una factura)."""
    return float(int(abs(float(x)) * 100 + 0.5 + 1e-7)) / 100 * (1 if x >= 0 else -1)


def impuesto_esperado(maquinas: pd.DataFrame, R: dict) -> list[dict]:
    """Lo que debe devolver QuickBooks: por cada tasa, la base y el impuesto sumando recibo por recibo.

    QuickBooks calcula el impuesto de cada recibo y lo redondea al centavo, asi que el total del mes
    es la suma de esos redondeos y no la tasa por la base total. Aqui se calcula igual.
    """
    J = R["jurisdicciones"]
    estado = f"TX estado {R['tasa_estado']:g}%"
    filas = {estado: {"jurisdiccion": estado, "tasa": float(R["tasa_estado"]), "base": 0.0, "impuesto": 0.0}}
    for _, m in maquinas.iterrows():
        g = float(m["gravable"])
        if g <= 0:
            continue
        filas[estado]["base"] += g
        filas[estado]["impuesto"] += _c(g * R["tasa_estado"] / 100)
        j = J.get(m["jurisdiccion"])
        if j:
            nombre = f"{j['nombre_comptroller']} {j['tasa']:g}%"
            f = filas.setdefault(nombre, {"jurisdiccion": nombre, "tasa": float(j["tasa"]), "base": 0.0, "impuesto": 0.0})
            f["base"] += g
            f["impuesto"] += _c(g * j["tasa"] / 100)
    for f in filas.values():
        f["base"], f["impuesto"] = round(f["base"], 2), round(f["impuesto"], 2)
    return list(filas.values())


def calcular(integ: pd.DataFrame, a: Ajustes, anio: int, mes: int) -> dict:
    R = reglas(f"{anio}-{mes:02d}")
    if a.cupones_empresa_minimo is not None:
        R["cupones_empresa_minimo"] = max(float(a.cupones_empresa_minimo), 0.0)
    dev = {"metodo": "cupones", "porcentaje": 3.0, **(R.get("devoluciones") or {}), **(a.devoluciones or {})}
    dev["metodo"] = "porcentaje" if dev["metodo"] == "porcentaje" else "cupones"
    dev["porcentaje"] = min(max(float(dev.get("porcentaje") or 0), 0.0), 100.0)
    R["devoluciones"] = dev
    por_pct = dev["metodo"] == "porcentaje"
    for nombre, ciudades in (a.ciudades or {}).items():
        if nombre in R["jurisdicciones"]:
            R["jurisdicciones"][nombre]["ciudades"] = [str(c).strip() for c in ciudades if str(c).strip()]
    J = R["jurisdicciones"]
    integ = integ.assign(jurisdiccion=integ["ciudad"].map(
        lambda c: next((k for k, v in J.items() if c.lower() in [x.lower() for x in v["ciudades"]]), "")))
    vendidos = (integ.groupby("producto", as_index=False).agg(ventas=("ventas", "sum"), cantidad=("cantidad", "sum"))
                .sort_values("ventas", ascending=False))

    # Lo que el gerente ya clasifico manda sobre la regla del agua
    cat = a.catalogo or {}
    guardado = lambda p: cat.get(p, {}).get("exento")  # noqa: E731
    propuesta = [p for p in vendidos["producto"] if (guardado(p) if guardado(p) is not None else prod.es_exento(p, R))]
    exentos = set(propuesta if a.exentos is None else a.exentos)
    if a.lista_pagados:
        cruce = prod.buscar_pagados(a.lista_pagados, vendidos)
    else:   # sin lista este mes: se proponen los que habitualmente se compran por fuera
        habituales = vendidos[vendidos["producto"].map(lambda p: bool(cat.get(p, {}).get("pagado_habitual")))]
        cruce = pd.DataFrame({"buscado": "Habitual", "producto": habituales["producto"],
                              "ventas": habituales["ventas"].round(2), "estado": "seguro"},
                             columns=["buscado", "producto", "ventas", "estado"])
    pagados = set(cruce.loc[cruce["estado"] == "seguro", "producto"]) if a.pagados is None else set(a.pagados)
    pagados -= exentos  # lo exento ya no paga impuesto: no se descuenta dos veces

    d = integ.copy()
    d["exento"] = d["producto"].isin(exentos)
    d["impuesto_pagado"] = d["producto"].isin(pagados)

    # Cupones: los que compra una empresa son venta; los demas son devoluciones a clientes
    por_maquina = d.groupby("id_maquina")["cupones"].sum()
    if a.cupones_empresa is not None:
        empresas = {m for m in a.cupones_empresa if m in por_maquina.index}
    else:   # las maquinas que la empresa marco en sus reglas, mas las que pasan del monto minimo
        fijas = {str(m).strip() for m in R.get("cupones_empresas", [])} & set(por_maquina.index)
        empresas = fijas | set(por_maquina[por_maquina >= R["cupones_empresa_minimo"]].index)
    d["cupon_empresa"] = d["id_maquina"].isin(empresas) & (d["cupones"] > 0)
    cupones = [{"id_maquina": m, "maquina": d.loc[d["id_maquina"] == m, "maquina"].iloc[0],
                "locacion": d.loc[d["id_maquina"] == m, "locacion"].iloc[0],
                "valor": round(float(v), 2), "de_empresa": m in empresas}
               for m, v in por_maquina[por_maquina > 0].sort_values(ascending=False).items()]

    # ---- por maquina, al centavo: de aqui salen el resumen, el Excel y los recibos de QuickBooks ----
    d["cup_emp"] = d["cupones"].where(d["cupon_empresa"], 0.0)
    d["cup_dev"] = d["cupones"].where(~d["cupon_empresa"], 0.0)
    for k, mask in (("ex", d["exento"]), ("pag", d["impuesto_pagado"])):
        d[f"{k}_e"], d[f"{k}_t"] = d["efectivo"].where(mask, 0.0), d["tarjeta"].where(mask, 0.0)
    sumas = ["cantidad", "efectivo", "tarjeta", "cup_emp", "cup_dev", "ex_e", "ex_t", "pag_e", "pag_t"]
    primeros = ["maquina", "locacion", "direccion", "ciudad", "estado", "zip", "jurisdiccion", "en_lista", "activa"]
    pm = (d.groupby("id_maquina", dropna=False, sort=False)
          .agg(**{c: (c, "sum") for c in sumas}, **{c: (c, "first") for c in primeros},
               fuente=("fuente", lambda s: ", ".join(sorted(set(s)))))
          .reset_index())
    for c in sumas[1:]:
        pm[c] = pm[c].map(_c)
    if por_pct:
        factor = 1 - dev["porcentaje"] / 100
        pm["neto_e"], pm["neto_t"] = (pm["efectivo"] * factor).map(_c), (pm["tarjeta"] * factor).map(_c)
        pm["cup_emp"], pm["cup_dev"] = 0.0, 0.0
    else:
        # Los cupones que compran las empresas para sus empleados se cobran aparte: por defecto no
        # cuentan ni como venta ni como devolucion. Solo restan los cupones de reembolso.
        if not R.get("cupones_empresa_cuentan", False):
            pm["cup_emp"] = 0.0
        pm["neto_e"], pm["neto_t"] = pm["efectivo"], (pm["tarjeta"] + pm["cup_emp"] - pm["cup_dev"]).map(_c)
    pm["dev_e"] = (pm["efectivo"] - pm["neto_e"]).map(_c)
    pm["dev_t"] = (pm["tarjeta"] + pm["cup_emp"] - pm["neto_t"]).map(_c)   # = cupones de reembolso
    pm["unidades"] = pm["cantidad"].astype(float)
    pm["ventas"] = (pm["neto_e"] + pm["neto_t"]).map(_c)
    pm["exentas"] = (pm["ex_e"] + pm["ex_t"]).map(_c)
    pm["pagadas"] = (pm["pag_e"] + pm["pag_t"]).map(_c)
    pm["gravable"] = (pm["ventas"] - pm["exentas"] - pm["pagadas"]).map(_c)
    pm["en_lista"], pm["activa"] = pm["en_lista"].astype(bool), pm["activa"].astype(bool)
    negativas = pm[pm["gravable"] < 0]
    # una maquina que casi solo vendio agua puede quedar con gravable negativo: se deja en cero
    pm.loc[pm["gravable"] < 0, "exentas"] = (pm["ventas"] - pm["pagadas"]).clip(lower=0).map(_c)
    pm.loc[pm["gravable"] < 0, "gravable"] = 0.0
    pm = pm.assign(_o=pd.to_numeric(pm["id_maquina"], errors="coerce")).sort_values(["_o", "maquina"]).drop(columns="_o")

    def par(e: str, t: str, mask=None) -> tuple[float, float]:
        x = pm if mask is None else pm[mask]
        return float(x[e].sum()), float(x[t].sum())

    def menos(*pares) -> tuple[float, float]:
        return tuple(pares[0][i] - sum(q[i] for q in pares[1:]) for i in (0, 1))

    filas = {}
    filas["ventas"] = par("efectivo", "tarjeta")
    filas["cupones_empresa"] = (0.0, float(pm["cup_emp"].sum()))   # las empresas los pagan con factura
    filas["total"] = (filas["ventas"][0], filas["ventas"][1] + filas["cupones_empresa"][1])
    filas["devoluciones"] = par("dev_e", "dev_t")
    filas["neto"] = par("neto_e", "neto_t")
    filas["agua"] = par("ex_e", "ex_t")
    filas["walmart"] = par("pag_e", "pag_t")
    filas["gravable"] = menos(filas["neto"], filas["agua"], filas["walmart"])
    filas["impuesto_walmart"] = tuple(filas["walmart"][i] * R["tasa_compras"] / 100 for i in (0, 1))
    locales = []
    for nombre, j in J.items():
        en_j = pm["jurisdiccion"] == nombre
        filas[f"bruto_{nombre}"] = par("neto_e", "neto_t", en_j)
        filas[f"agua_{nombre}"] = par("ex_e", "ex_t", en_j)
        filas[f"pagadas_{nombre}"] = par("pag_e", "pag_t", en_j)
        filas[f"base_{nombre}"] = menos(filas[f"bruto_{nombre}"], filas[f"agua_{nombre}"], filas[f"pagadas_{nombre}"])
        locales.append({"jurisdiccion": nombre, "codigo": j["codigo"], "nombre_comptroller": j["nombre_comptroller"],
                        "tasa": j["tasa"], "maquinas": int(en_j.sum()),
                        "ventas": round(sum(filas[f"bruto_{nombre}"]), 2),
                        "base_exacta": round(float(pm.loc[en_j, "gravable"].sum()), 2),
                        "base": round(float(pm.loc[en_j, "gravable"].sum()))})

    pasos = {k: {"efectivo": round(v[0], 2), "tarjeta": round(v[1], 2), "total": round(v[0] + v[1], 2)}
             for k, v in filas.items()}
    pasos["prepago"] = round(float(d["prepago"].sum() + d["otros"].sum()), 2)
    pasos["cupones_minimo"] = R["cupones_empresa_minimo"]
    pasos["cupones_empresa_cuentan"] = bool(R.get("cupones_empresa_cuentan", False))
    pasos["cupones_empresa_fuera"] = round(float(d["cup_emp"].sum()), 2) if not pasos["cupones_empresa_cuentan"] and not por_pct else 0.0
    pasos["devoluciones_metodo"] = dev["metodo"]
    pasos["devoluciones_pct"] = dev["porcentaje"]
    pasos["cupones_reporte"] = round(float(d["cupones"].sum()), 2)

    # Valores de la declaracion: el Comptroller recibe dolares enteros y el calcula el impuesto
    gravable_exacto = round(float(pm["gravable"].sum()), 2)
    total_tx, gravable_tx = round(pasos["neto"]["total"]), round(gravable_exacto)
    impuesto_estado = round(gravable_tx * R["tasa_estado"] / 100, 2)
    for l in locales:
        l["impuesto"] = round(l["base"] * l["tasa"] / 100, 2)
    impuesto_local = round(sum(l["impuesto"] for l in locales), 2)
    total_imp = round(impuesto_estado + impuesto_local, 2)
    desc = R["descuento_a_tiempo_pct"] / 100
    vence = date(anio + (mes == 12), mes % 12 + 1, 20)
    esperado = impuesto_esperado(pm, R)
    declaracion = {
        "vence": vence.isoformat(), "total_ventas": total_tx, "ventas_gravables": gravable_tx, "compras_gravables": 0,
        "gravable_exacto": gravable_exacto,
        "tasa_estado": R["tasa_estado"], "impuesto_estado": impuesto_estado, "locales": locales,
        "impuesto_local": impuesto_local, "impuesto_total": total_imp, "descuento": round(total_imp * desc, 2),
        "a_pagar": round(total_imp - round(total_imp * desc, 2), 2),
        "a_pagar_estado": round(impuesto_estado * (1 - desc), 2), "a_pagar_local": round(impuesto_local * (1 - desc), 2),
        "quickbooks_esperado": esperado,
        "quickbooks_impuesto": round(sum(f["impuesto"] for f in esperado), 2),
    }

    lista_exentos = vendidos[vendidos["producto"].isin(set(propuesta) | exentos)].assign(
        marcado=lambda x: x["producto"].isin(exentos))
    cruce = cruce.assign(marcado=cruce["producto"].isin(pagados), exento=cruce["producto"].isin(exentos))

    revisar = []
    for _, m in pm[~pm["en_lista"]].iterrows():
        revisar.append({"texto": m["maquina"], "detalle": "Vendió este mes pero no está en la lista de máquinas, así que no se sabe en qué ciudad está: paga solo el impuesto del estado."})
    for _, m in pm[pm["en_lista"] & ~pm["activa"]].iterrows():
        revisar.append({"texto": m["maquina"], "detalle": "En la lista de máquinas figura como inactiva, pero este mes vendió. Actívela si ya está funcionando."})
    for _, m in negativas.iterrows():
        revisar.append({"texto": m["maquina"], "detalle": "Casi todo lo que vendió es agua o producto que ya pagó impuesto, así que no queda nada gravable."})
    # Los parecidos no van a "para revisar": tienen su propia seccion, donde se confirma uno por uno
    parejas = [{"producto": f["producto"], "buscado": f["buscado"], "ventas": float(f.get("ventas") or 0),
                "marcado": bool(f["marcado"])}
               for _, f in cruce[cruce["estado"] == "dudoso"].iterrows()]
    for _, f in cruce[cruce["estado"] == "sin_ventas"].iterrows():
        revisar.append({"texto": f["buscado"], "detalle": "Usted lo marcó como comprado con impuesto ya pagado, pero este mes no se vendió, así que no se descontó nada."})

    return {"pasos": pasos, "declaracion": declaracion, "maquinas": pm, "cupones": cupones, "exentos": lista_exentos, "pagados": cruce,
            "revisar": revisar, "parejas": parejas, "detalle": d, "reglas": R, "lista_exentos": sorted(exentos), "lista_pagados": sorted(pagados)}
