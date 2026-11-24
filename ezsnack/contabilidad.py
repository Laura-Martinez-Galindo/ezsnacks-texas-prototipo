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

Nada de lo que la empresa ya tenia en QuickBooks se modifica: la aplicacion solo crea lo suyo (con
la marca "EzSnack Impuestos") y solo actualiza lo que ella misma creo. El cliente QBO tiene un
candado que bloquea cualquier otra escritura (ver qbo.py).

Las reglas del cierre quedan dentro de QuickBooks, no solo en la aplicacion:

    jurisdicciones   cada una es un tax code con la tasa del estado y la local
    agua             cada producto vendido es un item de QuickBooks; el agua queda con Taxable = false
    compras pagadas  el renglon de ese producto va con el codigo NON ese mes
    devoluciones     un renglon negativo "Devoluciones a clientes" (el 3 % o los cupones del mes)
    cupones          los que compran las empresas, un renglon gravable "Cupones vendidos a empresas"

Por cada maquina se crea un recibo de venta con un renglon por producto. QuickBooks decide con sus
items y sus tax codes que es gravable y cuanto impuesto cobra. Si el mes ya se habia enviado, los
recibos se actualizan en vez de duplicarse.
"""
from __future__ import annotations

import re
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
    "devoluciones": ("Devoluciones a clientes", True),
    "cupones_empresa": ("Cupones vendidos a empresas", True),
}
LOTE = 25
LOTE_ITEMS = 30
MARCA = "EzSnack Impuestos"
DESC_ITEM = f"Producto de máquina expendedora · {MARCA}"
NOTA = f"[{MARCA}]"


def es_propio_item(it: dict) -> bool:
    return str(it.get("Description") or "").startswith("Producto de máquina expendedora")


def es_propio_recibo(r: dict) -> bool:
    nota = str(r.get("PrivateNote") or "")
    return nota.startswith(NOTA) or bool(re.match(r"Ventas \d\d/\d{4} de ", nota))   # los de antes de la marca


def _esc(t: str) -> str:
    return str(t).replace("\\", "\\\\").replace("'", "\\'")


def _asegurar(qbo: QBO, entidad: str, campo: str, nombre: str, cuerpo: dict) -> dict:
    """Usa el registro activo con ese nombre tal como esta, o crea uno. Nunca modifica ni reactiva nada."""
    filas = qbo.query(f"select * from {entidad} where {campo} = '{_esc(nombre)}'")
    if filas:
        return filas[0]
    nuevo = qbo.crear(entidad, cuerpo)
    qbo.marcar_propio(entidad, nuevo.get("Id"))
    return nuevo


def _agencia(qbo: QBO) -> str:
    agencias = qbo.query("select * from TaxAgency")
    for a in agencias:
        if "comptroller" in str(a.get("DisplayName", "")).lower():
            return a["Id"]
    if agencias:
        return agencias[0]["Id"]
    return qbo.crear("TaxAgency", {"DisplayName": AGENCIA})["Id"]


def _deseadas(R: dict) -> dict[str, list[tuple[str, float]]]:
    """jurisdiccion -> [(nombre de la tasa, porcentaje)], segun las reglas de la aplicacion."""
    estado_nombre = f"TX estado {R['tasa_estado']:g}%"
    deseadas = {SOLO_ESTADO: [(estado_nombre, float(R["tasa_estado"]))]}
    for nombre, j in R["jurisdicciones"].items():
        deseadas[nombre] = [(estado_nombre, float(R["tasa_estado"])),
                            (f"{j['nombre_comptroller']} {j['tasa']:g}%", float(j["tasa"]))]
    return deseadas


def tasas(qbo: QBO, detalle: bool = False, R: dict | None = None):
    """Crea (o encuentra) las tres tasas de EzSnack. Devuelve jurisdiccion -> id del tax code.

    QuickBooks no deja repetir el nombre de una tasa, y las tres comparten la del estado. Por eso
    la del estado se crea una sola vez y las demas la referencian por su id.

    Si en las reglas cambia un porcentaje, el codigo que ya existe en QuickBooks queda con la tasa
    vieja (QuickBooks no deja editarla por la API). En ese caso se crea un codigo nuevo, con el
    porcentaje en el nombre, y los recibos pasan a usar ese.
    """
    R = R or reglas()
    agencia = _agencia(qbo)
    rates = qbo.query("select * from TaxRate")
    existentes_rate = {t.get("Name"): t["Id"] for t in rates}
    valor_rate = {t["Id"]: float(t.get("RateValue") or 0) for t in rates}

    def partes_de(code: dict) -> list[float]:
        refs = (code.get("SalesTaxRateList") or {}).get("TaxRateDetail") or []
        return sorted(valor_rate.get(r.get("TaxRateRef", {}).get("value"), -1.0) for r in refs)

    def pedido(nombre: str, valor: float) -> dict:
        if nombre in existentes_rate:
            return {"TaxRateId": existentes_rate[nombre]}
        return {"TaxRateName": nombre, "RateValue": valor, "TaxAgencyId": agencia, "TaxApplicableOn": "Sales"}

    codes = {t.get("Name"): t for t in qbo.query("select * from TaxCode")}
    codigos, resumen = {}, []
    for nombre, partes in _deseadas(R).items():
        total = sum(v for _, v in partes)
        quiere = sorted(v for _, v in partes)
        etiqueta, accion = f"EzSnack {nombre}", "ya estaba"
        actual = codes.get(etiqueta)
        if actual is not None and partes_de(actual) != quiere:
            etiqueta, actual = f"EzSnack {nombre} {total:g}%", codes.get(f"EzSnack {nombre} {total:g}%")
        if actual is None:
            creado = qbo._peticion("POST", "taxservice/taxcode", json_body={
                "TaxCode": etiqueta, "TaxRateDetails": [pedido(n, v) for n, v in partes]})
            codigos[nombre], accion = str(creado.get("TaxCodeId") or creado.get("Id")), "creada"
            # las tasas que acaba de crear ya existen para el siguiente codigo
            rates = qbo.query("select * from TaxRate")
            existentes_rate = {t.get("Name"): t["Id"] for t in rates}
            valor_rate = {t["Id"]: float(t.get("RateValue") or 0) for t in rates}
        else:
            codigos[nombre] = actual["Id"]
        resumen.append({"jurisdiccion": nombre, "codigo": etiqueta, "id": codigos[nombre], "total": total,
                        "partes": [{"nombre": n, "tasa": v} for n, v in partes], "estado": accion})
    return (codigos, resumen) if detalle else codigos


def _nombres(R: dict | None) -> tuple[str, str]:
    conta = (R or {}).get("contabilidad") or {}
    return conta.get("cuenta") or CUENTA_INGRESOS, conta.get("cliente") or CLIENTE


def _item_propio(qbo: QBO, nombre: str, gravable: bool, cuenta: str) -> dict:
    """Un item de la aplicacion (devoluciones, cupones...). Si la empresa ya tenia uno con ese nombre
    y otra marca de gravable, no se toca: se crea otro con "(EzSnack)" al final."""
    for candidato in (nombre, f"{nombre} (EzSnack)"):
        filas = qbo.query(f"select * from Item where Name = '{_esc(candidato)}'")
        if filas and bool(filas[0].get("Taxable")) == gravable:
            return filas[0]
        if not filas:
            nuevo = qbo.crear("Item", {"Name": candidato, "Type": "Service", "Taxable": gravable,
                                       "Description": MARCA, "IncomeAccountRef": {"value": cuenta}})
            qbo.marcar_propio("Item", nuevo.get("Id"))
            return nuevo
    raise QBOError(f"Ya existen los productos {nombre} y {nombre} (EzSnack) con otra marca de impuesto.")


def _preparar(qbo: QBO, R: dict | None = None) -> tuple[str, dict[str, str], dict[str, str]]:
    n_cuenta, n_cliente = _nombres(R)
    cuenta = _asegurar(qbo, "Account", "Name", n_cuenta, {"Name": n_cuenta, "AccountType": "Income"})["Id"]
    cliente = _asegurar(qbo, "Customer", "DisplayName", n_cliente, {"DisplayName": n_cliente})["Id"]
    items = {}
    for clave, (nombre, gravable) in ITEMS.items():
        items[clave] = _item_propio(qbo, nombre, gravable, cuenta)["Id"]
    return cliente, items, tasas(qbo, R=R)


def gravables_del_catalogo(catalogo: dict, R: dict) -> dict[str, bool]:
    """producto -> paga impuesto, con la clasificacion guardada o, si esta en automatico, la regla del agua."""
    from .productos import es_exento
    return {p: not (c["exento"] if c.get("exento") is not None else es_exento(p, R)) for p, c in catalogo.items()}


def preparar(qbo: QBO, R: dict | None = None, catalogo: dict | None = None,
             alias: dict[str, list[str]] | None = None) -> dict:
    """Migra las reglas de impuestos de EzSnack a la empresa de QuickBooks. Se llama al conectar.

    Crea lo que falte y corrige lo que no coincida, sin tocar transacciones: la agencia (Texas
    Comptroller), un tax code por jurisdiccion, los items de devoluciones y cupones, el cliente, la
    cuenta de ingresos y un item por cada producto del catalogo con su marca de gravable (el agua no).
    """
    n_cuenta, n_cliente = _nombres(R)
    cuenta = _asegurar(qbo, "Account", "Name", n_cuenta, {"Name": n_cuenta, "AccountType": "Income"})
    cliente = _asegurar(qbo, "Customer", "DisplayName", n_cliente, {"DisplayName": n_cliente})
    productos = []
    for _, (nombre, gravable) in ITEMS.items():
        it = _item_propio(qbo, nombre, gravable, cuenta["Id"])
        productos.append({"nombre": it.get("Name"), "gravable": gravable, "id": it["Id"]})
    codigos, resumen = tasas(qbo, detalle=True, R=R)
    catalogo_qbo = {"en_quickbooks": 0, "creados": 0, "cambiados": 0, "agua": 0, "errores": []}
    if catalogo:
        gravables = gravables_del_catalogo(catalogo, R or reglas())
        ids, sinc = sincronizar_productos(qbo, gravables, cuenta["Id"], alias)
        catalogo_qbo = {**sinc, "en_quickbooks": len(set(ids.values())), "agua": sum(1 for v in gravables.values() if not v)}
    return {"tasas": codigos, "detalle": resumen, "productos": productos, "catalogo": catalogo_qbo,
            "cliente": cliente.get("DisplayName"), "cuenta": cuenta.get("Name")}


def _fondos_no_depositados(qbo: QBO) -> str | None:
    """La cuenta Undeposited Funds de la empresa (solo se lee). Los recibos quedan ahi hasta que
    llega el deposito del lector al banco, que se empareja con ellos en vez de contarse como ingreso."""
    for c in qbo.query("select * from Account where AccountType = 'Other Current Asset'"):
        if c.get("AccountSubType") == "UndepositedFunds" and c.get("Active", True):
            return c["Id"]
    return None


def _filas_pyg(filas: list, en_ingresos: bool = False, salida: list | None = None) -> list:
    """Recorre el reporte de perdidas y ganancias y devuelve (cuenta, valor) de la seccion Income."""
    salida = [] if salida is None else salida
    for f in filas or []:
        grupo = f.get("group")
        dentro = en_ingresos or grupo == "Income"
        if f.get("type") == "Section":
            _filas_pyg((f.get("Rows") or {}).get("Row"), dentro, salida)
        elif dentro and f.get("ColData"):
            col = f["ColData"]
            try:
                salida.append((str(col[0].get("value", "")), float(col[-1].get("value") or 0)))
            except (TypeError, ValueError):
                pass
        if grupo == "Income" and f.get("type") == "Section":
            break
    return salida


def otros_ingresos(qbo: QBO, anio: int, mes: int, R: dict | None = None) -> dict:
    """Cuanto ingreso tiene ya el mes en QuickBooks en cuentas distintas a la de la aplicacion.

    Solo lee el reporte de perdidas y ganancias. Si las ventas de las maquinas ya entran por otro
    lado (por ejemplo, registrando como ingreso los depositos de Nayax), enviar los recibos las
    duplicaria; con esto la pagina avisa antes de enviar.
    """
    n_cuenta, _ = _nombres(R)
    desde, hasta = date(anio, mes, 1).isoformat(), date(anio, mes, monthrange(anio, mes)[1]).isoformat()
    rep = qbo._peticion("GET", "reports/ProfitAndLoss", params={"start_date": desde, "end_date": hasta,
                                                                "accounting_method": "Accrual"})
    cuentas = [{"cuenta": n, "valor": round(v, 2)} for n, v in _filas_pyg((rep.get("Rows") or {}).get("Row"))
               if abs(v) >= 0.01 and n.strip().lower() != n_cuenta.lower()]
    return {"desde": desde, "hasta": hasta, "cuentas": cuentas, "total": round(sum(c["valor"] for c in cuentas), 2)}


def nombre_item(producto: str) -> str:
    """QuickBooks usa ':' para subproductos y no deja nombres de mas de 100 caracteres."""
    return " ".join(str(producto).replace(":", " -").split())[:100] or "Sin nombre"


TIPOS_PRODUCTO = ("NonInventory", "Inventory", "Service")


def sincronizar_productos(qbo: QBO, gravables: dict[str, bool], cuenta: str,
                          alias: dict[str, list[str]] | None = None) -> tuple[dict[str, str], dict]:
    """Deja en QuickBooks un item por producto, con la marca de gravable que dicen las reglas.

    gravables: producto -> True si paga impuesto (False para el agua).
    alias: producto -> otros nombres con que lo traen los sistemas de ventas.

    Si la empresa ya tenia el producto en QuickBooks, se usa ese item (sea de inventario, de
    servicio o no inventariable) tal como esta: no se le cambia nada, ni la marca de gravable. En
    los recibos de la aplicacion cada renglon dice si paga impuesto, asi que el agua sale sin
    impuesto aunque el item de la empresa diga otra cosa. Solo se corrige la marca de los items
    que creo la aplicacion. Se
    busca por el nombre, por los otros nombres del producto y, si nada coincide, por un nombre
    parecido que sea el mismo producto (por ejemplo "Ozarka Water 20 oz" y "Ozarka water 20oz").
    """
    from .productos import mismo_producto
    alias = alias or {}
    todos = [it for it in qbo.query("select * from Item") if it.get("Type") in TIPOS_PRODUCTO]
    propios = {nombre for nombre, _ in ITEMS.values()}
    existentes = {str(it.get("Name", "")).lower(): it for it in todos if it.get("Name") not in propios}
    grupos: dict[str, list[str]] = {}
    for producto in gravables:   # QuickBooks no distingue mayusculas: "Ozarka water" y "Ozarka Water" son un item
        grupos.setdefault(nombre_item(producto).lower(), []).append(producto)
    usados = set()
    for it in todos:
        if es_propio_item(it):
            qbo.marcar_propio("Item", it["Id"])
    ids, pedidos, de_pedido, reutilizados, sin_tocar = {}, [], {}, [], []
    nuevos = cambiados = existian = 0
    for clave, productos in grupos.items():
        gravable = all(gravables[p] for p in productos)   # si uno de los nombres es agua, el item es agua
        nombres = [clave] + [nombre_item(a).lower() for p in productos for a in alias.get(p, [])]
        it = next((existentes[n] for n in nombres if n in existentes and existentes[n]["Id"] not in usados), None)
        if it is None:
            parecidos = [x for n, x in existentes.items() if x["Id"] not in usados and mismo_producto(productos[0], x["Name"])]
            if len(parecidos) == 1:
                it = parecidos[0]
        if it is None:
            bid = f"n{len(pedidos)}"
            pedidos.append({"bId": bid, "operation": "create", "Item": {
                "Name": nombre_item(productos[0]), "Type": "NonInventory", "Taxable": gravable,
                "Description": DESC_ITEM, "IncomeAccountRef": {"value": cuenta}}})
            de_pedido[bid] = productos
            nuevos += 1
            continue
        usados.add(it["Id"])
        existian += 1
        ids.update({p: it["Id"] for p in productos})
        if str(it.get("Name", "")).lower() != clave:
            reutilizados.append({"producto": productos[0], "item": it.get("Name")})
        if bool(it.get("Taxable")) != gravable and not es_propio_item(it):
            sin_tocar.append({"producto": productos[0], "item": it.get("Name"), "en_quickbooks": "gravable" if it.get("Taxable") else "no gravable",
                              "regla": "gravable" if gravable else "no gravable"})
        elif bool(it.get("Taxable")) != gravable:
            pedidos.append({"bId": f"c{len(pedidos)}", "operation": "update", "Item": {
                "Id": it["Id"], "SyncToken": it["SyncToken"], "Taxable": gravable, "sparse": True}})
            cambiados += 1
    errores = []
    for i in range(0, len(pedidos), LOTE_ITEMS):
        resp = qbo._peticion("POST", "batch", json_body={"BatchItemRequest": pedidos[i:i + LOTE_ITEMS]})
        for r in resp.get("BatchItemResponse", []):
            if "Item" in r:
                qbo.marcar_propio("Item", r["Item"]["Id"])
                for p in de_pedido.get(r["bId"], []):
                    ids[p] = r["Item"]["Id"]
            else:
                err = (r.get("Fault", {}).get("Error") or [{}])[0]
                errores.append(f"{err.get('Message', '')} {err.get('Detail', '')}".strip()[:200])
    return ids, {"creados": nuevos, "cambiados": cambiados, "errores": errores, "ya_existian": existian,
                 "sin_tocar": sin_tocar,
                 "reutilizados": reutilizados}


def _recibo_productos(m, filas: pd.DataFrame, cliente: str, items: dict, prods: dict, codigos: dict,
                      anio: int, mes: int, fecha: str) -> dict | None:
    """Un renglon por producto. Devuelve None si no cuadra con la maquina, para usar el resumido."""
    if float(m["gravable"]) <= 0 or filas.empty:
        return None
    lineas = []

    def linea(item: str, valor: float, gravable: bool, texto: str) -> None:
        valor = round(valor, 2)
        if abs(valor) < 0.005:
            return
        lineas.append({"DetailType": "SalesItemLineDetail", "Amount": valor, "Description": texto[:4000],
                       "SalesItemLineDetail": {"ItemRef": {"value": item}, "Qty": 1, "UnitPrice": valor,
                                               "TaxCodeRef": {"value": "TAX" if gravable else "NON"}}})

    for f in filas.itertuples(index=False):
        if f.producto not in prods:
            return None
        texto = f"{int(f.cantidad)} unidades" if f.cantidad else ""
        if f.pagado and not f.exento:
            texto = (texto + ". Comprado con impuesto ya pagado").strip(". ")
        linea(prods[f.producto], float(f.venta), not (f.exento or f.pagado), texto)
    linea(items["cupones_empresa"], float(m["cup_emp"]), True, f"Cupones vendidos a empresas {mes:02d}/{anio}")
    devol = round(float(m["dev_e"]) + float(m["dev_t"]), 2)
    gravado = round(sum(l["Amount"] for l in lineas if l["SalesItemLineDetail"]["TaxCodeRef"]["value"] == "TAX") - devol, 2)
    ajuste = round(float(m["gravable"]) - gravado, 2)   # centavos de redondeo entre producto y maquina
    if abs(ajuste) > 0.05:
        return None
    linea(items["devoluciones"], -(devol - ajuste), True, f"Devoluciones a clientes {mes:02d}/{anio}")
    if not lineas:
        return None
    return lineas


def _por_jurisdiccion(maquinas: pd.DataFrame) -> pd.DataFrame:
    """Junta todas las maquinas de una misma tasa en una sola fila: un recibo por jurisdiccion."""
    m = maquinas.copy()
    m["jurisdiccion"] = m["jurisdiccion"].fillna("")
    filas = []
    for juris, g in m.groupby("jurisdiccion", sort=False):
        nombre = juris or SOLO_ESTADO
        filas.append({
            "id_maquina": re.sub(r"[^A-Za-z0-9]+", "", nombre)[:12] or "TX",
            "maquina": f"{len(g)} maquinas - {nombre}",
            "jurisdiccion": juris,
            **{c: float(pd.to_numeric(g[c], errors="coerce").fillna(0).sum())
               for c in g.columns if pd.api.types.is_numeric_dtype(g[c]) or c in ITEMS},
            "direccion": None, "ciudad": None, "estado": None, "zip": None,
        })
    return pd.DataFrame(filas)


def _recibo(m, cliente: str, items: dict, codigos: dict, anio: int, mes: int, fecha: str,
            lineas: list | None = None, fondos: str | None = None) -> dict | None:
    resumido = lineas is None
    lineas = [] if lineas is None else lineas
    for clave, (nombre, gravable) in (list(ITEMS.items())[:3] if resumido else []):
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
        "PrivateNote": f"{NOTA} Ventas {mes:02d}/{anio} de {m['maquina']}."[:4000],
        "TxnTaxDetail": {"TxnTaxCodeRef": {"value": codigo}},
        **({"DepositToAccountRef": {"value": fondos}} if fondos else {}),
        "Line": lineas,
    }
    if m["direccion"] and m["ciudad"]:
        r["ShipFromAddr"] = {"Line1": str(m["direccion"]), "City": str(m["ciudad"]),
                             "CountrySubDivisionCode": str(m["estado"] or "TX"), "PostalCode": str(m["zip"]),
                             "Country": "USA"}
    return r


def enviar(qbo: QBO, maquinas: pd.DataFrame, anio: int, mes: int, esperado: list[dict] | None = None,
           R: dict | None = None, detalle: pd.DataFrame | None = None, alias: dict[str, list[str]] | None = None) -> dict:
    cliente, items, codigos = _preparar(qbo, R)
    # Productos: cada uno es un item de QuickBooks y el agua queda marcada como no gravable alli
    prods, sinc, por_maquina = {}, {"creados": 0, "cambiados": 0, "errores": []}, {}
    if detalle is not None and len(detalle):
        n_cuenta, _ = _nombres(R)
        cuenta = _asegurar(qbo, "Account", "Name", n_cuenta, {"Name": n_cuenta, "AccountType": "Income"})["Id"]
        d = detalle.assign(venta=detalle["efectivo"] + detalle["tarjeta"],
                           id_maquina=detalle["id_maquina"].fillna(""))
        g = (d.groupby(["id_maquina", "producto"], sort=False)
             .agg(venta=("venta", "sum"), cantidad=("cantidad", "sum"), exento=("exento", "first"),
                  pagado=("impuesto_pagado", "first")).reset_index())
        prods, sinc = sincronizar_productos(qbo, {p: not bool(e) for p, e in
                                                   g.groupby("producto")["exento"].first().items()}, cuenta, alias)
        por_maquina = {k: v for k, v in g.groupby("id_maquina")}
    fecha = date(anio, mes, monthrange(anio, mes)[1]).isoformat()
    prefijo = f"V{anio % 100:02d}{mes:02d}-"
    existentes = {r["DocNumber"]: r for r in qbo.query(f"select * from SalesReceipt where TxnDate = '{fecha}'")
                  if str(r.get("DocNumber", "")).startswith(prefijo)}

    ajenos = {}
    for num, r in list(existentes.items()):
        if es_propio_recibo(r):
            qbo.marcar_propio("SalesReceipt", r["Id"])
        else:   # un recibo de la empresa con el mismo numero: no se toca
            ajenos[num] = existentes.pop(num)
    fondos = _fondos_no_depositados(qbo)
    # El gerente declara un total por jurisdiccion, no maquina por maquina. QuickBooks aplica una
    # sola tasa por recibo, asi que lo mas cerca que se puede estar de "un solo recibo" es uno por
    # tasa: estado solo, Houston y Houston MTA.
    if str(((R or {}).get("contabilidad") or {}).get("recibos") or "maquina") == "jurisdiccion":
        juris = {str(k): (v or "") for k, v in zip(maquinas["id_maquina"], maquinas["jurisdiccion"])}
        maquinas = _por_jurisdiccion(maquinas)
        nuevo_detalle = {}
        for clave, g in por_maquina.items():
            destino = re.sub(r"[^A-Za-z0-9]+", "", juris.get(str(clave), "") or SOLO_ESTADO)[:12] or "TX"
            nuevo_detalle.setdefault(destino, []).append(g)
        por_maquina = {k: pd.concat(v).groupby("producto", as_index=False, sort=False)
                       .agg(venta=("venta", "sum"), cantidad=("cantidad", "sum"),
                            exento=("exento", "first"), pagado=("pagado", "first")).assign(id_maquina=k)
                       for k, v in nuevo_detalle.items()}
    pedidos, resumidos, omitidos = [], 0, []
    for _, m in maquinas.iterrows():
        lineas = None
        if prods:
            lineas = _recibo_productos(m, por_maquina.get(m["id_maquina"] or "", pd.DataFrame()), cliente, items,
                                       prods, codigos, anio, mes, fecha)
        r = _recibo(m, cliente, items, codigos, anio, mes, fecha, lineas, fondos)
        if r is None:
            continue
        resumidos += lineas is None
        if r["DocNumber"] in ajenos:
            omitidos.append({"recibo": r["DocNumber"], "error": "Ya hay un recibo con ese número que no creó la aplicación; no se tocó."})
            continue
        previo = existentes.get(r["DocNumber"])
        if previo:
            r.update(Id=previo["Id"], SyncToken=previo["SyncToken"], sparse=False)
        pedidos.append({"bId": r["DocNumber"], "operation": "update" if previo else "create", "SalesReceipt": r})

    recibos, errores = [], list(omitidos)
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
    # Cuadre: lo que devolvio QuickBooks contra lo que calculo la aplicacion, tasa por tasa
    cuadre = []
    for e in esperado or []:
        q = por_tasa.get(e["jurisdiccion"], {"base": 0.0, "impuesto": 0.0})
        cuadre.append({"jurisdiccion": e["jurisdiccion"], "tasa": e["tasa"],
                       "base_app": e["base"], "base_qbo": q["base"],
                       "impuesto_app": e["impuesto"], "impuesto_qbo": q["impuesto"],
                       # La base tiene que dar igual al centavo. En el impuesto se admite un centavo:
                       # la aplicacion lo redondea maquina por maquina y QuickBooks una sola vez
                       # sobre el total de la tasa, que es como lo liquida el Comptroller.
                       "igual": abs(e["base"] - q["base"]) < 0.005 and abs(e["impuesto"] - q["impuesto"]) <= 0.01 + 1e-9})
    for nombre, q in por_tasa.items():
        if esperado is not None and nombre not in {e["jurisdiccion"] for e in esperado}:
            cuadre.append({"jurisdiccion": nombre, "tasa": q["tasa"], "base_app": 0.0, "base_qbo": q["base"],
                           "impuesto_app": 0.0, "impuesto_qbo": q["impuesto"], "igual": False})
    return {
        "productos": {**sinc, "en_quickbooks": len(set(prods.values())), "recibos_resumidos": resumidos},
        "cuadre": cuadre, "cuadra": bool(cuadre) and all(c["igual"] for c in cuadre) and not errores,
        "recibos": filas, "errores": errores,
        "creados": sum(f["estado"] == "creado" for f in filas),
        "actualizados": sum(f["estado"] == "actualizado" for f in filas),
        "tasas": sorted(codigos),
        "por_jurisdiccion": sorted(por_tasa.values(), key=lambda v: -v["impuesto"]),
        "impuesto": round(sum(f["impuesto"] for f in filas), 2),
        "gravable": round(gravable, 2), "exento": round(exento, 2),
    }


__all__ = ["enviar", "preparar", "tasas", "QBOError"]
