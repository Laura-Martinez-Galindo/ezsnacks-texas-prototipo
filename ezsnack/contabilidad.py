"""Envio de las ventas del mes a QuickBooks Online.

QuickBooks trae prendido su impuesto automatico, que cobra por la direccion exacta de cada venta
y termina aplicando tambien las tasas de Stafford, Sugar Land y de los distritos de emergencia
del condado. EzSnack no declara asi: declara el 6.25 % del estado, el 1 % de la ciudad de Houston
y el 1 % del MTA para Bellaire, Katy y Spring.

Para que QuickBooks calcule igual que la declaracion, la aplicacion crea en la empresa tres tasas
propias (custom rates) a nombre del Texas Comptroller y le dice a cada recibo cual usar, en vez de
dejar que el impuesto automatico decida por la direccion:

    EzSnack Houston       6.25 % estado + 1 % ciudad
    EzSnack Houston MTA   6.25 % estado + 1 % MTA
    EzSnack solo estado   6.25 % estado

Por cada maquina se crea un recibo de venta con tres renglones: ventas gravables, agua (exenta) y
productos comprados con impuesto ya pagado (exentos, porque ese impuesto ya se pago en la caja).
Si el mes ya se habia enviado, los recibos se actualizan en vez de duplicarse.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

import pandas as pd

from .cierre import reglas
from .qbo import QBO, QBOError

CLIENTE = "Consumidores en maquinas"
CUENTA_INGRESOS = "Ventas en maquinas"
AGENCIA = "Texas State Comptroller"
SOLO_ESTADO = "Solo estado"
ITEMS = {
    "gravable": ("Ventas gravables", True),
    "exentas": ("Agua (exenta)", False),
    "pagadas": ("Comprado con impuesto ya pagado", False),
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


def _agencia(qbo: QBO) -> str:
    agencias = qbo.query("select * from TaxAgency")
    for a in agencias:
        if "comptroller" in str(a.get("DisplayName", "")).lower():
            return a["Id"]
    if agencias:
        return agencias[0]["Id"]
    return qbo.crear("TaxAgency", {"DisplayName": AGENCIA})["Id"]


def tasas(qbo: QBO) -> dict[str, str]:
    """Crea (o encuentra) las tres tasas de EzSnack. Devuelve jurisdiccion -> id del tax code."""
    R = reglas()
    agencia = _agencia(qbo)
    estado = {"TaxRateName": f"TX estado {R['tasa_estado']:g}%", "RateValue": R["tasa_estado"],
              "TaxAgencyId": agencia, "TaxApplicableOn": "Sales"}
    deseadas = {SOLO_ESTADO: [estado]}
    for nombre, j in R["jurisdicciones"].items():
        deseadas[nombre] = [estado, {"TaxRateName": f"{j['nombre_comptroller']} {j['tasa']:g}%",
                                     "RateValue": j["tasa"], "TaxAgencyId": agencia, "TaxApplicableOn": "Sales"}]

    existentes = {t.get("Name"): t for t in qbo.query("select * from TaxCode")}
    codigos = {}
    for nombre, detalles in deseadas.items():
        etiqueta = f"EzSnack {nombre}"
        if etiqueta in existentes:
            codigos[nombre] = existentes[etiqueta]["Id"]
            continue
        creado = qbo._peticion("POST", "taxservice/taxcode",
                               json_body={"TaxCode": etiqueta, "TaxRateDetails": detalles})
        codigos[nombre] = str(creado.get("TaxCodeId") or creado.get("Id"))
    return codigos


def _preparar(qbo: QBO) -> tuple[str, dict[str, str], dict[str, str]]:
    cuenta = _asegurar(qbo, "Account", "Name", CUENTA_INGRESOS, {"Name": CUENTA_INGRESOS, "AccountType": "Income"})["Id"]
    cliente = _asegurar(qbo, "Customer", "DisplayName", CLIENTE, {"DisplayName": CLIENTE})["Id"]
    items = {}
    for clave, (nombre, gravable) in ITEMS.items():
        items[clave] = _asegurar(qbo, "Item", "Name", nombre, {
            "Name": nombre, "Type": "Service", "Taxable": gravable, "IncomeAccountRef": {"value": cuenta}})["Id"]
    return cliente, items, tasas(qbo)


def _recibo(m, cliente: str, items: dict, codigos: dict, anio: int, mes: int, fecha: str) -> dict | None:
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
    codigo = codigos.get(m["jurisdiccion"] or SOLO_ESTADO, codigos[SOLO_ESTADO])
    r = {
        "DocNumber": f"V{anio % 100:02d}{mes:02d}-{m['id_maquina'] or 'X'}"[:21],
        "TxnDate": fecha, "CustomerRef": {"value": cliente},
        "PrivateNote": f"Ventas {mes:02d}/{anio} de {m['maquina']}."[:4000],
        "TxnTaxDetail": {"TxnTaxCodeRef": {"value": codigo}},
        "Line": lineas,
    }
    if m["direccion"] and m["ciudad"]:
        r["ShipFromAddr"] = {"Line1": str(m["direccion"]), "City": str(m["ciudad"]),
                             "CountrySubDivisionCode": str(m["estado"] or "TX"), "PostalCode": str(m["zip"]),
                             "Country": "USA"}
    return r


def enviar(qbo: QBO, maquinas: pd.DataFrame, anio: int, mes: int) -> dict:
    cliente, items, codigos = _preparar(qbo)
    fecha = date(anio, mes, monthrange(anio, mes)[1]).isoformat()
    prefijo = f"V{anio % 100:02d}{mes:02d}-"
    existentes = {r["DocNumber"]: r for r in qbo.query(f"select * from SalesReceipt where TxnDate = '{fecha}'")
                  if str(r.get("DocNumber", "")).startswith(prefijo)}

    pedidos = []
    for _, m in maquinas.iterrows():
        r = _recibo(m, cliente, items, codigos, anio, mes, fecha)
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
                errores.append({"recibo": item.get("bId"), "error": f"{err.get('Message', '')} {err.get('Detail', '')}".strip()[:300]})

    nombres = {t["Id"]: t.get("Name", "") for t in qbo.query("select * from TaxRate")}
    por_tasa: dict[str, dict] = {}
    filas, gravable, exento = [], 0.0, 0.0
    for operacion, r in recibos:
        detalle = r.get("TxnTaxDetail", {})
        for linea in detalle.get("TaxLine", []):
            det = linea.get("TaxLineDetail", {})
            nombre = nombres.get(det.get("TaxRateRef", {}).get("value"), "Sin nombre")
            acum = por_tasa.setdefault(nombre, {"jurisdiccion": nombre, "tasa": float(det.get("TaxPercent") or 0),
                                                "base": 0.0, "impuesto": 0.0})
            acum["base"] += float(det.get("NetAmountTaxable") or 0)
            acum["impuesto"] += float(linea.get("Amount") or 0)
        for linea in r.get("Line", []):
            det = linea.get("SalesItemLineDetail") or {}
            if det.get("TaxCodeRef", {}).get("value") == "TAX":
                gravable += float(linea.get("Amount") or 0)
            elif det:
                exento += float(linea.get("Amount") or 0)
        filas.append({"recibo": r.get("DocNumber"), "estado": "actualizado" if operacion == "update" else "creado",
                      "total": float(r.get("TotalAmt") or 0), "impuesto": float(detalle.get("TotalTax") or 0)})
    for v in por_tasa.values():
        v["base"], v["impuesto"] = round(v["base"], 2), round(v["impuesto"], 2)
    return {
        "recibos": filas, "errores": errores,
        "creados": sum(f["estado"] == "creado" for f in filas),
        "actualizados": sum(f["estado"] == "actualizado" for f in filas),
        "tasas": sorted(codigos),
        "por_jurisdiccion": sorted(por_tasa.values(), key=lambda v: -v["impuesto"]),
        "impuesto": round(sum(f["impuesto"] for f in filas), 2),
        "gravable": round(gravable, 2), "exento": round(exento, 2),
    }


__all__ = ["enviar", "tasas", "QBOError"]
