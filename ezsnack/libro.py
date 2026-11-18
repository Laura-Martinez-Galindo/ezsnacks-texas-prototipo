"""Excel del cierre.

Sigue la estructura del archivo que la empresa arma cada mes, para que el gerente lo reconozca:
las hojas Master Sales_<mes>, Read Me, Payment Summary, Pivot Table y Data. La diferencia es que
los valores que antes se sacaban filtrando a mano (agua, compras con impuesto pagado, maquinas de
Houston y del MTA, cupones) ahora salen con formulas, asi que al abrirlo se ve de donde sale cada
numero y se puede cambiar una lista y recalcular.

La hoja Machines tiene un renglon por maquina, que es un recibo de venta en QuickBooks: lo vendido,
las devoluciones, el agua, lo comprado con impuesto pagado y la venta gravable. El resumen de la
hoja Master Sales suma esa hoja, de modo que el Excel, la pagina y QuickBooks salen del mismo numero.
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
import xlsxwriter

MESES = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"]
MES_LARGO = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]
COLS = ["Source", "Machine", "Product", "Barcode", "Category", "Quantity Sold", "Sales Revenue", "Cost", "Profit",
        "Sales Tax", "Credit Sales", "Cash Sales", "Coupon Sales", "Account Sales", "Prepaid Credit Sales",
        "Monyx Balance Sales", "Machine ID"]
CONT = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def _txt(v):
    return None if v is None or pd.isna(v) else str(v)


def libro(res: dict, lecturas: list, anio: int, mes: int) -> bytes:
    d = res["detalle"]
    p = res["pasos"]
    n = len(d)
    hoja = f"Master Sales_{MESES[mes - 1]}{anio}"
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    f = lambda **k: wb.add_format({"font_name": "Calibri", "font_size": 11, **k})  # noqa: E731
    cab = f(bold=True, font_color="#FFFFFF", bg_color="#17365D", valign="vcenter")
    num = f(num_format="#,##0.00")
    cont = f(num_format=CONT, align="right")
    sub = f(bg_color="#C6E0B4")
    subn = f(bg_color="#C6E0B4", num_format="#,##0.00")
    naranja = f(bold=True, bg_color="#FFC000", align="right", font_name="Arial", font_size=10)
    verde = f(bg_color="#92D050", align="center")
    verde_i = f(bg_color="#92D050", align="left")
    verden = f(bg_color="#92D050", num_format=CONT, align="right")
    amar = f(bg_color="#FFFF00")
    amarn = f(bg_color="#FFFF00", num_format=CONT, align="right")
    izq = f(align="left")
    centro = f(align="center")

    # ---------- Lists: lo que alimenta las formulas ----------
    maquinas = d.drop_duplicates("maquina")
    listas = {
        "Water products (exempt)": res["lista_exentos"],
        "Products bought with sales tax paid": res["lista_pagados"],
        "Machines with local tax": sorted(maquinas.loc[maquinas["jurisdiccion"] != "", "maquina"]),
        "Machines with state tax only": sorted(maquinas.loc[maquinas["jurisdiccion"] == "", "maquina"]),
        "Coupons sold to companies": sorted({c["maquina"] for c in res["cupones"] if c["de_empresa"]}),
        "Coupons refunded to customers": sorted({c["maquina"] for c in res["cupones"] if not c["de_empresa"]}),
    }

    # ---------- Master Sales ----------
    ws = wb.add_worksheet(hoja)
    wl = None  # Lists se crea al final para conservar el orden de las hojas
    ws.set_row(0, 27.95)
    for col, ancho in zip("ABCDEFGHIJKLMNOPQ", [13, 53, 43, 20, 22, 17, 18, 16, 12, 12, 22, 14, 14, 14, 20, 20, 12]):
        ws.set_column(f"{col}:{col}", ancho)
    d = d.assign(revenue=d[["efectivo", "tarjeta", "cupones", "cuenta", "prepago", "otros"]].sum(axis=1))
    filas = []
    for r in d.itertuples(index=False):
        filas.append([r.fuente, r.maquina, r.producto, _txt(r.barcode), _txt(r.categoria), r.cantidad, r.revenue, _num(r.costo),
                      _num(r.utilidad), _num(r.impuesto), r.tarjeta, r.efectivo, r.cupones, r.cuenta, r.prepago, r.otros,
                      str(r.id_maquina or "")])
    ws.add_table(0, 0, n, 16, {
        "name": "MasterSales", "style": "Table Style Medium 2", "data": filas,
        "columns": [{"header": c, "header_format": cab, **({"format": num} if 5 <= i <= 15 else {})} for i, c in enumerate(COLS)],
    })
    ws.freeze_panes(1, 0)

    # ---------- Machines: un renglon por maquina = un recibo de venta en QuickBooks ----------
    pm = res["maquinas"].reset_index(drop=True)
    dev = res["reglas"]["devoluciones"]
    por_pct = dev["metodo"] == "porcentaje"
    nm = len(pm)
    wm_ = wb.add_worksheet("Machines")
    MCOLS = ["Machine ID", "Machine", "City", "Local tax", "Coupons are", "Cash Sales", "Credit Sales", "Coupon Sales",
             "Net cash", "Net credit", "Water cash", "Water credit", "Tax paid cash", "Tax paid credit",
             "Net sales", "Water", "Bought with tax paid", "Taxable sales"]
    for i, (c, ancho) in enumerate(zip(MCOLS, [11, 50, 16, 14, 12, 13, 13, 13, 13, 13, 12, 12, 13, 14, 13, 12, 18, 14])):
        wm_.write(0, i, c, cab)
        wm_.set_column(i, i, ancho)
    empresas = {c["id_maquina"] for c in res["cupones"] if c["de_empresa"]}
    fa = max(len(res["lista_exentos"]), 1) + 1
    fb = max(len(res["lista_pagados"]), 1) + 1

    def por_lista(col: str, fin_l: int, campo: str, r: int) -> str:
        return (f"=SUMPRODUCT((MasterSales[Machine ID]=A{r})*COUNTIF(Lists!${col}$2:${col}${fin_l},MasterSales[Product])"
                f"*MasterSales[{campo}])")

    for i, m in enumerate(pm.itertuples(index=False)):
        r = i + 2
        cup = "" if por_pct else ("sale" if m.id_maquina in empresas else "refund")
        wm_.write_string(i + 1, 0, str(m.id_maquina or ""))
        wm_.write_string(i + 1, 1, str(m.maquina))
        wm_.write_string(i + 1, 2, str(m.ciudad or ""))
        wm_.write_string(i + 1, 3, str(m.jurisdiccion or ""))
        wm_.write_string(i + 1, 4, cup)
        wm_.write_formula(f"F{r}", f"=SUMIFS(MasterSales[Cash Sales],MasterSales[Machine ID],A{r})", num, float(m.efectivo))
        wm_.write_formula(f"G{r}", f"=SUMIFS(MasterSales[Credit Sales],MasterSales[Machine ID],A{r})", num, float(m.tarjeta))
        wm_.write_formula(f"H{r}", f"=SUMIFS(MasterSales[Coupon Sales],MasterSales[Machine ID],A{r})", num,
                          float(m.cup_emp + m.cup_dev) if not por_pct else float(d.loc[d["id_maquina"] == m.id_maquina, "cupones"].sum()))
        if por_pct:
            wm_.write_formula(f"I{r}", f"=ROUND(F{r}*(1-Lists!$H$2/100),2)", num, float(m.neto_e))
            wm_.write_formula(f"J{r}", f"=ROUND(G{r}*(1-Lists!$H$2/100),2)", num, float(m.neto_t))
        else:
            wm_.write_formula(f"I{r}", f"=F{r}", num, float(m.neto_e))
            wm_.write_formula(f"J{r}", f'=G{r}+IF(E{r}="sale",H{r},-H{r})', num, float(m.neto_t))
        wm_.write_formula(f"K{r}", por_lista("A", fa, "Cash Sales", r), num, float(m.ex_e))
        wm_.write_formula(f"L{r}", por_lista("A", fa, "Credit Sales", r), num, float(m.ex_t))
        wm_.write_formula(f"M{r}", por_lista("B", fb, "Cash Sales", r), num, float(m.pag_e))
        wm_.write_formula(f"N{r}", por_lista("B", fb, "Credit Sales", r), num, float(m.pag_t))
        wm_.write_formula(f"O{r}", f"=I{r}+J{r}", num, float(m.ventas))
        wm_.write_formula(f"P{r}", f"=MIN(K{r}+L{r},O{r}-Q{r})", num, float(m.exentas))
        wm_.write_formula(f"Q{r}", f"=M{r}+N{r}", num, float(m.pagadas))
        wm_.write_formula(f"R{r}", f"=O{r}-P{r}-Q{r}", num, float(m.gravable))
    tot_m = f(bold=True, bg_color="#DDEBF7", num_format="#,##0.00")
    wm_.write(nm + 1, 1, "Total", tot_m)
    for i, c in enumerate(MCOLS):
        if i >= 5:
            col = "ABCDEFGHIJKLMNOPQR"[i]
            clave = {5: "efectivo", 6: "tarjeta", 8: "neto_e", 9: "neto_t", 10: "ex_e", 11: "ex_t", 12: "pag_e",
                     13: "pag_t", 14: "ventas", 15: "exentas", 16: "pagadas", 17: "gravable"}.get(i)
            wm_.write_formula(nm + 1, i, f"=SUM({col}2:{col}{nm + 1})", tot_m,
                              float(pm[clave].sum()) if clave else float(d["cupones"].sum()))
    wm_.freeze_panes(1, 2)

    J = res["reglas"]["jurisdicciones"]
    s = n + 2          # fila de Subtotal (numeracion de Excel)
    v = s + 2          # Sales (cash + credit)
    ce, t, dv, m, w, g, wm, tp = (v + i for i in range(1, 9))
    ws.write(f"C{s}", "Subtotal")
    ws.write(f"D{s}", " ", sub)
    ws.write(f"E{s}", "Subtotal", sub)
    totales = {"F": d["cantidad"].sum(), "G": d["revenue"].sum(), "K": d["tarjeta"].sum(), "L": d["efectivo"].sum(),
               "M": d["cupones"].sum(), "N": d["cuenta"].sum(), "O": d["prepago"].sum(), "P": d["otros"].sum()}
    for col, titulo in zip("FGHIJKLMNOP", COLS[5:]):
        if col in totales:
            ws.write_formula(f"{col}{s}", f"=SUBTOTAL(9,MasterSales[{titulo}])", subn, float(totales[col]))
        else:
            ws.write(f"{col}{s}", " ", subn)

    ws.write(f"F{s + 1}", "Cash Sales", naranja)
    ws.write(f"G{s + 1}", "Credit Sales", naranja)
    ws.write(f"H{s + 1}", "Total", naranja)

    def fila(r, titulo, f_ef, f_tj, clave, fmt_t=None, fmt_n=cont, unir=True):
        if unir:
            ws.merge_range(f"D{r}:E{r}", titulo, fmt_t or izq)
        else:
            ws.write(f"D{r}", titulo, fmt_t)
            if fmt_t is amar:
                ws.write(f"E{r}", None, amar)
        v = p[clave]
        ws.write_formula(f"F{r}", f_ef, fmt_n, v["efectivo"])
        ws.write_formula(f"G{r}", f_tj, fmt_n, v["tarjeta"])
        ws.write_formula(f"H{r}", f"=F{r}+G{r}", fmt_n, v["total"])

    M = lambda col: f"Machines!${col}$2:${col}${nm + 1}"  # noqa: E731
    suma = lambda col: f"=SUM({M(col)})"  # noqa: E731
    de = lambda jur, col: f'=SUMIF({M("D")},"{jur}",{M(col)})'  # noqa: E731

    fila(v, "Sales (cash and credit)", "=SUM(MasterSales[Cash Sales])", "=SUM(MasterSales[Credit Sales])",
         "ventas", unir=False)
    fila(ce, "Coupons sold to companies", "=0",
         "=0" if por_pct else f'=SUMIF({M("E")},"sale",{M("H")})', "cupones_empresa", unir=False)
    fila(t, "Total sales", f"=F{v}+F{ce}", f"=G{v}+G{ce}", "total", unir=False)
    fila(dv, f"Returns to customer ({dev['porcentaje']:g} %)" if por_pct else "Returns to customer (coupons)",
         f"=F{t}-F{m}", f"=G{t}-G{m}", "devoluciones", unir=False)
    fila(m, "Total minus returns to customer", suma("I"), suma("J"), "neto", verde, verden)
    fila(w, "Water Sells", suma("K"), suma("L"), "agua", unir=False)
    fila(g, "Taxable sells", f"=F{m}-F{w}-F{wm}", f"=G{m}-G{w}-G{wm}", "gravable", amar, amarn, unir=False)
    ws.merge_range(f"I{g}:L{g}", "Removing Sales tax already paid", centro)
    fila(wm, "Walmart buys (Taxes paid)", suma("M"), suma("N"), "walmart")
    fila(tp, "Taxes Paid (Walmart buys)", f"=F{wm}*0.0625", f"=G{wm}*0.0625", "impuesto_walmart", amar, amarn)
    # cuatro renglones por cada jurisdiccion local que tenga la empresa en sus reglas
    r0 = tp + 1
    for nombre, j in J.items():
        ciudades = " ".join(j["ciudades"])
        titulo = nombre if nombre.lower() == ciudades.lower() else f"{nombre} ({ciudades})"
        fila(r0, f"{titulo} sales minus returns to customer", de(nombre, "I"), de(nombre, "J"), f"bruto_{nombre}")
        fila(r0 + 1, f"{nombre} water", de(nombre, "K"), de(nombre, "L"), f"agua_{nombre}")
        fila(r0 + 2, f"{nombre} Walmart buys", de(nombre, "M"), de(nombre, "N"), f"pagadas_{nombre}")
        fila(r0 + 3, f"{nombre} Taxable sales ({j['nombre_comptroller']})", f"=F{r0}-F{r0 + 1}-F{r0 + 2}",
             f"=G{r0}-G{r0 + 1}-G{r0 + 2}", f"base_{nombre}", verde_i, verden)
        r0 += 4

    # ---------- Read Me ----------
    rm = wb.add_worksheet("Read Me")
    rm.set_column("A:A", 26)
    rm.set_column("B:B", 105)
    rm.write("A1", "Integrated Sales Workbook")
    rm.write("B1", f"{MES_LARGO[date.today().month - 1]} {date.today().day}, {date.today().year}")
    rm.write("A4", "Source", cab)
    rm.write("B4", "Input rows", cab)
    fila_rm = 5
    for l in lecturas:
        rm.write(f"A{fila_rm}", l.fuente)
        rm.write_number(f"B{fila_rm}", l.leidas, izq)
        fila_rm += 1
    rm.write(f"A{fila_rm}", "Master rows")
    rm.write_number(f"B{fila_rm}", n, izq)
    periodo = f"{MES_LARGO[mes - 1]} {anio}"
    notas = [
        ("Method", "Each row represents a source + machine + product. Nayax transactions are grouped by machine and product."),
        ("Nayax quantity", "Blank transaction quantity is treated as 1 vend. Declined transactions (value 0) are not counted."),
        ("Missing fields", "Blank cells mean the source report did not provide that metric."),
        ("Period", periodo),
        ("Payment amounts", "Added credit, cash, coupon, account, prepaid credit and Monyx balance amounts."),
        ("Credit-only systems", "Qingo and XMAI are credit-only, confirmed by EzSnack Texas."),
        ("Nayax coupons", "No payment method explicitly identifies coupons. Prepaid and Monyx amounts are kept separate."),
        ("Coupons", "Hoerbiger buys coupons every month for its employees: that is a sale. The rest are sent to "
                    "customers who report a failed vend: that is a return."),
        ("Returns", f"Returns to customer are {dev['porcentaje']:g} % of cash and credit sales, machine by machine." if por_pct
                    else "Returns to customer are the refund coupons of the month. Coupons bought by companies are sales."),
        ("Machines", "One row per machine: it is the sales receipt sent to QuickBooks. The summary adds that sheet."),
        ("Lists", "Water and Walmart buys come from Lists. Change a list and the workbook recalculates."),
        ("Files", "; ".join(f"{l.fuente}: {l.archivo}" for l in lecturas)),
    ]
    fila_rm += 2
    for a, b in notas:
        rm.write(f"A{fila_rm}", a)
        rm.write(f"B{fila_rm}", b)
        fila_rm += 1

    # ---------- Payment Summary ----------
    ps = wb.add_worksheet("Payment Summary")
    ps.hide_gridlines(2)
    ps.set_column("A:A", 25)
    ps.set_column("B:B", 28)
    ps.set_column("C:H", 23)
    ps.write("A2", "Sales by payment method (USD)", f(bold=True, font_size=14))
    cab2 = f(bold=True, font_color="#FFFFFF", bg_color="#19395C")
    for i, c in enumerate(["Source", "Credit Sales", "Cash Sales", "Coupon Sales", "Account Sales",
                           "Prepaid Credit Sales", "Monyx Balance Sales", "Sales Revenue"]):
        ps.write(3, i, c, cab2)
    usd = f(num_format='"$"#,##0.00')
    campos = [("K", "tarjeta"), ("L", "efectivo"), ("M", "cupones"), ("N", "cuenta"), ("O", "prepago"), ("P", "otros"), ("G", "revenue")]
    for i, fuente in enumerate(sorted(d["fuente"].unique())):
        r = 5 + i
        ps.write(f"A{r}", fuente)
        for j, (col, campo) in enumerate(campos):
            ps.write_formula(r - 1, j + 1, f"=SUMIF('{hoja}'!$A$2:$A${n + 1},A{r},'{hoja}'!${col}$2:${col}${n + 1})",
                             usd, float(d.loc[d["fuente"] == fuente, campo].sum()))
    ps.write("A11", "Payment classification")
    ps.write("B11", "Basis")
    for r, (a, b) in enumerate([
        ("AV360", "Cash, credit, coupon and account amounts come from the source report."),
        ("Nayax", "Credit Card methods are credit. Cash, prepaid credit and Monyx balance are separate."),
        ("Qingo and XMAI", "All sales classified as credit, as confirmed by EzSnack Texas."),
        ("Coupon coverage", "Nayax has no separately identified coupon method in this export."),
    ], start=12):
        ps.write(f"A{r}", a)
        ps.merge_range(f"B{r}:H{r}", b, f())

    # ---------- Pivot Table y Data ----------
    pm = d.groupby("maquina", as_index=False).agg(revenue=("revenue", "sum"), cantidad=("cantidad", "sum")).sort_values("maquina")  # noqa: F841
    for nombre, formulas in (("Pivot Table", True), ("Data", False)):
        pv = wb.add_worksheet(nombre)
        pv.set_column("A:A", 60.2)
        pv.set_column("B:C", 21)
        fmt = num if formulas else f()
        tit = f(bold=True, bg_color="#DDEBF7") if formulas else f()
        for i, c in enumerate(["Row Labels", "Sum of Sales Revenue", "Sum of Quantity Sold"]):
            pv.write(2, i, c, tit)
        for i, r in enumerate(pm.itertuples(index=False)):
            fila_pv = 4 + i
            pv.write(f"A{fila_pv}", r.maquina, izq if formulas else f())
            if formulas:
                pv.write_formula(f"B{fila_pv}", f"=SUMIF(MasterSales[Machine],A{fila_pv},MasterSales[Sales Revenue])", fmt, float(r.revenue))
                pv.write_formula(f"C{fila_pv}", f"=SUMIF(MasterSales[Machine],A{fila_pv},MasterSales[Quantity Sold])", fmt, float(r.cantidad))
            else:
                pv.write_number(f"B{fila_pv}", float(r.revenue))
                pv.write_number(f"C{fila_pv}", float(r.cantidad))
        fin = 4 + len(pm)
        pv.write(f"A{fin}", "Grand Total", tit)
        if formulas:
            pv.write_formula(f"B{fin}", f"=SUM(B4:B{fin - 1})", f(bold=True, bg_color="#DDEBF7", num_format="#,##0.00"), float(pm["revenue"].sum()))
            pv.write_formula(f"C{fin}", f"=SUM(C4:C{fin - 1})", f(bold=True, bg_color="#DDEBF7", num_format="#,##0.00"), float(pm["cantidad"].sum()))
        else:
            pv.write_number(f"B{fin}", float(pm["revenue"].sum()))
            pv.write_number(f"C{fin}", float(pm["cantidad"].sum()))

    # ---------- Lists ----------
    wl = wb.add_worksheet("Lists")
    for i, (titulo, valores) in enumerate(listas.items()):
        wl.set_column(i, i, 52)
        wl.write(0, i, titulo, cab)
        for j, v in enumerate(valores):
            wl.write_string(j + 1, i, str(v))
    wl.write(0, 7, "Returns to customer %", cab)
    wl.set_column(7, 7, 24)
    wl.write_number(1, 7, float(dev["porcentaje"]) if por_pct else 0.0)
    wl.freeze_panes(1, 0)

    wb.close()
    return buf.getvalue()
