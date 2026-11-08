"""Preparar el sandbox: quitar los datos de ejemplo de Intuit y cargar los de EzSnack.

Se usa desde la app (pestaña "Preparar sandbox") o desde scripts/preparar_sandbox.py.
Solo funciona con QBO_ENVIRONMENT=sandbox.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .qbo import QBO, QBOError

CATALOGO = json.loads(Path("config/catalogo.json").read_text(encoding="utf-8"))

# Orden: primero lo que contiene a otras transacciones (un deposito agrupa pagos, un pago cierra facturas)
TRANSACCIONES = [
    "Deposit", "Payment", "BillPayment", "Transfer", "RefundReceipt", "SalesReceipt",
    "CreditMemo", "Invoice", "Estimate", "VendorCredit", "Purchase", "Bill",
    "PurchaseOrder", "JournalEntry", "TimeActivity",
]
LISTAS = ["Customer", "Vendor", "Item"]


def es_sandbox() -> bool:
    return os.getenv("QBO_ENVIRONMENT", "sandbox") == "sandbox"


def nombres_ezsnack() -> set[str]:
    n = {p["nombre"] for p in CATALOGO["productos"]}
    n |= {p["nombre"] for p in CATALOGO["proveedores"]}
    n |= {s["nombre"] for s in CATALOGO["socios"]}
    n.add(CATALOGO["cliente_ventas"])
    return n


def plan_limpieza(qbo: QBO) -> dict:
    """Lo que se borraria / inactivaria. No cambia nada."""
    propios = nombres_ezsnack()
    tx = {t: qbo.query(f"select Id, SyncToken from {t}") for t in TRANSACCIONES}
    listas = {}
    for entidad in LISTAS:
        campo = "Name" if entidad == "Item" else "DisplayName"
        filas = qbo.query(f"select * from {entidad} where Active = true")
        listas[entidad] = [f for f in filas if f.get(campo) not in propios]
    return {"transacciones": tx, "listas": listas}


def resumen_plan(plan: dict) -> list[dict]:
    filas = [{"accion": "Borrar", "tipo": t, "cantidad": len(v)} for t, v in plan["transacciones"].items() if v]
    filas += [{"accion": "Inactivar", "tipo": e, "cantidad": len(v)} for e, v in plan["listas"].items() if v]
    return filas


def ejecutar_limpieza(qbo: QBO, plan: dict, progreso=None) -> list[str]:
    """Borra y luego inactiva. Devuelve la lista de errores (algunos registros del sistema no se pueden quitar)."""
    if not es_sandbox():
        raise QBOError("Por seguridad, la limpieza solo funciona en el sandbox.")
    errores = []
    pasos = [("borrar", t, f) for t, v in plan["transacciones"].items() for f in v]
    pasos += [("inactivar", e, f) for e, v in plan["listas"].items() for f in v]
    for i, (accion, entidad, f) in enumerate(pasos, 1):
        try:
            if accion == "borrar":
                qbo.borrar(entidad, f["Id"], f["SyncToken"])
            else:
                qbo.inactivar(entidad, f)
        except QBOError as exc:
            errores.append(f"{accion} {entidad} {f['Id']}: {exc}")
        if progreso:
            progreso(i / max(len(pasos), 1))
    return errores


def _cuenta(qbo: QBO, nombre: str, tipo: str) -> str:
    filas = qbo.query(f"select * from Account where Name = '{nombre}'")
    if filas:
        return filas[0]["Id"]
    return qbo.crear("Account", {"Name": nombre, "AccountType": tipo})["Id"]


def _asegurar(qbo: QBO, entidad: str, nombre: str, cuerpo: dict) -> str:
    campo = "Name" if entidad == "Item" else "DisplayName"
    seguro = nombre.replace("'", "\\'")
    filas = qbo.query(f"select * from {entidad} where {campo} = '{seguro}'")
    if not filas:  # puede existir inactivo de una corrida anterior
        filas = qbo.query(f"select * from {entidad} where Active = false and {campo} = '{seguro}'")
    if filas:
        f = filas[0]
        if not f.get("Active", True):
            qbo.actualizar(entidad, {"Id": f["Id"], "SyncToken": f["SyncToken"], "Active": True})
        return f["Id"]
    return qbo.crear(entidad, cuerpo)["Id"]


def cargar_datos(qbo: QBO) -> list[str]:
    """Crea (o reactiva) cuentas, productos, proveedores, socios y el cliente de ventas."""
    log = []
    c = CATALOGO["cuentas"]
    ingresos = _cuenta(qbo, c["ingresos_ventas"], "Income")
    costo = _cuenta(qbo, c["costo_mercancia"], "Cost of Goods Sold")
    _cuenta(qbo, c["impuesto_pagado_compras"], "Expense")
    _cuenta(qbo, c["comisiones"], "Expense")
    log.append("Cuentas contables listas (4).")

    for p in CATALOGO["productos"]:
        _asegurar(qbo, "Item", p["nombre"], {
            "Name": p["nombre"], "Type": "NonInventory", "UnitPrice": p["precio"],
            "Taxable": p["gravable"],
            "IncomeAccountRef": {"value": ingresos}, "ExpenseAccountRef": {"value": costo},
        })
    exentos = sum(not p["gravable"] for p in CATALOGO["productos"])
    log.append(f"Productos listos: {len(CATALOGO['productos'])} ({exentos} exentos).")

    for p in CATALOGO["proveedores"]:
        _asegurar(qbo, "Vendor", p["nombre"], {"DisplayName": p["nombre"], "Notes": f"Proveedor {p['tipo']}"})
    for s in CATALOGO["socios"]:
        _asegurar(qbo, "Vendor", s["nombre"], {"DisplayName": s["nombre"],
                                              "Notes": f"Socio de locaciones, {s['pct_comision']}%"})
    log.append(f"Proveedores listos: {len(CATALOGO['proveedores'])}, socios: {len(CATALOGO['socios'])}.")

    _asegurar(qbo, "Customer", CATALOGO["cliente_ventas"], {
        "DisplayName": CATALOGO["cliente_ventas"],
        "Notes": "Cliente generico para las ventas consolidadas de las maquinas",
    })
    log.append("Cliente de ventas listo.")
    return log
