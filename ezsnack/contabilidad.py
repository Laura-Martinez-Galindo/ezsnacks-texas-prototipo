"""Registro del cierre en el sistema contable (QuickBooks Online).

El cierre deja dos cosas por pagar, y se registran como facturas de proveedor (Bill):
el impuesto a favor del Texas Comptroller, con vencimiento el 20 del mes siguiente, y la
comision de cada socio. Si el mes ya se registro, no se duplica (se busca por numero de documento).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from .qbo import QBO

CUENTA_IMPUESTO = ("Sales Tax Paid to Texas Comptroller", "Expense", "TaxesPaid")
CUENTA_COMISIONES = ("Location Commissions", "Expense", "OtherMiscellaneousServiceCost")


def _esc(t: str) -> str:
    return str(t).replace("\\", "\\\\").replace("'", "\\'")


def _cuenta(qbo: QBO, nombre: str, tipo: str, subtipo: str) -> str:
    filas = qbo.query(f"select * from Account where Name = '{_esc(nombre)}'")
    if filas:
        return filas[0]["Id"]
    return qbo.crear("Account", {"Name": nombre, "AccountType": tipo, "AccountSubType": subtipo})["Id"]


def _proveedor(qbo: QBO, nombre: str) -> str:
    filas = qbo.query(f"select * from Vendor where DisplayName = '{_esc(nombre)}'")
    if filas:
        return filas[0]["Id"]
    return qbo.crear("Vendor", {"DisplayName": nombre})["Id"]


def _factura(qbo: QBO, proveedor: str, numero: str, fecha: str, vence: str, valor: float,
             cuenta: str, descripcion: str) -> dict:
    existe = qbo.query(f"select * from Bill where DocNumber = '{_esc(numero)}'")
    if existe:
        return {"documento": numero, "estado": "ya existia", "valor": float(existe[0].get("TotalAmt", valor))}
    qbo.crear("Bill", {
        "VendorRef": {"value": proveedor}, "DocNumber": numero, "TxnDate": fecha, "DueDate": vence,
        "PrivateNote": descripcion,
        "Line": [{"DetailType": "AccountBasedExpenseLineDetail", "Amount": round(valor, 2), "Description": descripcion,
                  "AccountBasedExpenseLineDetail": {"AccountRef": {"value": cuenta}}}],
    })
    return {"documento": numero, "estado": "creado", "valor": round(valor, 2)}


def registrar(qbo: QBO, res: dict, anio: int, mes: int) -> list[dict]:
    dcl = res["declaracion"]
    fin = date(anio, mes, monthrange(anio, mes)[1]).isoformat()
    yymm = f"{anio % 100:02d}{mes:02d}"
    salida = []

    cuenta = _cuenta(qbo, *CUENTA_IMPUESTO)
    prov = _proveedor(qbo, "Texas Comptroller")
    locales = ", ".join(f"{l['nombre_comptroller']} {l['impuesto']:.2f}" for l in dcl["locales"])
    r = _factura(qbo, prov, f"TX{yymm}", fin, dcl["vence"], dcl["a_pagar"], cuenta,
                 f"Sales and Use Tax {mes:02d}/{anio}. Estado {dcl['impuesto_estado']:.2f}; {locales}; "
                 f"descuento por pago a tiempo {dcl['descuento']:.2f}.")
    salida.append({"concepto": "Impuesto a las ventas", "a_nombre_de": "Texas Comptroller", **r})

    cuenta_c = None
    for s in res["comisiones"]["socios"]:
        if s["por_confirmar"] or s["comision"] <= 0:
            continue
        cuenta_c = cuenta_c or _cuenta(qbo, *CUENTA_COMISIONES)
        prov = _proveedor(qbo, s["socio"])
        r = _factura(qbo, prov, f"COM{yymm}-{prov}", fin, fin, s["comision"], cuenta_c,
                     f"Comisión {mes:02d}/{anio}: {s['con_comision']} de {s['maquinas']} máquinas. {s['regla']}")
        salida.append({"concepto": "Comisión", "a_nombre_de": s["socio"], **r})
    return salida
