"""Genera los archivos de ejemplo de la carpeta datos_prueba.

Tienen el mismo formato que los reportes reales que exporta cada lector (Nayax, AV360, XMAI y
Qingo) y que el vendor list de la empresa, pero las maquinas, direcciones y ventas son ficticias.
Los datos reales de la empresa no se publican en este repositorio.

    python scripts/generar_datos_prueba.py
"""
from __future__ import annotations

import random
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

SALIDA = Path(__file__).resolve().parents[1] / "datos_prueba"
random.seed(2609)

# id, locacion, direccion, ciudad, zip, comision, lector
MAQUINAS = [
    (201, "City Hall Annex", "900 Bagby St", "Houston", "77002", "ProCity", "Nayax"),
    (202, "Convention Center Hall A", "1001 Avenida de las Americas", "Houston", "77010", "ProCity", "Nayax"),
    (203, "Central Library", "500 McKinney St", "Houston", "77002", "", "Nayax"),
    (204, "Medical Center Garage 2", "6550 Bertner Ave", "Houston", "77030", "ProCity", "Nayax"),
    (205, "North American University - Piso 1", "11929 W Airport Blvd", "Stafford", "77477", "", "Nayax"),
    (206, "North American University - Piso 3", "11929 W Airport Blvd", "Stafford", "77477", "", "Nayax"),
    (207, "Warehouse Distribution", "3898 Distribution Blvd", "Houston", "77018", "", "AV360"),
    (208, "Regus Six Pines", "9595 Six Pines Dr", "Spring", "77380", "VMS", "AV360"),
    (209, "Regus Park Ten", "16225 Park Ten Pl", "Houston", "77084", "VMS", "AV360"),
    (210, "Bellaire Office Park", "5110 Bellaire Blvd", "Bellaire", "77401", "ProCity", "AV360"),
    (211, "Katy Veterinary", "4611 FM 1463", "Katy", "77494", "", "AV360"),
    (212, "Sugar Land Tubing", "1407 Gillingham Ln", "Sugar Land", "77478", "ProCity", "AV360"),
    (213, "Westheimer Showroom", "4006 Westheimer Rd", "Houston", "77027", "", "XMAI"),
    (214, "Haden Electric Warehouse", "1823 Haden Rd", "Houston", "77015", "ProCity", "Qingo"),
]

# nombre en Nayax, nombre en AV360, precio, demanda relativa
PRODUCTOS = [
    ("Coke 16.9 fl. oz.", "Coke Classic - 12 oz. can", 2.00, 9),
    ("Diet Coke 16.9 oz", "Diet Coke 12 oz", 2.00, 6),
    ("Dr Pepper 16.9oz", "12oz - Dr. Pepper", 2.00, 6),
    ("Diet Dr. Pepper 16.9 fl. oz.", "12oz - Diet Dr. Pepper", 2.00, 3),
    ("Sunkist Orange 16.9oz", "Sunkist-Orange 12 fl. oz.", 2.00, 4),
    ("Monster Energy 16oz", "Monster Energy Drink 16 Fl Oz", 3.50, 6),
    ("Celsius Variety 12oz", "Celsius Sparkling Orange, 12-Ounce Cans", 3.50, 4),
    ("Gatorade Variety 20 oz", "Gatorade Orange 20oz", 2.60, 4),
    ("Ozarka Water 20 oz", "Ozarka water 20oz", 1.50, 7),
    ("Smart Water", "Smart Water", 2.70, 2),
    ("Topo Chico Mineral Water", "Topo Chico Mineral Water", 2.50, 1),
    ("Vitamin Water - Variety", "Vitamin Water - Variety", 2.80, 2),
    ("DORITOS 1.75 oz", "Doritos Cool Ranch", 1.50, 7),
    ("CHEETOS CRUNCHY - 2 Oz", "Cheetos Crunchy 2oz", 1.50, 6),
    ("Takis Fuego", "Takis 2 Oz", 1.75, 5),
    ("Lance Captain Wafers", "Lance Captain's Wafers", 1.25, 2),
    ("Maruchan Instant lunch Chicken", "Maruchan Spicy Beef", 1.75, 3),
    ("Snickers 2oz", "Snickers", 2.00, 5),
    ("Reese's Peanut Butter Cups", "Reese's Peanut Butter Cups", 2.00, 4),
    ("Duchess Honey Bun 3 oz", "Honey Bun", 2.00, 4),
    ("Famous Amos Chocolate Chip Cookies", "Famous Amos Cookies", 1.50, 4),
    ("Otis Spunkmeyer Muffin", "Otis Spunkmeyer Muffin", 2.50, 3),
]
PAGO_NAYAX = [("Credit Card(NFC)", 1, .45), ("Credit Card(CLS)", 1, .27), ("Cash", 3, .22),
              ("Credit Card(CON)", 1, .03), ("Prepaid Credit(MIFH)", 2, .02), ("Monyx Balance(PHO)", 22, .01)]


def _vendor_list():
    filas = [{"Assigned id": "A2-Warehouse", "Key": None, "Company": "EzSnack Texas", "Address": "4520 W 34th St",
              "City": "Houston", "State": "TX", "ZIP": 77092, "Commision to": None, "Active": "Y"}]
    for mid, loc, dirc, ciudad, zp, com, _ in MAQUINAS:
        filas.append({"Assigned id": f"EzSnack {mid}", "Key": "Y", "Company": loc, "Address": dirc, "City": ciudad,
                      "State": "TX", "ZIP": int(zp), "Commision to": com or " ", "Active": "Y"})
    # una ubicacion anterior de la maquina 207, como las que la empresa guarda con "old"
    filas.append({"Assigned id": "EzSnack 207 - old", "Key": None, "Company": "Old Office Building",
                  "Address": "12651 Briar Forest Dr", "City": "Houston", "State": "TX", "ZIP": 77077,
                  "Commision to": "ProCity", "Active": "N"})
    df = pd.DataFrame(filas)
    for c in ["Address for Planner", "Contact Name", "Contact mail", "Contact Phone #"]:
        df[c] = None
    df.to_excel(SALIDA / "vendor_list_EJEMPLO.xlsx", sheet_name="Locations EZSnack", index=False)


def _nombre(mid):
    m = next(x for x in MAQUINAS if x[0] == mid)
    return f"EzSnack {mid} - {m[2]} - {m[1]}"


def _ventas(mid):
    """Unidades vendidas en el mes por producto para una maquina."""
    escala = random.uniform(.35, 1.6)
    return {p: max(0, int(random.gauss(p[3] * 9 * escala, p[3] * 2.5))) for p in PRODUCTOS}


def _nayax():
    filas = []
    for mid in [m[0] for m in MAQUINAS if m[6] == "Nayax"]:
        for p, unidades in _ventas(mid).items():
            for _ in range(unidades):
                metodo, mid_pago, _ = random.choices(PAGO_NAYAX, weights=[x[2] for x in PAGO_NAYAX])[0]
                filas.append([4, str(random.randint(4_700_000_000, 4_900_000_000)), mid_pago, "USD", _nombre(mid), p[0],
                              "", 0 if metodo != "Cash" else "", p[2], metodo])
                if random.random() < .03:  # tarjeta rechazada: queda con valor 0
                    filas.append([4, str(random.randint(4_700_000_000, 4_900_000_000)), 1, "USD", _nombre(mid), None,
                                  "", 0, 0, "Credit Card(NFC)"])
    random.shuffle(filas)
    total = round(sum(f[8] for f in filas), 2)
    cab = ["Site ID", "Transaction ID", "Payment Method ID", "Currency", "Machine Name", "Product Name", "Quantity",
           "Transaction Type ID", "Settlement Value (Vend Price)", "Payment Method (Source)"]
    df = pd.DataFrame(filas + [[None, None, None, "Total", None, None, None, None, total, None]], columns=cab)
    ruta = SALIDA / "reporte_nayax_2026-09_EJEMPLO.xlsx"
    df.to_excel(ruta, sheet_name="Table1", index=False, startrow=1)
    wb = load_workbook(ruta)
    wb["Table1"]["A1"] = "Dynamic Transactions Monitor\nSearched Date Range: 9/1/2026 12:00:00 AM - 9/30/2026 11:59:59 PM"
    wb.save(ruta)


def _av360():
    filas = []
    for mid in [m[0] for m in MAQUINAS if m[6] == "AV360"]:
        for p, unidades in _ventas(mid).items():
            if not unidades:
                continue
            efectivo = sum(random.random() < .25 for _ in range(unidades))
            cupon = sum(random.random() < .02 for _ in range(unidades - efectivo))
            cash, coupon = efectivo * p[2], cupon * p[2]
            credit = (unidades - efectivo - cupon) * p[2]
            total = cash + credit + coupon
            filas.append([_nombre(mid), p[1], unidades, cash, credit, coupon, 0, total, .0625, total * .0625])
    df = pd.DataFrame(filas, columns=["Machine", "Product", "Quantity Sold", "Cash", "Credit", "Coupon", "Account",
                                      "Total", "Tax Rate", "Tax"])
    suma = df[["Quantity Sold", "Cash", "Credit", "Coupon", "Account", "Total", "Tax"]].sum()
    df.loc[len(df)] = [None, "Totals:", suma["Quantity Sold"], suma["Cash"], suma["Credit"], suma["Coupon"], 0,
                       suma["Total"], .0625, suma["Tax"]]
    df.to_excel(SALIDA / "reporte_av360_2026-09_EJEMPLO.xlsx", sheet_name="SalesTaxDetail", index=False)


def _xmai():
    filas = []
    for p, unidades in _ventas(213).items():
        if unidades:
            filas.append([_nombre(213), str(random.randint(20000, 540000)), p[0], "", "", f"{p[2] + .1:.2f}", str(unidades),
                          f"{unidades * (p[2] + .1):.2f}", "", "0.00", f"{p[2] / 2:.2f}"])
    pd.DataFrame(filas, columns=["Machine ", "Item ID", "Item Name", "Barcode", "Item Category", "Average Unit Price",
                                 "Items Sold", "Sales revenue", "Profit", "Discount Amount", "Cost price"]
                 ).to_excel(SALIDA / "reporte_xmai_2026-09_EJEMPLO.xlsx", sheet_name="Item Sales_1", index=False)


def _qingo():
    filas = []
    for p, unidades in _ventas(214).items():
        if unidades:
            monto = round(unidades * (p[2] + .4), 2)
            filas.append([_nombre(214), p[0], "", "Beverages", "", "USD", 0, unidades, monto, 0, 0, 0, monto, 0, monto, 1, 0])
    cab = ["Machine ", "Product Name", " Product Barcode", " Product Category", " Product Varieties", " currency",
           " Cost Price ($)", " Sales Quantity", " Sales Amount ($)", " Discount Amount ($)", " Refund quantity",
           " Refunds ($)", " Transaction Amount ($)", " Cost amount ($)", " Gross profit", " Gross margin", " Sales Share"]
    ruta = SALIDA / "reporte_qingo_2026-09_EJEMPLO.xlsx"
    pd.DataFrame(filas, columns=cab).to_excel(ruta, index=False, startrow=1)
    wb = load_workbook(ruta)
    wb.active["I1"] = "Product sales statistics 2026-09-01~2026-09-30(export time):2026-10-12 21:01:34"
    wb.save(ruta)


def _compras():
    pd.DataFrame({"Product": ["maruchan", "Sunkist 16 oz", "smart water", "diet dr pepper 16 oz", "lance captain wafers"]}
                 ).to_excel(SALIDA / "compras_impuesto_pagado_EJEMPLO.xlsx", index=False)


if __name__ == "__main__":
    SALIDA.mkdir(exist_ok=True)
    for viejo in SALIDA.glob("*.xlsx"):
        viejo.unlink()
    _vendor_list(); _nayax(); _av360(); _xmai(); _qingo(); _compras()
    print("Listo:", ", ".join(sorted(p.name for p in SALIDA.glob("*.xlsx"))))
