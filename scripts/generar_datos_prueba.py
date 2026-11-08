"""Genera Excel de PRUEBA (vendor list y reportes de Nayax / AB360) para septiembre de 2026.

Las direcciones de las maquinas 158 y 160 salen de las capturas del Explorer Workshop.
Las demas usan edificios publicos como direccion de ejemplo (alcaldias, centro de convenciones)
para que QuickBooks pueda ubicar la jurisdiccion. Todo es ficticio y debe reemplazarse
por los archivos reales de Humberto.

Uso: python scripts/generar_datos_prueba.py
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

random.seed(2026)
SALIDA = Path("datos_prueba")
SALIDA.mkdir(exist_ok=True)
CATALOGO = json.loads(Path("config/catalogo.json").read_text(encoding="utf-8"))
PRECIOS = {p["nombre"]: p["precio"] for p in CATALOGO["productos"]}
SOCIO = CATALOGO["socios"][0]

MAQUINAS = [
    # id, locacion, direccion, ciudad, zip, sistema, jurisdiccion, socio
    ("158", "Triac Electric", "1823 Haden Rd", "Houston", "77015", "Nayax", "Houston", ""),
    ("160", "Crate & Barrel", "4006 Westheimer Rd", "Houston", "77027", "AB360", "Houston", ""),
    ("101", "Oficinas centro (prueba)", "901 Bagby St", "Houston", "77002", "Nayax", "Houston", ""),
    ("112", "Centro de convenciones (prueba)", "1001 Avenida De Las Americas", "Houston", "77010", "Nayax", "Houston", ""),
    ("116", "Universidad (prueba)", "7008 S Rice Ave", "Bellaire", "77401", "Nayax", "MTA", SOCIO["nombre"]),
    ("130", "Bodega Katy (prueba)", "901 Avenue C", "Katy", "77493", "AB360", "MTA", ""),
    ("136", "Lavanderia (prueba)", "1025 Campbell Rd", "Houston", "77055", "Nayax", "MTA", SOCIO["nombre"]),
]

# Como aparecen los productos en cada reporte (AB360 abrevia algunos, para probar el emparejamiento)
NOMBRE_AB360 = {
    "Doritos Nacho Cheese 1 oz": "DORITOS NCH 1OZ",
    "Gatorade Variety 20 oz": "Gatorade 20oz Variety",
    "Classic Coke 12 oz": "Coca Cola 12oz",
    "Ozarka Water 16 oz": "OZARKA 16OZ",
}
EXTRA_NO_REGISTRADO = ("Cheetos Crunchy 1 oz", 1.75)


def vendor_list() -> None:
    filas = [{
        "ID": m[0], "Locacion": m[1], "Direccion": m[2], "Ciudad": m[3], "Estado": "TX", "ZIP": m[4],
        "Sistema": m[5], "Jurisdiccion": m[6], "Socio": m[7],
        "Comision %": SOCIO["pct_comision"] if m[7] else 0,
    } for m in MAQUINAS]
    pd.DataFrame(filas).to_excel(SALIDA / "vendor_list_PRUEBA.xlsx", index=False)


def ventas(sistema: str) -> pd.DataFrame:
    filas = []
    inicio = date(2026, 9, 1)
    maquinas = [m for m in MAQUINAS if m[5] == sistema]
    if sistema == "Nayax":  # una maquina que no esta en el vendor list, para ver la alerta
        maquinas.append(("999", "Nueva maquina", "", "", "", "Nayax", "", ""))
    for m in maquinas:
        surtido = random.sample(list(PRECIOS), 14)
        for dia in range(30):
            fecha = inicio + timedelta(days=dia)
            for prod in random.sample(surtido, random.randint(4, 9)):
                qty = random.randint(1, 6)
                pago = random.choices(["Credit Card", "Cash"], weights=[7, 3])[0]
                nombre = NOMBRE_AB360.get(prod, prod) if sistema == "AB360" else prod
                filas.append((m, fecha, nombre, qty, round(qty * PRECIOS[prod], 2), pago))
            if sistema == "AB360" and dia % 7 == 0:
                n, precio = EXTRA_NO_REGISTRADO
                filas.append((m, fecha, n, 2, round(2 * precio, 2), "Cash"))
    if sistema == "Nayax":
        return pd.DataFrame([{
            "Date": f.strftime("%m/%d/%Y"), "Machine": f"EzSnack {m[0]} - {m[2]} - {m[1]}".rstrip(" -"),
            "Product": n, "Quantity": q, "Total": t, "Payment Method": p,
        } for m, f, n, q, t, p in filas])
    return pd.DataFrame([{
        "Sale Date": f.isoformat(), "Machine Name": f"EzSnack {m[0]} - {m[1]}",
        "Item": n, "Qty Sold": q, "Sales $": f"${t:,.2f}", "Tender": p,
    } for m, f, n, q, t, p in filas])


if __name__ == "__main__":
    vendor_list()
    ventas("Nayax").to_excel(SALIDA / "nayax_ventas_2026-09_PRUEBA.xlsx", index=False)
    ventas("AB360").to_excel(SALIDA / "ab360_ventas_2026-09_PRUEBA.xlsx", index=False)
    print("Listo: archivos de prueba en", SALIDA.resolve())
