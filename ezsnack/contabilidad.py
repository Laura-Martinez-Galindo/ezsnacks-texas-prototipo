"""Envio de las ventas del mes a QuickBooks Online, que calcula el impuesto con su modulo de Sales Tax.

Por cada maquina se crea un recibo de venta (Sales Receipt) con la direccion de la maquina. Con esa
direccion QuickBooks decide que impuestos aplican (estado, ciudad y MTA) y los calcula. El recibo
lleva hasta tres renglones: ventas gravables, agua (exenta) y productos comprados con impuesto pagado.
Si el mes ya se habia enviado, los recibos se actualizan en lugar de duplicarse.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

import pandas as pd

from .qbo import QBO, QBOError

CLIENTE = "Consumidores en maquinas"
CUENTA_INGRESOS = "Ventas en maquinas"
ITEMS = {  # nombre en QuickBooks -> paga impuesto
    "gravable": ("Vending sales - taxable", True),
    "exentas": ("Vending sales - water (exempt)", False),
    "pagadas": ("Vending sales - sales tax paid at purchase", False),
}
LOTE = 25


def _esc(t: str) -> str:
    return str(t).replace("\\", "\\\\").replace("'", "\\'")


def _asegurar(qbo: QBO, entidad: str, campo: str, nombre: str, cuerpo: dict) -> dict:
    filas = qbo.query(f"select * from {entidad} where {campo} = '{_esc(nombre)}'")
    if not filas and entidad != "Account":
        filas = qbo.query(f"select * from {entidad} where Active = false and {campo} = '{_esc(nombre)}'")
        if filas:
            return qbo.actualizar(entidad, {"Id": filas[0]["Id"], "SyncToken": filas[0]["SyncToken"], "Active": True})
    return filas[0] if filas else qbo.crear(entidad, cuerpo)


def _preparar(qbo: QBO) -> tuple[str, dict[str, str]]:
    cuenta = _asegurar(qbo, "Account", "Name", CUENTA_INGRESOS, {"Name": CUENTA_INGRESOS, "AccountType": "Income"})["Id"]
    cliente = _asegurar(qbo, "Customer", "DisplayName", CLIENTE, {"DisplayName": CLIENTE})["Id"]
    items = {}
    for clave, (nombre, gravable) in ITEMS.items():
        items[clave] = _asegurar(qbo, "Item", "Name", nombre, {
            "Name": nombre, "Type": "Service", "Taxable": gravable, "IncomeAccountRef": {"value": cuenta}})["Id"]
    return cliente, items


def _recibo(m, cliente: str, items: dict, anio: int, mes: int, fecha: str) -> dict | None:
    lineas = []
    for clave, (nombre, gravable) in ITEMS.items():
        valor = round(float(m[clave]), 2)
        if valor <= 0:
            continue
        lineas.append({
            "DetailType": "SalesItemLineDetail", "Amount": valor,
            "Description": f"{nombre} {mes:02d}/{anio}",
            "SalesItemLineDetail": {"ItemRef": {"value": items[clave]}, "Qty": 1, "UnitPrice": valor,
                                    "TaxCodeRef": {"value": "TAX" if gravable else "NON"}},
        })
    if not lineas:
        return None
    r = {
        "DocNumber": f"V{anio % 100:02d}{mes:02d}-{m['id_maquina'] or 'X'}"[:21],
        "TxnDate": fecha, "CustomerRef": {"value": cliente},
        "PrivateNote": f"Ventas {mes:02d}/{anio} de {m['maquina']}. Generado por EzSnack Impuestos."[:4000],
        "Line": lineas,
    }
    if m["direccion"] and m["ciudad"]:
        # Lugar de la venta: con esta direccion QuickBooks decide los impuestos locales
        r["ShipFromAddr"] = {"Line1": str(m["direccion"]), "City": str(m["ciudad"]),
                             "CountrySubDivisionCode": str(m["estado"] or "TX"), "PostalCode": str(m["zip"]),
                             "Country": "USA"}
    return r


def enviar(qbo: QBO, maquinas: pd.DataFrame, anio: int, mes: int) -> dict:
    cliente, items = _preparar(qbo)
    fecha = date(anio, mes, monthrange(anio, mes)[1]).isoformat()
    prefijo = f"V{anio % 100:02d}{mes:02d}-"
    existentes = {r["DocNumber"]: r for r in qbo.query(
        f"select * from SalesReceipt where TxnDate = '{fecha}'") if str(r.get("DocNumber", "")).startswith(prefijo)}

    pedidos = []
    for _, m in maquinas.iterrows():
        r = _recibo(m, cliente, items, anio, mes, fecha)
        if r is None:
            continue
        previo = existentes.get(r["DocNumber"])
        if previo:
            r.update(Id=previo["Id"], SyncToken=previo["SyncToken"], sparse=False)
        pedidos.append({"bId": r["DocNumber"], "operation": "update" if previo else "create", "SalesReceipt": r})

    recibos, errores = [], []
    for i in range(0, len(pedidos), LOTE):
        lote = pedidos[i:i + LOTE]
        resp = qbo._peticion("POST", "batch", json_body={"BatchItemRequest": lote})
        operacion = {p["bId"]: p["operation"] for p in lote}
        for item in resp.get("BatchItemResponse", []):
            if "SalesReceipt" in item:
                recibos.append((operacion.get(item.get("bId")), item["SalesReceipt"]))
            else:
                err = (item.get("Fault", {}).get("Error") or [{}])[0]
                errores.append({"recibo": item.get("bId"), "error": f"{err.get('Message', '')} {err.get('Detail', '')}".strip()})

    tasas = {t["Id"]: t for t in qbo.query("select * from TaxRate")}
    por_tasa: dict[str, dict] = {}
    filas = []
    for operacion, r in recibos:
        detalle = r.get("TxnTaxDetail", {})
        for linea in detalle.get("TaxLine", []):
            d = linea.get("TaxLineDetail", {})
            t = tasas.get(d.get("TaxRateRef", {}).get("value"), {})
            nombre = t.get("Name") or "Sin nombre"
            acum = por_tasa.setdefault(nombre, {"jurisdiccion": nombre, "tasa": float(d.get("TaxPercent") or 0),
                                                "base": 0.0, "impuesto": 0.0, "recibos": 0})
            acum["base"] += float(d.get("NetAmountTaxable") or 0)
            acum["impuesto"] += float(linea.get("Amount") or 0)
            acum["recibos"] += 1
        filas.append({"recibo": r.get("DocNumber"), "estado": "actualizado" if operacion == "update" else "creado",
                      "total": float(r.get("TotalAmt") or 0), "impuesto": float(detalle.get("TotalTax") or 0)})
    for v in por_tasa.values():
        v["base"], v["impuesto"] = round(v["base"], 2), round(v["impuesto"], 2)
    otros = [n for n in existentes if n not in {p["bId"] for p in pedidos}]
    return {
        "recibos": filas, "errores": errores,
        "creados": sum(f["estado"] == "creado" for f in filas),
        "actualizados": sum(f["estado"] == "actualizado" for f in filas),
        "por_jurisdiccion": sorted(por_tasa.values(), key=lambda v: -v["impuesto"]),
        "impuesto": round(sum(f["impuesto"] for f in filas), 2),
        "ventas": round(sum(f["total"] - f["impuesto"] for f in filas), 2),
        "otros_del_mes": sorted(otros),
    }


__all__ = ["enviar", "QBOError"]
