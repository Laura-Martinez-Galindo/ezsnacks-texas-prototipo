"""Lo que el programa hace en QuickBooks: enviar ventas, revisar recibos y registrar comisiones."""
from __future__ import annotations

import calendar
import json
from datetime import date
from pathlib import Path

import pandas as pd

from .emparejar import cargar_alias, emparejar, es_impuesto
from .qbo import QBO

CATALOGO = json.loads(Path("config/catalogo.json").read_text(encoding="utf-8"))


def ultimo_dia(anio: int, mes: int) -> date:
    return date(anio, mes, calendar.monthrange(anio, mes)[1])


def _q(texto: str) -> str:
    return texto.replace("'", "\\'")


# ---------------- datos maestros desde QuickBooks ----------------
def productos_qbo(qbo: QBO) -> dict[str, dict]:
    """Nombre -> {Id, Taxable} de los productos activos en QuickBooks."""
    items = qbo.query("select * from Item where Active = true")
    return {i["Name"]: {"Id": i["Id"], "Taxable": bool(i.get("Taxable", False))} for i in items}


def _buscar_uno(qbo: QBO, entidad: str, nombre: str, campo: str = "DisplayName") -> dict | None:
    filas = qbo.query(f"select * from {entidad} where {campo} = '{_q(nombre)}'")
    return filas[0] if filas else None


def _id_cuenta(qbo: QBO, nombre: str) -> str:
    cuenta = _buscar_uno(qbo, "Account", nombre, "Name")
    if not cuenta:
        raise RuntimeError(f"No existe la cuenta '{nombre}'. Corra scripts/preparar_sandbox.py --cargar")
    return cuenta["Id"]


# ---------------- 1. ventas del mes ----------------
def armar_recibos(resumen: pd.DataFrame, items: dict[str, dict], anio: int, mes: int, id_cliente: str) -> list[dict]:
    """Un recibo de venta por maquina, con la direccion de la maquina como lugar de la venta."""
    recibos = []
    fecha = ultimo_dia(anio, mes).isoformat()
    for id_maquina, g in resumen.groupby("id_maquina"):
        primera = g.iloc[0]
        lineas = []
        for _, fila in g.iterrows():
            item = items.get(fila["producto"])
            if not item or fila["valor"] <= 0:
                continue
            qty = float(fila["cantidad"]) or 1.0
            lineas.append({
                "DetailType": "SalesItemLineDetail",
                "Amount": round(float(fila["valor"]), 2),
                "Description": f"Ventas {mes:02d}/{anio} - {fila['producto']}",
                "SalesItemLineDetail": {
                    "ItemRef": {"value": item["Id"]},
                    "Qty": qty,
                    "UnitPrice": round(float(fila["valor"]) / qty, 4),
                    "TaxCodeRef": {"value": "TAX" if item["Taxable"] else "NON"},
                },
            })
        if not lineas:
            continue
        recibos.append({
            "DocNumber": f"V{anio % 100:02d}{mes:02d}-{id_maquina}"[:21],
            "TxnDate": fecha,
            "CustomerRef": {"value": id_cliente},
            "PrivateNote": f"Ventas consolidadas maquina {id_maquina} - {primera['locacion']} ({mes:02d}/{anio}). Generado por EzSnack Impuestos.",
            # Direccion donde ocurrio la venta: QuickBooks la usa para el impuesto automatico
            "ShipFromAddr": {
                "Line1": str(primera["direccion"]),
                "City": str(primera["ciudad"]),
                "CountrySubDivisionCode": str(primera["estado"]),
                "PostalCode": str(primera["zip"]),
                "Country": "USA",
            },
            "Line": lineas,
        })
    return recibos


def enviar_recibos(qbo: QBO, recibos: list[dict]) -> pd.DataFrame:
    """Crea los recibos en QuickBooks. Si ya existe uno con el mismo numero, no lo duplica."""
    resultado = []
    for r in recibos:
        existente = qbo.query(f"select Id, TotalAmt, TxnTaxDetail from SalesReceipt where DocNumber = '{r['DocNumber']}'")
        if existente:
            e = existente[0]
            resultado.append({"recibo": r["DocNumber"], "estado": "ya existia", "total": e.get("TotalAmt"),
                              "impuesto": e.get("TxnTaxDetail", {}).get("TotalTax")})
            continue
        try:
            creado = qbo.crear("SalesReceipt", r)
            resultado.append({"recibo": r["DocNumber"], "estado": "creado", "total": creado.get("TotalAmt"),
                              "impuesto": creado.get("TxnTaxDetail", {}).get("TotalTax")})
        except Exception as exc:  # noqa: BLE001
            resultado.append({"recibo": r["DocNumber"], "estado": f"error: {exc}", "total": None, "impuesto": None})
    return pd.DataFrame(resultado)


def id_cliente_ventas(qbo: QBO) -> str:
    cliente = _buscar_uno(qbo, "Customer", CATALOGO["cliente_ventas"])
    if not cliente:
        raise RuntimeError("Falta el cliente de ventas. Corra scripts/preparar_sandbox.py --cargar")
    return cliente["Id"]


# ---------------- 2. recibos de compras con impuesto pagado ----------------
def revisar_recibos(qbo: QBO, desde: date, hasta: date, productos: list[str]) -> pd.DataFrame:
    """Lee los gastos ya guardados de proveedores minoristas y clasifica cada renglon."""
    minoristas = {p["nombre"] for p in CATALOGO["proveedores"] if p["tipo"] == "minorista"}
    gastos = qbo.query(
        f"select * from Purchase where TxnDate >= '{desde.isoformat()}' and TxnDate <= '{hasta.isoformat()}'"
    )
    alias = cargar_alias()
    filas = []
    for g in gastos:
        proveedor = (g.get("EntityRef") or {}).get("name", "")
        if proveedor not in minoristas:
            continue
        for linea in g.get("Line", []):
            if linea.get("DetailType") == "SubTotalLineDetail":
                continue
            item = (linea.get("ItemBasedExpenseLineDetail") or {}).get("ItemRef", {}).get("name")
            texto = linea.get("Description") or item or ""
            monto = float(linea.get("Amount") or 0)
            if es_impuesto(texto):
                producto, puntaje, estado = None, 100, "impuesto"
            elif item and item in productos:
                producto, puntaje, estado = item, 100, "producto registrado"
            else:
                producto, puntaje, estado = emparejar(texto, productos, alias)
            filas.append({
                "gasto_id": g["Id"], "fecha": g.get("TxnDate"), "proveedor": proveedor,
                "texto_recibo": texto, "monto": monto, "producto": producto,
                "puntaje": puntaje, "estado": estado,
            })
    return pd.DataFrame(filas, columns=["gasto_id", "fecha", "proveedor", "texto_recibo", "monto", "producto", "puntaje", "estado"])


# ---------------- 3. comisiones ----------------
def calcular_comisiones(detalle: pd.DataFrame) -> pd.DataFrame:
    d = detalle[detalle["socio"].fillna("") != ""]
    if d.empty:
        return pd.DataFrame(columns=["socio", "maquinas", "ventas", "pct_comision", "comision"])
    g = d.groupby(["socio", "pct_comision"]).agg(
        maquinas=("id_maquina", lambda s: ", ".join(sorted(set(map(str, s))))),
        ventas=("valor", "sum"),
    ).reset_index()
    g["comision"] = (g["ventas"] * g["pct_comision"] / 100).round(2)
    g["ventas"] = g["ventas"].round(2)
    return g[["socio", "maquinas", "ventas", "pct_comision", "comision"]]


def registrar_comisiones(qbo: QBO, comisiones: pd.DataFrame, anio: int, mes: int) -> pd.DataFrame:
    """Crea una factura de proveedor (Bill) por socio, cargada a la cuenta de comisiones."""
    cuenta = _id_cuenta(qbo, CATALOGO["cuentas"]["comisiones"])
    fecha = ultimo_dia(anio, mes).isoformat()
    resultado = []
    for _, c in comisiones.iterrows():
        proveedor = _buscar_uno(qbo, "Vendor", c["socio"])
        if not proveedor:
            proveedor = qbo.crear("Vendor", {"DisplayName": c["socio"]})
        numero = f"COM{anio % 100:02d}{mes:02d}-{proveedor['Id']}"
        if qbo.query(f"select Id from Bill where DocNumber = '{numero}'"):
            resultado.append({"socio": c["socio"], "estado": "ya existia", "valor": c["comision"]})
            continue
        qbo.crear("Bill", {
            "VendorRef": {"value": proveedor["Id"]},
            "DocNumber": numero,
            "TxnDate": fecha,
            "PrivateNote": f"Comision {c['pct_comision']}% sobre ventas de maquinas {c['maquinas']} ({mes:02d}/{anio}).",
            "Line": [{
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": float(c["comision"]),
                "Description": f"Comision {mes:02d}/{anio} - maquinas {c['maquinas']}",
                "AccountBasedExpenseLineDetail": {"AccountRef": {"value": cuenta}},
            }],
        })
        resultado.append({"socio": c["socio"], "estado": "registrada", "valor": c["comision"]})
    return pd.DataFrame(resultado)
