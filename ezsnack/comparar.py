"""Comparacion del cierre de la aplicacion con el Excel integrado que el gerente arma a mano.

Se lee el Excel hecho a mano (la tabla Master Sales y el bloque de resumen que esta debajo) y se
compara renglon por renglon con lo que calculo la aplicacion. Para cada diferencia se busca la
causa en los propios datos: una maquina que falta en un lado, un porcentaje fijo en lugar de los
cupones reales, una cifra digitada que no sale de la tabla, una maquina que se quedo por fuera al
filtrar las de Houston.

No cambia ningun calculo: solo explica. Sirve para el mes de prueba en paralelo y para una auditoria.
"""
from __future__ import annotations

import io
import itertools
import re
from pathlib import Path

import pandas as pd

from .lectores import id_maquina

# Texto de la etiqueta en el Excel (en minusculas, sin espacios repetidos) -> clave interna
ETIQUETAS = [
    ("totals houston sales", "houston"),
    ("houston mta", "mta"),
    ("houston taxable sales", "houston_bruto"),
    ("totals minus returns", "neto"),
    ("total minus returns", "neto"),
    ("taxes paid", "impuesto_pagado"),
    ("walmart buys", "walmart"),
    ("water sells", "agua"),
    ("water sales", "agua"),
    ("taxable sells", "gravable"),
    ("taxable sales", "gravable"),
    ("equipment sales", "equipos"),
    ("total sales", "ventas"),
]
NUMERICAS = ["Quantity Sold", "Sales Revenue", "Credit Sales", "Cash Sales", "Coupon Sales", "Account Sales",
             "Prepaid Credit Sales", "Monyx Balance Sales"]


class ExcelNoReconocido(ValueError):
    pass


def _norm(t) -> str:
    return re.sub(r"\s+", " ", str(t)).strip().lower()


def _plata(n: float) -> str:
    return f"${n:,.2f}"


def leer_original(fuente, nombre: str | None = None) -> dict:
    """Lee el Excel integrado hecho a mano: {"tabla": DataFrame, "resumen": {clave: (efectivo, tarjeta, total)}}."""
    nombre = nombre or getattr(fuente, "name", "") or str(fuente)
    if isinstance(fuente, (str, Path)):
        fuente = io.BytesIO(Path(fuente).read_bytes())
    if hasattr(fuente, "seek"):
        fuente.seek(0)
    try:
        hojas = pd.read_excel(fuente, sheet_name=None, header=None, dtype=object)
    except Exception as exc:  # noqa: BLE001
        raise ExcelNoReconocido(f"No se pudo abrir {Path(str(nombre)).name}: {exc}") from exc
    for crudo in hojas.values():
        if crudo.empty:
            continue
        cab = [_norm(c) for c in crudo.iloc[0].tolist()]
        if not {"source", "machine", "product", "cash sales", "credit sales"} <= set(cab):
            continue
        df = crudo.iloc[1:].copy()
        df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in crudo.iloc[0].tolist()]
        tabla = df[df["Source"].notna() & df["Machine"].notna() & df["Product"].notna()].copy()
        for c in NUMERICAS:
            tabla[c] = pd.to_numeric(tabla[c], errors="coerce").fillna(0.0) if c in tabla else 0.0
        tabla["id_maquina"] = tabla["Machine"].map(id_maquina).fillna("")
        resumen = {}
        for _, fila in crudo.iloc[len(tabla) + 1:].iterrows():
            celdas = fila.tolist()
            clave = None
            for c in celdas:
                if isinstance(c, str) and _norm(c):
                    clave = next((k for texto, k in ETIQUETAS if _norm(c).startswith(texto)), None)
                    if clave:
                        break
            if not clave or clave in resumen:
                continue
            nums = [float(c) for c in celdas if isinstance(c, (int, float)) and not isinstance(c, bool) and not pd.isna(c)]
            if len(nums) >= 2:
                resumen[clave] = (nums[0], nums[1], nums[2] if len(nums) >= 3 else nums[0] + nums[1])
        if not resumen:
            raise ExcelNoReconocido("El Excel tiene la tabla de ventas, pero no el resumen con Total sales, Water Sells y los demás renglones.")
        return {"archivo": Path(str(nombre)).name, "tabla": tabla.reset_index(drop=True), "resumen": resumen}
    raise ExcelNoReconocido("No es el Excel integrado: no tiene una hoja con las columnas Source, Machine, Product, Cash Sales y Credit Sales.")


def _faltantes(objetivo: float, candidatos: list[tuple[str, float]], maximo: int = 2) -> list[str] | None:
    """Busca una o dos maquinas cuya venta sea exactamente la diferencia."""
    for n in range(1, maximo + 1):
        for combo in itertools.combinations(candidatos, n):
            if abs(sum(v for _, v in combo) - objetivo) < 0.005:
                return [k for k, _ in combo]
    return None


def comparar(original: dict, res: dict, maquinas: pd.DataFrame) -> dict:
    """Devuelve las filas de la comparacion: concepto, original, app, diferencia y causas."""
    T, S = original["tabla"], original["resumen"]
    p, R, pm, det = res["pasos"], res["reglas"], res["maquinas"], res["detalle"]
    T = T.assign(venta=T["Cash Sales"] + T["Credit Sales"])
    ciudad = dict(zip(maquinas["id_maquina"], maquinas["ciudad"]))
    J = R["jurisdicciones"]

    def jur(idm: str) -> str:
        c = str(ciudad.get(idm, "")).lower()
        return next((k for k, v in J.items() if c in [x.lower() for x in v["ciudades"]]), "")

    T["jurisdiccion"] = T["id_maquina"].map(jur)
    tot = lambda k: S[k][2] if k in S else None  # noqa: E731
    filas = []

    def fila(concepto: str, orig, app, causas: list[str]):
        dif = None if orig is None else round(app - orig, 2)
        filas.append({"concepto": concepto, "original": None if orig is None else round(orig, 2), "app": round(app, 2),
                      "dif": dif, "causas": [] if dif is not None and abs(dif) < 0.005 else causas})

    # ---- 1. ventas en efectivo y tarjeta ----
    causas = []
    a = det.assign(venta=det["efectivo"] + det["tarjeta"]).groupby(["fuente", "id_maquina"]).agg(
        venta=("venta", "sum"), maquina=("maquina", "first"))
    o = T.groupby(["Source", "id_maquina"]).agg(venta=("venta", "sum"), maquina=("Machine", "first"))
    o.index.names = ["fuente", "id_maquina"]
    for clave in sorted(set(a.index) | set(o.index)):
        va = float(a["venta"].get(clave, 0.0))
        vo = float(o["venta"].get(clave, 0.0))
        if abs(va - vo) < 0.005:
            continue
        nombre = (a["maquina"].get(clave) if clave in a.index else o["maquina"].get(clave)) or clave[1]
        if clave not in o.index:
            causas.append(f"El Excel no trae la máquina “{nombre}” del reporte de {clave[0]}: {_plata(va)}.")
        elif clave not in a.index:
            causas.append(f"El Excel trae “{nombre}” ({clave[0]}), que no está en los reportes subidos: {_plata(vo)}.")
        else:
            causas.append(f"“{nombre}” ({clave[0]}): la aplicación suma {_plata(va)} y el Excel {_plata(vo)}.")
    suma_tabla = float(T["venta"].sum())
    if "ventas" in S and abs(suma_tabla - S["ventas"][2]) > 0.005:
        causas.append(f"El total digitado en el resumen ({_plata(S['ventas'][2])}) no es la suma de la tabla del mismo Excel ({_plata(suma_tabla)}).")
    ventas_o = tot("ventas") if "ventas" in S else suma_tabla
    fila("Ventas en efectivo y tarjeta", ventas_o, p["ventas"]["total"], causas[:8])

    # ---- 2. devoluciones y ventas netas ----
    if "neto" in S and ventas_o:
        dev_o = ventas_o - S["neto"][2]
        pct = dev_o / ventas_o * 100
        causas = []
        cerca = round(pct)
        if abs(pct - cerca) < 0.15 and cerca > 0:
            exacto = ventas_o * cerca / 100
            causas.append(f"El Excel no usa los cupones: resta un {cerca} % fijo de lo vendido ({_plata(exacto)}).")
            if abs(dev_o - exacto) > 0.005:
                causas.append(f"Además su fórmula resta {_plata(dev_o - exacto)} de más, por una celda mal referenciada.")
        if p["devoluciones_metodo"] == "cupones":
            causas.append(f"La aplicación resta los cupones de reembolso que trae el reporte ({_plata(p['devoluciones']['total'])}) "
                          f"y suma como venta los cupones que compraron las empresas ({_plata(p['cupones_empresa']['total'])}).")
            causas.append("Para calcular como el Excel, en Reglas elija “Porcentaje fijo”.")
        else:
            causas.append(f"La aplicación resta el {p['devoluciones_pct']:g} % máquina por máquina y redondea al centavo.")
        fila("Devoluciones a clientes", dev_o, p["devoluciones"]["total"], causas)
        fila("Ventas netas", S["neto"][2], p["neto"]["total"], ["Sale de los dos renglones anteriores."])

    # ---- 3. agua ----
    if "agua" in S:
        con_water = T[T["Product"].astype(str).str.contains(r"\bwater\b|\bagua\b", case=False, regex=True)]
        suma_water = float(con_water["venta"].sum())
        causas = []
        if abs(suma_water - S["agua"][2]) > 0.005:
            causas.append(f"La cifra del Excel está digitada y no sale de su tabla: allí los productos que dicen “water” suman {_plata(suma_water)}.")
        exentos = set(res["lista_exentos"])
        fuera = con_water[~con_water["Product"].isin(exentos)].groupby("Product")["venta"].sum().sort_values(ascending=False)
        if len(fuera):
            lista = ", ".join(f"{n} ({_plata(v)})" for n, v in fuera.head(5).items())
            causas.append(f"La aplicación no marcó como agua: {lista}. Si son exentos, márquelos en el paso 2.")
        fila("Agua", S["agua"][2], p["agua"]["total"], causas)

    # ---- 4. comprado con impuesto pagado ----
    if "walmart" in S:
        marcados = det[det["impuesto_pagado"]].assign(v=lambda x: x["efectivo"] + x["tarjeta"]).groupby("producto")["v"].sum()
        lista = ", ".join(f"{n} ({_plata(v)})" for n, v in marcados.sort_values(ascending=False).head(6).items())
        fila("Comprado con impuesto pagado", S["walmart"][2], p["walmart"]["total"], [
            "La cifra del Excel está digitada: depende de los productos que el gerente eligió en el filtro ese mes.",
            f"La aplicación descontó: {lista or 'ninguno'}. La lista se ajusta en el paso 2."])
    if "gravable" in S:
        fila("Ventas gravables", S["gravable"][2], p["gravable"]["total"], ["Sale de los renglones anteriores."])

    # ---- 5. maquinas de Houston y del MTA ----
    def local(nombre: str, clave_bruto: str | None, clave_base: str, etiqueta: str):
        en_t = T[T["jurisdiccion"] == nombre]
        bruto_tabla = float(en_t["venta"].sum())
        bruto_app = float(pm.loc[pm["jurisdiccion"] == nombre, ["efectivo", "tarjeta"]].sum().sum())
        if clave_bruto and clave_bruto in S:
            causas = []
            dif = bruto_tabla - S[clave_bruto][2]
            if abs(dif) > 0.005:
                por_maq = en_t.groupby("Machine")["venta"].sum()
                faltan = _faltantes(dif, [(k, float(v)) for k, v in por_maq.items() if 0 < v <= dif + 0.005]) if dif > 0 else None
                if faltan:
                    causas.append(f"Al filtrar a mano las máquinas de {nombre} se quedó por fuera “{'” y “'.join(faltan)}” ({_plata(dif)}).")
                else:
                    causas.append(f"Con la lista de máquinas, la tabla del mismo Excel suma {_plata(bruto_tabla)} para {nombre}, no {_plata(S[clave_bruto][2])}.")
            if abs(bruto_app - bruto_tabla) > 0.005:
                causas.append(f"La aplicación suma {_plata(bruto_app - bruto_tabla)} más por las máquinas que el Excel no trae.")
            fila(f"Ventas de las máquinas de {etiqueta}", S[clave_bruto][2], bruto_app, causas)
        if clave_base in S:
            b = p[f"base_{nombre}"]["total"]
            fila(f"Base de {J[nombre]['nombre_comptroller']}", S[clave_base][2], b, [
                f"El Excel toma la venta de esas máquinas sin quitarles el agua ({_plata(p[f'agua_{nombre}']['total'])}) "
                "ni las devoluciones" + (", y le resta las compras con impuesto pagado de todas las ciudades." if clave_bruto else "."),
                "La aplicación usa las ventas gravables de esas mismas máquinas, que es la base sobre la que QuickBooks cobra el 1 %."])

    if "Houston" in J:
        local("Houston", "houston_bruto", "houston", "Houston")
    if "Houston MTA" in J:
        local("Houston MTA", None, "mta", "Houston MTA")

    return {"archivo": original["archivo"], "filas": filas,
            "iguales": sum(1 for f in filas if f["dif"] is not None and abs(f["dif"]) < 0.005), "total": len(filas)}
