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


def test_cierre_sigue_el_procedimiento(lecturas):
    integ = cierre.integrar(lecturas, maquinas.leer(D / "vendor_list_EJEMPLO.xlsx"))
    a = cierre.Ajustes(lista_pagados=productos.leer_lista(D / "compras_impuesto_pagado_EJEMPLO.xlsx"))
    r = cierre.calcular(integ, a, 2026, 9)
    p, d = r["pasos"], r["declaracion"]
    assert p["neto"] == pytest.approx(p["total"] * 0.97, abs=0.01)
    assert p["gravable"] == pytest.approx(p["neto"] - p["exentas"] - p["pagadas"], abs=0.01)
    assert d["impuesto_estado"] == pytest.approx(round(d["ventas_gravables"] * 0.0625, 2))
    assert d["descuento"] == pytest.approx(round(d["impuesto_total"] * 0.005, 2))
    assert d["vence"] == "2026-10-20"
    # Smart Water es exenta y esta en la lista de compras: no se descuenta dos veces
    assert "Smart Water" not in set(r["pagados"].loc[r["pagados"]["marcado"], "producto"])


def test_comision_procity_respeta_el_minimo(lecturas):
    integ = cierre.integrar(lecturas, maquinas.leer(D / "vendor_list_EJEMPLO.xlsx"))
    r = cierre.calcular(integ, cierre.Ajustes(), 2026, 9)
    for f in r["comisiones"]["detalle"]:
        if f["socio"] == "ProCity":
            assert f["aplica"] == (f["ventas"] > 300)


def test_api_de_ejemplo_y_excel():
    c = TestClient(app)
    d = c.post("/api/cierre/ejemplo").json()
    assert d["declaracion"]["a_pagar"] > 0
    r = c.post(f"/api/cierre/{d['codigo']}/libro", json={"anio": 2026, "mes": 9})
    assert r.status_code == 200 and r.content[:2] == b"PK"
