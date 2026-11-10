"""Deja la empresa de prueba (sandbox) de QuickBooks solo con los datos de EzSnack.

Borra todas las transacciones de prueba, deja inactivos los productos, proveedores y clientes que
no usa la integracion y pone el nombre y la direccion de la empresa. Nunca corre en una empresa real.
"""
from __future__ import annotations

import os

from .contabilidad import CLIENTE, ITEMS, LOTE
from .qbo import QBO

TRANSACCIONES = ["Deposit", "Payment", "BillPayment", "Transfer", "RefundReceipt", "SalesReceipt", "CreditMemo",
                 "Invoice", "Estimate", "VendorCredit", "Purchase", "Bill", "PurchaseOrder", "JournalEntry", "TimeActivity"]
EMPRESA = {"CompanyName": "EzSnack Texas", "LegalName": "Ez Snack Texas Corp",
           "CompanyAddr": {"Line1": "4520 W 34th St Ste G", "City": "Houston", "CountrySubDivisionCode": "TX",
                           "PostalCode": "77092", "Country": "US"}}


def es_sandbox() -> bool:
    return os.getenv("QBO_ENVIRONMENT", "sandbox") == "sandbox"


def _lotes(qbo: QBO, pedidos: list[dict]) -> int:
    fallas = 0
    for i in range(0, len(pedidos), LOTE):
        resp = qbo._peticion("POST", "batch", json_body={"BatchItemRequest": pedidos[i:i + LOTE]})
        fallas += sum("Fault" in r for r in resp.get("BatchItemResponse", []))
    return fallas


def limpiar(qbo: QBO) -> dict:
    if not es_sandbox():
        raise RuntimeError("Solo funciona en la empresa de prueba.")
    resumen = {"borradas": {}, "inactivados": {}, "no_se_pudo": 0}
    for entidad in TRANSACCIONES:
        filas = qbo.query(f"select * from {entidad}")
        if not filas:
            continue
        pedidos = [{"bId": f"{entidad}{f['Id']}", "operation": "delete",
                    entidad: {"Id": f["Id"], "SyncToken": f["SyncToken"]}} for f in filas]
        fallas = _lotes(qbo, pedidos)
        resumen["borradas"][entidad] = len(filas) - fallas
        resumen["no_se_pudo"] += fallas

    conservar = {"Item": {n for n, _ in ITEMS.values()}, "Customer": {CLIENTE}, "Vendor": set()}
    for entidad, campo in (("Item", "Name"), ("Customer", "DisplayName"), ("Vendor", "DisplayName")):
        filas = [f for f in qbo.query(f"select * from {entidad} where Active = true")
                 if f.get(campo) not in conservar[entidad] and f.get("Type") != "Category"]
        if not filas:
            continue
        pedidos = [{"bId": f"{entidad}{f['Id']}", "operation": "update",
                    entidad: {"Id": f["Id"], "SyncToken": f["SyncToken"], "sparse": True, "Active": False}} for f in filas]
        fallas = _lotes(qbo, pedidos)
        resumen["inactivados"][entidad] = len(filas) - fallas
        resumen["no_se_pudo"] += fallas

    try:
        info = qbo.info_empresa()
        qbo._peticion("POST", "companyinfo", json_body={"Id": info["Id"], "SyncToken": info["SyncToken"], "sparse": True, **EMPRESA})
        resumen["empresa"] = EMPRESA["CompanyName"]
    except Exception as exc:  # noqa: BLE001
        resumen["empresa"] = f"No se pudo cambiar el nombre: {exc}"
    return resumen
