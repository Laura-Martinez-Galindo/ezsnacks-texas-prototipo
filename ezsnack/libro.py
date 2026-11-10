"""Libro de Excel del cierre: el respaldo que la empresa guarda para una auditoria del estado."""
from __future__ import annotations

import io

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

MARINO = "0F3D5E"
DINERO = '#,##0.00'


def _hoja(w, nombre: str, df: pd.DataFrame, columnas: dict[str, str], dinero: set[str] = frozenset()):
    df = df[list(columnas)].rename(columns=columnas)
    df.to_excel(w, sheet_name=nombre, index=False)
    ws = w.sheets[nombre]
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=MARINO)
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    nombres = list(columnas.values())
    for i, titulo in enumerate(nombres, start=1):
        letra = get_column_letter(i)
        largo = max([len(str(titulo))] + [len(str(v)) for v in df[titulo].head(300)])
        ws.column_dimensions[letra].width = min(max(10, largo + 2), 60)
        if list(columnas)[i - 1] in dinero:
            for celda in ws[letra][1:]:
                celda.number_format = DINERO


def libro(res: dict, lecturas: list, anio: int, mes: int) -> bytes:
    p, dcl = res["pasos"], res["declaracion"]
    resumen = [
        ("Cierre", f"{mes:02d}/{anio}"),
        ("Vence", dcl["vence"]),
        ("", ""),
        ("Ventas en efectivo", p["efectivo"]),
        ("Ventas con tarjeta", p["tarjeta"]),
        ("Ventas de equipos", p["equipos"]),
        ("Ventas totales", p["total"]),
        (f"Devoluciones a clientes ({p['devoluciones_pct']:g} %)", -p["devoluciones"]),
        ("Ventas netas", p["neto"]),
        ("Ventas exentas (agua)", -p["exentas"]),
        ("Ventas de productos comprados con impuesto pagado", -p["pagadas"]),
        ("Ventas gravables", p["gravable"]),
        ("", ""),
        ("Texas Comptroller, Sales and Use Tax", ""),
        ("Total Texas Sales", dcl["total_ventas"]),
        ("Taxable Sales", dcl["ventas_gravables"]),
        ("Taxable Purchases", dcl["compras_gravables"]),
        ("Subject to State Tax (Rate .0625)", dcl["sujeto_estado"]),
        ("State Tax Due", dcl["impuesto_estado"]),
    ]
    for l in dcl["locales"]:
        resumen.append((f"{l['codigo']} {l['nombre_comptroller']}, amount subject to local tax", l["base"]))
        resumen.append((f"{l['codigo']} {l['nombre_comptroller']}, local tax due ({l['tasa']:g} %)", l["impuesto"]))
    resumen += [("Total Tax Due", dcl["impuesto_total"]), ("Timely Filing Discount", -dcl["descuento"]),
                ("Total Amount Due and Payable", dcl["a_pagar"])]

    archivos = pd.DataFrame([{
        "archivo": l.archivo, "fuente": l.fuente, "periodo": l.periodo, "leidas": l.leidas,
        "usadas": len(l.filas), "descartadas": "; ".join(f"{k}: {v}" for k, v in l.descartadas.items() if v),
        "efectivo": round(float(l.filas["efectivo"].sum()), 2), "tarjeta": round(float(l.filas["tarjeta"].sum()), 2),
        "cupones": round(float(l.filas["cupones"].sum()), 2),
        "prepago": round(float(l.filas["prepago"].sum() + l.filas["otros"].sum()), 2),
    } for l in lecturas])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(resumen, columns=["Concepto", "Valor"]).to_excel(w, sheet_name="Resumen", index=False)
        ws = w.sheets["Resumen"]
        ws.column_dimensions["A"].width = 62
        ws.column_dimensions["B"].width = 18
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=MARINO)
        for fila in ws.iter_rows(min_row=2):
            if isinstance(fila[1].value, (int, float)):
                fila[1].number_format = DINERO
            if fila[0].value in ("Ventas gravables", "Total Amount Due and Payable", "Texas Comptroller, Sales and Use Tax"):
                fila[0].font = Font(bold=True)
                fila[1].font = Font(bold=True)

        _hoja(w, "Ventas integradas", res["detalle"], {
            "fuente": "Fuente", "id_maquina": "Máquina", "maquina": "Nombre en el lector", "producto": "Producto",
            "cantidad": "Cantidad", "efectivo": "Efectivo", "tarjeta": "Tarjeta", "cupones": "Cupones",
            "prepago": "Prepago", "otros": "Monyx", "ventas": "Ventas", "ciudad": "Ciudad", "jurisdiccion": "Jurisdicción local",
            "exento": "Exento", "impuesto_pagado": "Comprado con impuesto pagado"},
            {"efectivo", "tarjeta", "cupones", "prepago", "otros", "ventas"})
        _hoja(w, "Por máquina", res["maquinas"], {
            "id_maquina": "Máquina", "maquina": "Nombre en el lector", "fuente": "Lector", "locacion": "Locación",
            "ciudad": "Ciudad", "jurisdiccion": "Jurisdicción local", "comision_a": "Comisión a", "unidades": "Unidades",
            "efectivo": "Efectivo", "tarjeta": "Tarjeta", "ventas": "Ventas", "exentas": "Exentas",
            "pagadas": "Con impuesto pagado", "gravable": "Gravable después de devoluciones"},
            {"efectivo", "tarjeta", "ventas", "exentas", "pagadas", "gravable"})
        _hoja(w, "Comisiones", pd.DataFrame(res["comisiones"]["detalle"] or [{}], columns=[
            "socio", "id_maquina", "maquina", "ventas", "tarjeta", "descuento_tarjeta", "costo_lector", "base", "aplica", "comision"]), {
            "socio": "Socio", "id_maquina": "Máquina", "maquina": "Nombre", "ventas": "Ventas", "tarjeta": "Con tarjeta",
            "descuento_tarjeta": "Descuento por tarjeta", "costo_lector": "Costo del lector", "base": "Base",
            "aplica": "Aplica", "comision": "Comisión"},
            {"ventas", "tarjeta", "descuento_tarjeta", "costo_lector", "base", "comision"})
        _hoja(w, "Archivos", archivos, {
            "archivo": "Archivo", "fuente": "Lector", "periodo": "Periodo", "leidas": "Filas leídas", "usadas": "Filas usadas",
            "descartadas": "Filas que no se usaron", "efectivo": "Efectivo", "tarjeta": "Tarjeta", "cupones": "Cupones",
            "prepago": "Prepago y Monyx"}, {"efectivo", "tarjeta", "cupones", "prepago"})
    return buf.getvalue()
