"""Pruebas de lo que queda guardado en el servidor: reglas, maquinas, productos, usuarios y cierres."""
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from ezsnack import almacen, cierre, lectores, libro, maquinas, productos
from web.main import app

D = Path(__file__).resolve().parents[1] / "datos_prueba"


def _integ():
    lecturas = [lectores.leer(p) for p in sorted(D.glob("reporte_*.xlsx"))]
    return lecturas, cierre.integrar(lecturas, maquinas.leer(D / "vendor_list_EJEMPLO.xlsx"))


def _otra_ciudad(integ) -> str:
    """Una ciudad con ventas que hoy solo paga el impuesto del estado."""
    usadas = {c.lower() for j in almacen.reglas()["jurisdicciones"].values() for c in j["ciudades"]}
    return next(c for c in integ["ciudad"].unique() if c and c.lower() not in usadas)


def test_reglas_nuevas_aplican_desde_su_mes_y_no_cambian_los_anteriores():
    lecturas, integ = _integ()
    ciudad = _otra_ciudad(integ)
    R = almacen.reglas()
    R["jurisdicciones"]["Nueva"] = {"codigo": "9999999", "nombre_comptroller": "NUEVA-CITY", "tasa": 1.5, "ciudades": [ciudad]}
    almacen.guardar_reglas(R, "Humberto", "2026-10", "Máquinas en otra ciudad")
    antes = cierre.calcular(integ, cierre.Ajustes(), 2026, 9)
    despues = cierre.calcular(integ, cierre.Ajustes(), 2026, 10)
    assert [l["jurisdiccion"] for l in antes["declaracion"]["locales"]] == ["Houston", "Houston MTA"]
    nueva = next(l for l in despues["declaracion"]["locales"] if l["jurisdiccion"] == "Nueva")
    assert nueva["maquinas"] > 0 and nueva["tasa"] == 1.5
    assert any(e["jurisdiccion"] == "NUEVA-CITY 1.5%" for e in despues["declaracion"]["quickbooks_esperado"])
    # el Excel trae los renglones de la jurisdiccion nueva
    ws = load_workbook(BytesIO(libro.libro(despues, lecturas, 2026, 10))).worksheets[0]
    etiquetas = [ws.cell(row=f, column=4).value for f in range(ws.max_row - 14, ws.max_row + 1)]
    assert "Nueva Taxable sales (NUEVA-CITY)" in etiquetas
    assert [v["desde"] for v in almacen.versiones_reglas()][:2] == ["2026-10", "2000-01"]


def test_reglas_invalidas_no_se_guardan():
    R = almacen.reglas()
    R["jurisdicciones"]["Otra"] = {"codigo": "1", "nombre_comptroller": "OTRA", "tasa": 1, "ciudades": ["Houston"]}
    with pytest.raises(ValueError, match="dos jurisdicciones"):
        almacen.guardar_reglas(R, "x", "2026-10")
    R = almacen.reglas()
    R["tasa_estado"] = 80
    with pytest.raises(ValueError):
        almacen.guardar_reglas(R, "x", "2026-10")


def test_la_clasificacion_guardada_manda_sobre_la_regla_del_agua():
    _, integ = _integ()
    agua = next(p for p in integ["producto"].unique() if productos.es_exento(p))
    otro = next(p for p in integ["producto"].unique() if not productos.es_exento(p))
    almacen.marcar_producto(agua, "Humberto", exento=False)
    almacen.marcar_producto(otro, "Humberto", exento=True, pagado_habitual=False)
    r = cierre.calcular(integ, cierre.Ajustes(catalogo=almacen.productos()), 2026, 9)
    assert agua not in r["lista_exentos"] and otro in r["lista_exentos"]
    almacen.marcar_producto(agua, "Humberto", exento=None)          # vuelve a lo automatico
    assert almacen.productos()[agua]["exento"] is None


def test_sin_lista_del_mes_se_proponen_las_compras_habituales():
    _, integ = _integ()
    habitual = next(p for p in integ["producto"].unique() if not productos.es_exento(p))
    almacen.marcar_producto(habitual, "Humberto", pagado_habitual=True)
    r = cierre.calcular(integ, cierre.Ajustes(catalogo=almacen.productos()), 2026, 9)
    assert r["lista_pagados"] == [habitual] and r["pasos"]["walmart"]["total"] > 0


def test_maquinas_guardadas_y_cierre_sin_subir_la_lista():
    c = TestClient(app)
    with open(D / "vendor_list_EJEMPLO.xlsx", "rb") as f:
        r = c.post("/api/config/maquinas", files={"lista": ("vendor.xlsx", f)}).json()
    assert r["nuevas"] == r["total"] > 0
    una = r["maquinas"][0]["id_maquina"]
    c.post(f"/api/config/maquinas/{una}", json={"ciudad": "katy"})
    assert next(m for m in almacen.maquinas() if m["id_maquina"] == una)["ciudad"] == "Katy"
    reportes = [("reportes", (p.name, p.read_bytes())) for p in sorted(D.glob("reporte_*.xlsx"))]
    d = c.post("/api/cierre/archivos?anio=2026&mes=9", files=reportes)     # sin vendor list
    assert d.status_code == 200 and d.json()["declaracion"]["ventas_gravables"] > 0
    g = c.post(f"/api/cierre/{d.json()['codigo']}/guardar", json={"anio": 2026, "mes": 9}).json()
    guardado = almacen.cierre(g["id"])
    assert guardado["estado"] == "guardado" and len(guardado["maquinas"]) == len(d.json()["maquinas"])
    assert sum(m["gravable"] for m in guardado["maquinas"]) == pytest.approx(d.json()["declaracion"]["gravable_exacto"], abs=0.01)
    # un cierre declarado no se reemplaza
    c.post(f"/api/cierres/{g['id']}/estado", json={"estado": "declarado"})
    assert c.post(f"/api/cierre/{d.json()['codigo']}/guardar", json={"anio": 2026, "mes": 9}).status_code == 400


def test_roles():
    c = TestClient(app)
    assert c.get("/api/estado").json()["usuario"]["abierto"]            # sin usuarios, la app esta abierta
    assert c.post("/api/config/usuarios", json={"nombre": "Ana", "usuario": "ana", "clave": "clave-de-prueba-1", "rol": "operador"}).status_code == 400
    assert c.post("/api/config/usuarios", json={"nombre": "Humberto", "usuario": "humberto", "clave": "clave-de-prueba-1", "rol": "admin"}).status_code == 200
    # desde que hay un usuario, todo pide sesion
    assert c.get("/api/estado").json()["requiere_login"]
    assert c.get("/api/config").status_code == 401
    assert c.post("/api/sesion/entrar", json={"usuario": "humberto", "clave": "otra-clave-mala"}).status_code == 401
    assert c.post("/api/sesion/entrar", json={"usuario": "Humberto", "clave": "clave-de-prueba-1"}).status_code == 200
    for nombre, rol in (("Operador", "operador"), ("Contador", "consulta")):
        assert c.post("/api/config/usuarios", json={"nombre": nombre, "usuario": rol, "clave": "clave-de-prueba-2", "rol": rol}).status_code == 200
    reglas = c.get("/api/config").json()["reglas"]

    op = TestClient(app)
    op.post("/api/sesion/entrar", json={"usuario": "operador", "clave": "clave-de-prueba-2"})
    assert op.post("/api/cierre/ejemplo").status_code == 200
    assert op.post("/api/config/reglas", json={"reglas": reglas, "desde": "2026-11"}).status_code == 403
    assert op.post("/api/config/productos", json={"nombre": "Coke", "exento": False}).status_code == 200

    ver = TestClient(app)
    ver.post("/api/sesion/entrar", json={"usuario": "consulta", "clave": "clave-de-prueba-2"})
    assert ver.get("/api/cierres").status_code == 200
    assert ver.post("/api/cierre/ejemplo").status_code == 403
    assert ver.get("/api/config").json()["usuarios"] == []

    assert c.post("/api/config/reglas", json={"reglas": reglas, "desde": "2026-11", "nota": "prueba"}).status_code == 200
    # no se puede dejar la empresa sin administrador
    yo = next(u for u in c.get("/api/config").json()["usuarios"] if u["usuario"] == "humberto")
    assert c.post(f"/api/config/usuarios/{yo['id']}", json={"rol": "operador"}).status_code == 400
    acciones = [b["accion"] for b in almacen.bitacora()]
    assert "Cambió las reglas" in acciones and "Creó un usuario" in acciones


def test_sistema_registrado_en_el_servidor(tmp_path):
    import pandas as pd
    c = TestClient(app)
    ruta = tmp_path / "otro.xlsx"
    pd.DataFrame({"Kiosko": ["EzSnack 5 - X"], "Articulo vendido": ["Coke"], "Neto cobrado": [3.0]}).to_excel(ruta, index=False)
    mapeo = {"maquina": "Kiosko", "producto": "Articulo vendido", "total": "Neto cobrado"}
    assert c.post("/api/config/formatos", json={"nombre": "Nayax", "mapeo": mapeo}).status_code == 400
    assert c.post("/api/config/formatos", json={"nombre": "Cantaloupe", "mapeo": mapeo}).status_code == 200
    with open(D / "vendor_list_EJEMPLO.xlsx", "rb") as f:
        d = c.post("/api/cierre/archivos?anio=2026&mes=9", files=[("maquinas", ("v.xlsx", f.read())), ("reportes", ("otro.xlsx", ruta.read_bytes()))]).json()
    assert d["archivos"][0]["fuente"] == "Cantaloupe" and d["archivos"][0]["registrado"]


def test_las_reglas_quedan_en_quickbooks_y_cuadra():
    """Cada producto es un item; el agua no es gravable en QuickBooks; las devoluciones son un renglon."""
    from tests.falso_qbo import Falso

    from ezsnack import contabilidad
    lecturas, integ = _integ()
    r = cierre.calcular(integ, cierre.Ajustes(lista_pagados=productos.leer_lista(D / "compras_impuesto_pagado_EJEMPLO.xlsx")), 2026, 9)
    q = Falso()
    e = contabilidad.enviar(q, r["maquinas"], 2026, 9, r["declaracion"]["quickbooks_esperado"], r["reglas"], r["detalle"])
    assert e["cuadra"] and not e["errores"] and e["productos"]["recibos_resumidos"] == 0
    agua = {it["Name"] for it in q.items.values() if it["Type"] == "NonInventory" and not it["Taxable"]}
    assert agua == {contabilidad.nombre_item(p) for p in r["lista_exentos"]}
    assert any(l["Amount"] < 0 for rc in q.recibos.values() for l in rc["Line"])   # devoluciones
    # si una regla cambia (un producto deja de ser agua) QuickBooks se actualiza al reenviar
    un_agua = r["lista_exentos"][0]
    r2 = cierre.calcular(integ, cierre.Ajustes(exentos=r["lista_exentos"][1:]), 2026, 9)
    e2 = contabilidad.enviar(q, r2["maquinas"], 2026, 9, r2["declaracion"]["quickbooks_esperado"], r2["reglas"], r2["detalle"])
    assert e2["cuadra"] and e2["productos"]["cambiados"] >= 1 and e2["actualizados"] == len(q.recibos)
    assert next(it for it in q.items.values() if it["Name"] == contabilidad.nombre_item(un_agua))["Taxable"]


def test_al_conectar_un_quickbooks_vacio_se_migran_las_reglas():
    """Una empresa de QuickBooks nueva queda con los tax codes y cada producto con su marca, sin enviar nada."""
    from tests.falso_qbo import Falso

    from ezsnack import contabilidad
    _, integ = _integ()
    almacen.registrar_productos(integ["producto"].unique())
    otro = next(p for p in integ["producto"].unique() if not productos.es_exento(p, almacen.reglas()))
    almacen.marcar_producto(otro, "Humberto", exento=True)            # una clasificacion a mano tambien viaja
    q = Falso()
    m = contabilidad.preparar(q, almacen.reglas(), almacen.productos())
    assert set(m["tasas"]) == {"Solo estado", "Houston", "Houston MTA"} and len(q.codes) == 3
    items = {it["Name"]: it["Taxable"] for it in q.items.values() if it["Type"] == "NonInventory"}
    agua = {contabilidad.nombre_item(p) for p in integ["producto"].unique() if productos.es_exento(p, almacen.reglas())} | {contabilidad.nombre_item(otro)}
    assert {n for n, t in items.items() if not t} == agua and m["catalogo"]["agua"] == len(agua)
    assert {it["Name"] for it in q.items.values() if it["Type"] == "Service"} >= {"Devoluciones a clientes", "Cupones vendidos a empresas"}
    # conectar otra vez no duplica nada
    m2 = contabilidad.preparar(q, almacen.reglas(), almacen.productos())
    assert m2["catalogo"]["creados"] == 0 and len(q.codes) == 3


def test_devoluciones_por_defecto_son_los_cupones():
    _, integ = _integ()
    r = cierre.calcular(integ, cierre.Ajustes(), 2026, 9)
    assert r["pasos"]["devoluciones_metodo"] == "cupones"
