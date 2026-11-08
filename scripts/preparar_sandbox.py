"""Deja el sandbox de QuickBooks con datos de EzSnack.

Uso (desde la carpeta del proyecto, despues de conectarse en la app):
    python scripts/preparar_sandbox.py --limpiar          # solo MUESTRA que se borraria
    python scripts/preparar_sandbox.py --limpiar --confirmar   # borra (pide escribir BORRAR)
    python scripts/preparar_sandbox.py --cargar           # crea cuentas, productos, proveedores y cliente

--limpiar borra las transacciones de ejemplo que trae el sandbox (facturas, pagos, gastos...)
y marca como inactivos los clientes, proveedores y productos de ejemplo
(QuickBooks no permite borrar listas, solo inactivarlas). No se puede deshacer.
SOLO usar en el sandbox, nunca en la empresa real.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ezsnack.qbo import QBO, QBOError  # noqa: E402

CATALOGO = json.loads(Path("config/catalogo.json").read_text(encoding="utf-8"))

# Orden pensado para borrar primero lo que depende de otras transacciones
TRANSACCIONES = [
    "Payment", "BillPayment", "Deposit", "Transfer", "RefundReceipt", "SalesReceipt",
    "CreditMemo", "Invoice", "Estimate", "VendorCredit", "Purchase", "Bill",
    "PurchaseOrder", "JournalEntry", "TimeActivity",
]
LISTAS = ["Customer", "Vendor", "Item"]


def nombres_ezsnack() -> set[str]:
    n = {p["nombre"] for p in CATALOGO["productos"]}
    n |= {p["nombre"] for p in CATALOGO["proveedores"]}
    n |= {s["nombre"] for s in CATALOGO["socios"]}
    n.add(CATALOGO["cliente_ventas"])
    return n


def limpiar(qbo: QBO, confirmar: bool) -> None:
    if os.getenv("QBO_ENVIRONMENT", "sandbox") != "sandbox":
        sys.exit("Por seguridad, la limpieza solo funciona con QBO_ENVIRONMENT=sandbox.")
    empresa = qbo.info_empresa().get("CompanyName")
    plan_tx = {t: qbo.query(f"select Id, SyncToken from {t}") for t in TRANSACCIONES}
    propios = nombres_ezsnack()
    plan_listas = {}
    for entidad in LISTAS:
        campo = "Name" if entidad == "Item" else "DisplayName"
        filas = qbo.query(f"select * from {entidad} where Active = true")
        plan_listas[entidad] = [f for f in filas if f.get(campo) not in propios]

    print(f"\nEmpresa: {empresa}")
    print("Se BORRARIAN estas transacciones de ejemplo:")
    for t, filas in plan_tx.items():
        if filas:
            print(f"  {t:15s} {len(filas)}")
    print("Se INACTIVARIAN estos registros de ejemplo:")
    for e, filas in plan_listas.items():
        print(f"  {e:15s} {len(filas)}")

    if not confirmar:
        print("\nNo se cambio nada. Para ejecutar: agregue --confirmar")
        return
    respuesta = input(f"\nEsto borra datos de '{empresa}' y NO se puede deshacer. Escriba BORRAR para seguir: ")
    if respuesta.strip() != "BORRAR":
        print("Cancelado. No se cambio nada.")
        return

    errores = 0
    for t, filas in plan_tx.items():
        for f in filas:
            try:
                qbo.borrar(t, f["Id"], f["SyncToken"])
            except QBOError as exc:
                errores += 1
                print(f"  No se pudo borrar {t} {f['Id']}: {exc}")
    for e, filas in plan_listas.items():
        for f in filas:
            try:
                qbo.inactivar(e, f)
            except QBOError as exc:
                errores += 1
                print(f"  No se pudo inactivar {e} {f['Id']}: {exc}")
    print(f"\nLimpieza terminada. Errores: {errores} (algunos registros del sistema no se pueden quitar).")


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


def cargar(qbo: QBO) -> None:
    c = CATALOGO["cuentas"]
    ingresos = _cuenta(qbo, c["ingresos_ventas"], "Income")
    costo = _cuenta(qbo, c["costo_mercancia"], "Cost of Goods Sold")
    _cuenta(qbo, c["impuesto_pagado_compras"], "Expense")
    _cuenta(qbo, c["comisiones"], "Expense")
    print("Cuentas listas.")

    for p in CATALOGO["productos"]:
        _asegurar(qbo, "Item", p["nombre"], {
            "Name": p["nombre"], "Type": "NonInventory", "UnitPrice": p["precio"],
            "Taxable": p["gravable"],
            "IncomeAccountRef": {"value": ingresos}, "ExpenseAccountRef": {"value": costo},
        })
    print(f"Productos listos: {len(CATALOGO['productos'])}")

    for p in CATALOGO["proveedores"]:
        _asegurar(qbo, "Vendor", p["nombre"], {"DisplayName": p["nombre"], "Notes": f"Proveedor {p['tipo']}"})
    for s in CATALOGO["socios"]:
        _asegurar(qbo, "Vendor", s["nombre"], {"DisplayName": s["nombre"], "Notes": f"Socio de locaciones, {s['pct_comision']}%"})
    print("Proveedores y socios listos.")

    _asegurar(qbo, "Customer", CATALOGO["cliente_ventas"], {
        "DisplayName": CATALOGO["cliente_ventas"],
        "Notes": "Cliente generico para las ventas consolidadas de las maquinas",
    })
    print("Cliente de ventas listo. El sandbox ya tiene los datos de EzSnack.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limpiar", action="store_true")
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--cargar", action="store_true")
    args = ap.parse_args()
    if not (args.limpiar or args.cargar):
        ap.print_help()
        return
    qbo = QBO()
    if args.limpiar:
        limpiar(qbo, args.confirmar)
    if args.cargar:
        cargar(qbo)


if __name__ == "__main__":
    main()
