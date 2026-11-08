"""Pruebas sin conexion: corren con los Excel de datos_prueba/.  Uso: python -m pytest -q"""
import json
from pathlib import Path

import pytest

from ezsnack.consolidar import (consolidar, extraer_id_maquina, leer_vendor_list, leer_ventas,
                                resumen_por_maquina, vista_previa_impuesto)
from ezsnack.emparejar import emparejar, es_impuesto
from ezsnack.servicios import armar_recibos, calcular_comisiones

CAT = json.loads(Path("config/catalogo.json").read_text(encoding="utf-8"))
PRODUCTOS = [p["nombre"] for p in CAT["productos"]]
GRAVABLES = {p["nombre"]: p["gravable"] for p in CAT["productos"]}
D = Path("datos_prueba")


@pytest.fixture(scope="module")
def datos():
    vendor = leer_vendor_list(D / "vendor_list_PRUEBA.xlsx")
    ventas = [leer_ventas(D / "nayax_ventas_2026-09_PRUEBA.xlsx", "Nayax"),
              leer_ventas(D / "ab360_ventas_2026-09_PRUEBA.xlsx", "AB360")]
    detalle, problemas = consolidar(ventas, vendor, PRODUCTOS)
    return vendor, ventas, detalle, problemas


def test_id_maquina():
    assert extraer_id_maquina("EzSnack 158 - 1823 Haden Rd - Triac Electric") == "158"
    assert extraer_id_maquina("EzSnack 160 - Crate & Barrel") == "160"


def test_impuesto_detectado():
    assert es_impuesto("TFL TAX") and es_impuesto("IVA $") and es_impuesto("Sales Tax")
    assert not es_impuesto("Doritos Cool Ranch")


def test_emparejar():
    assert emparejar("DORITOS NCH 1OZ", PRODUCTOS)[0] == "Doritos Nacho Cheese 1 oz"   # alias
    assert emparejar("Gatorade 20oz Variety", PRODUCTOS)[2] in ("seguro", "dudoso")
    assert emparejar("Cheetos Crunchy 1 oz", PRODUCTOS)[2] in ("sin_coincidencia", "dudoso")


def test_consolidado_no_pierde_dinero(datos):
    _, ventas, detalle, _ = datos
    assert round(detalle["valor"].sum(), 2) == round(sum(v["valor"].sum() for v in ventas), 2)


def test_alerta_maquina_desconocida(datos):
    _, _, _, problemas = datos
    assert "Maquina no esta en el vendor list" in set(problemas["tipo"])
    assert problemas["texto"].str.contains("999").any()


def test_agua_exenta_en_vista_previa(datos):
    _, _, detalle, _ = datos
    previa = vista_previa_impuesto(detalle, GRAVABLES, {"Houston": 8.25, "MTA": 8.25})
    assert set(previa["jurisdiccion"]) == {"Houston", "MTA"}
    assert (previa["ventas_exentas"] > 0).all()


def test_comisiones_solo_maquinas_con_socio(datos):
    _, _, detalle, _ = datos
    com = calcular_comisiones(detalle)
    assert len(com) == 1 and com.iloc[0]["maquinas"] == "116, 136"
    esperado = detalle[detalle["id_maquina"].isin(["116", "136"])]["valor"].sum() * 0.10
    assert abs(com.iloc[0]["comision"] - esperado) < 0.01


def test_recibos_con_direccion_y_codigo_de_impuesto(datos):
    _, _, detalle, _ = datos
    resumen = resumen_por_maquina(detalle)
    items = {n: {"Id": str(i), "Taxable": GRAVABLES[n]} for i, n in enumerate(PRODUCTOS, 1)}
    recibos = armar_recibos(resumen, items, 2026, 9, "1")
    assert len(recibos) == 7                         # 7 maquinas del vendor list (la 999 queda por fuera)
    r = next(x for x in recibos if x["DocNumber"] == "V2609-158")
    assert r["ShipFromAddr"]["Line1"] == "1823 Haden Rd" and r["TxnDate"] == "2026-09-30"
    codigos = {l["Description"].split(" - ", 1)[1]: l["SalesItemLineDetail"]["TaxCodeRef"]["value"] for l in r["Line"]}
    for prod, cod in codigos.items():
        assert cod == ("TAX" if GRAVABLES[prod] else "NON")
