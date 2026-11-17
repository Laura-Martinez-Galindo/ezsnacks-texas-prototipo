"""Pruebas sin conexion con los archivos de datos_prueba/.  Uso: python -m pytest -q"""
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ezsnack import cierre, lectores, maquinas, productos
from web.main import app

D = Path(__file__).resolve().parents[1] / "datos_prueba"


@pytest.fixture(scope="module")
def lecturas():
    return [lectores.leer(p) for p in sorted(D.glob("reporte_*.xlsx"))]


def test_reconoce_los_cuatro_lectores(lecturas):
    assert sorted(l.fuente for l in lecturas) == ["AV360", "Nayax", "Qingo", "XMAI"]
    for l in lecturas:
        assert l.filas["id_maquina"].notna().all()


def test_nayax_cuadra_con_su_fila_de_total(lecturas):
    nayax = next(l for l in lecturas if l.fuente == "Nayax")
    crudo = pd.read_excel(D / "reporte_nayax_2026-09_EJEMPLO.xlsx", header=1)
    total = crudo.loc[crudo["Currency"] == "Total", "Settlement Value (Vend Price)"].iloc[0]
    suma = nayax.filas[["efectivo", "tarjeta", "prepago", "otros"]].sum().sum()
    assert suma == pytest.approx(total, abs=0.01)


def test_vendor_list_ignora_ubicaciones_viejas():
    m = maquinas.leer(D / "vendor_list_EJEMPLO.xlsx")
    assert m["id_maquina"].is_unique
    assert m.set_index("id_maquina").loc["207", "locacion"] == "Warehouse Distribution"


def test_coincidencias_de_la_lista_de_compras():
    assert productos.coincide("Sunkist 16 oz", "Sunkist Orange 16.9oz") == "seguro"
    assert productos.coincide("Sunkist 16 oz", "Sunkist-Orange 12 fl. oz.") is None
    assert productos.coincide("Sunkist 16 oz", "Sunkist") == "dudoso"
    assert productos.coincide("lance captain wafers", "Lance Captain's Wafers") == "seguro"
    assert productos.coincide("maruchan", "M&M Peanuts") is None
    assert productos.coincide("diet dr pepper 16 oz", "12oz - Diet Dr. Pepper") is None


def test_agua_exenta():
    assert productos.es_exento("Ozarka Water 20 oz")
    assert not productos.es_exento("Vitamin Water - Variety")
    assert not productos.es_exento("Coconut water")


def test_cierre_sigue_las_formulas_del_excel(lecturas):
    integ = cierre.integrar(lecturas, maquinas.leer(D / "vendor_list_EJEMPLO.xlsx"))
    a = cierre.Ajustes(lista_pagados=productos.leer_lista(D / "compras_impuesto_pagado_EJEMPLO.xlsx"))
    r = cierre.calcular(integ, a, 2026, 9)
    p = r["pasos"]
    assert p["total"]["total"] == pytest.approx(p["ventas"]["total"] + p["cupones_empresa"]["total"], abs=0.02)
    assert p["neto"]["total"] == pytest.approx(p["total"]["total"] - p["devoluciones"]["total"], abs=0.02)
    assert p["gravable"]["total"] == pytest.approx(p["neto"]["total"] - p["agua"]["total"] - p["walmart"]["total"], abs=0.02)
    for j in ("Houston", "Houston MTA"):
        assert p[f"base_{j}"]["total"] == pytest.approx(
            p[f"bruto_{j}"]["total"] - p[f"agua_{j}"]["total"] - p[f"pagadas_{j}"]["total"], abs=0.02)
    assert r["declaracion"]["vence"] == "2026-10-20"
    assert "Smart Water" not in r["lista_pagados"]


def test_cupones_de_empresa_se_separan_de_las_devoluciones(lecturas):
    """Una maquina con muchos cupones al mes se los vendio a una empresa: es venta, no devolucion."""
    integ = cierre.integrar(lecturas, maquinas.leer(D / "vendor_list_EJEMPLO.xlsx"))
    r = cierre.calcular(integ, cierre.Ajustes(cupones_empresa=["208"]), 2026, 9)
    assert [c["id_maquina"] for c in r["cupones"] if c["de_empresa"]] == ["208"]
    total = sum(c["valor"] for c in r["cupones"])
    vendidos = sum(c["valor"] for c in r["cupones"] if c["de_empresa"])
    assert r["pasos"]["cupones_empresa"]["total"] == pytest.approx(vendidos, abs=0.02)
    assert r["pasos"]["devoluciones"]["total"] == pytest.approx(total - vendidos, abs=0.02)


def test_excel_tiene_las_hojas_y_formulas_del_integrado(lecturas):
    from io import BytesIO

    from openpyxl import load_workbook

    from ezsnack import libro
    integ = cierre.integrar(lecturas, maquinas.leer(D / "vendor_list_EJEMPLO.xlsx"))
    r = cierre.calcular(integ, cierre.Ajustes(), 2026, 9)
    wb = load_workbook(BytesIO(libro.libro(r, lecturas, 2026, 9)))
    assert wb.sheetnames == ["Master Sales_Sept2026", "Machines", "Read Me", "Payment Summary", "Pivot Table", "Data", "Lists"]
    ws = wb["Master Sales_Sept2026"]
    assert [c.value for c in ws[1]][:3] == ["Source", "Machine", "Product"]
    formulas = [ws.cell(row=f, column=4).value for f in range(ws.max_row - 17, ws.max_row + 1)]
    assert "Coupons sold to companies" in formulas
    assert "Returns to customer (coupons)" in formulas


def test_api_de_ejemplo_y_excel():
    c = TestClient(app)
    d = c.post("/api/cierre/ejemplo").json()
    assert d["declaracion"]["ventas_gravables"] > 0
    r = c.post(f"/api/cierre/{d['codigo']}/libro", json={"anio": 2026, "mes": 9})
    assert r.status_code == 200 and r.content[:2] == b"PK"


# ---------------- reglas de devoluciones, cuadre con QuickBooks y comparacion ----------------
def _cierre(lecturas, **ajustes):
    integ = cierre.integrar(lecturas, maquinas.leer(D / "vendor_list_EJEMPLO.xlsx"))
    a = cierre.Ajustes(lista_pagados=productos.leer_lista(D / "compras_impuesto_pagado_EJEMPLO.xlsx"), **ajustes)
    return cierre.calcular(integ, a, 2026, 9)


@pytest.mark.parametrize("dev", [{"metodo": "cupones"}, {"metodo": "porcentaje", "porcentaje": 3}])
def test_resumen_es_la_suma_de_las_maquinas(lecturas, dev):
    """El resumen, el Excel y los recibos de QuickBooks salen de la misma tabla por maquina, al centavo."""
    r = _cierre(lecturas, devoluciones=dev)
    p, pm = r["pasos"], r["maquinas"]
    assert pm["gravable"].sum() == pytest.approx(p["gravable"]["total"], abs=0.005)
    assert pm["ventas"].sum() == pytest.approx(p["neto"]["total"], abs=0.005)
    assert (pm["gravable"] + pm["exentas"] + pm["pagadas"]).sum() == pytest.approx(pm["ventas"].sum(), abs=0.005)
    for j in ("Houston", "Houston MTA"):
        assert pm.loc[pm["jurisdiccion"] == j, "gravable"].sum() == pytest.approx(p[f"base_{j}"]["total"], abs=0.005)
    # lo que se espera de QuickBooks: la base del estado es toda la venta gravable
    estado = r["declaracion"]["quickbooks_esperado"][0]
    assert estado["base"] == pytest.approx(p["gravable"]["total"], abs=0.005)


def test_devoluciones_por_porcentaje_como_el_excel_a_mano(lecturas):
    r = _cierre(lecturas, devoluciones={"metodo": "porcentaje", "porcentaje": 3})
    p = r["pasos"]
    assert p["cupones_empresa"]["total"] == 0
    assert p["neto"]["total"] == pytest.approx(p["ventas"]["total"] * 0.97, abs=1.0)   # centavos por maquina
    assert p["devoluciones"]["total"] == pytest.approx(p["ventas"]["total"] - p["neto"]["total"], abs=0.005)


def test_nayax_resta_las_devoluciones_en_negativo():
    df = pd.DataFrame({
        "Machine Name": ["EzSnack 1 - A", "EzSnack 1 - A", "EzSnack 1 - A"], "Product Name": ["Coke", "Unknown", "Coke"],
        "Quantity": [None, 1, None], "Settlement Value (Vend Price)": [2.5, -2.5, 0],
        "Payment Method (Source)": ["Credit Card(NFC)", "Credit Card(MOTO)", "Credit Card(NFC)"]})
    l = lectores._nayax(df)
    assert l.filas["tarjeta"].sum() == pytest.approx(0.0)
    assert l.descartadas["transacciones rechazadas (valor 0)"] == 1
    assert l.avisos


def test_formato_registrado_se_reconoce_solo(tmp_path):
    ruta = tmp_path / "otro.xlsx"
    pd.DataFrame({"Kiosko": ["EzSnack 5 - X", "EzSnack 5 - X"], "Articulo vendido": ["Coke", "Agua"],
                  "Neto cobrado": [3.0, 2.0]}).to_excel(ruta, index=False)
    formato = {"nombre": "Cantaloupe", "mapeo": {"maquina": "Kiosko", "producto": "Articulo vendido", "total": "Neto cobrado"}}
    l = lectores.leer(ruta, formatos=[formato])
    assert l.fuente == "Cantaloupe" and l.registrado and not l.generico
    assert l.filas["tarjeta"].sum() == pytest.approx(5.0)
    with pytest.raises(lectores.FormatoDesconocido):
        lectores.leer(ruta)


def test_comparacion_encuentra_la_maquina_que_falto(lecturas):
    """Se arma un Excel 'a mano' con el 3 % fijo y sin una maquina de Houston, y la comparacion lo dice."""
    from io import BytesIO

    from ezsnack import comparar
    lista = maquinas.leer(D / "vendor_list_EJEMPLO.xlsx")
    r = _cierre(lecturas)
    d = r["detalle"]
    tabla = pd.DataFrame({"Source": d["fuente"], "Machine": d["maquina"], "Product": d["producto"],
                          "Cash Sales": d["efectivo"], "Credit Sales": d["tarjeta"], "Coupon Sales": d["cupones"]})
    houston = r["maquinas"][r["maquinas"]["jurisdiccion"] == "Houston"]
    falta = houston.iloc[0]
    bruto = float(houston[["efectivo", "tarjeta"]].sum().sum()) - float(falta["efectivo"] + falta["tarjeta"])
    total = float(tabla["Cash Sales"].sum() + tabla["Credit Sales"].sum())
    resumen = pd.DataFrame([
        {"Product": "Total sales", "Cash Sales": float(tabla["Cash Sales"].sum()), "Credit Sales": float(tabla["Credit Sales"].sum()), "Coupon Sales": total},
        {"Product": "Totals minus returns to customer", "Cash Sales": total * 0.97, "Credit Sales": 0, "Coupon Sales": total * 0.97},
        {"Product": "Houston  Taxable sales", "Cash Sales": bruto, "Credit Sales": 0, "Coupon Sales": bruto},
    ])
    buf = BytesIO()
    pd.concat([tabla, resumen]).assign(Source=lambda x: x["Source"]).to_excel(buf, index=False)
    c = comparar.comparar(comparar.leer_original(buf, "a_mano.xlsx"), r, lista)
    filas = {f["concepto"]: f for f in c["filas"]}
    assert filas["Ventas en efectivo y tarjeta"]["dif"] == 0
    assert any("3 % fijo" in x for x in filas["Devoluciones a clientes"]["causas"])
    assert any(falta["maquina"] in x for x in filas["Ventas de las máquinas de Houston"]["causas"])
