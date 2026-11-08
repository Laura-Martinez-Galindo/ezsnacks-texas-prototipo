"""EzSnack Impuestos: interfaz para Humberto.

Correr con:  streamlit run app.py
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from ezsnack import qbo as qbo_mod
from ezsnack.consolidar import consolidar, leer_vendor_list, leer_ventas, resumen_por_maquina, vista_previa_impuesto
from ezsnack.emparejar import guardar_alias
from ezsnack.preparar import cargar_datos, ejecutar_limpieza, es_sandbox, plan_limpieza, resumen_plan
from ezsnack.servicios import (
    armar_recibos, calcular_comisiones, enviar_recibos, id_cliente_ventas, productos_qbo,
    registrar_comisiones, revisar_recibos, ultimo_dia,
)

st.set_page_config(page_title="EzSnack Impuestos", page_icon="🧾", layout="wide")
CATALOGO = json.loads(Path("config/catalogo.json").read_text(encoding="utf-8"))
TARIFAS = {k: v for k, v in json.loads(Path("config/tarifas.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def dinero(x) -> str:
    return f"${x:,.2f}"


# ---------------- conexion (OAuth) ----------------
params = st.query_params
if "code" in params and "realmId" in params and not st.session_state.get("conexion_procesada"):
    try:
        qbo_mod.cambiar_codigo_por_tokens(params["code"], params["realmId"])
        st.session_state["conexion_procesada"] = True
        st.query_params.clear()
        st.success("Conectado con QuickBooks.")
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo completar la conexion: {exc}")


def cliente_qbo():
    try:
        return qbo_mod.QBO() if qbo_mod.esta_conectado() else None
    except Exception:  # noqa: BLE001
        return None


with st.sidebar:
    st.header("🧾 EzSnack Impuestos")
    qbo = cliente_qbo()
    if qbo:
        try:
            st.success(f"Conectado a: {qbo.info_empresa().get('CompanyName')}")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"La conexion fallo: {exc}")
            qbo = None
        if st.button("Desconectar"):
            qbo_mod.desconectar()
            st.rerun()
    if not qbo:
        st.info("No conectado a QuickBooks. Puede consolidar igual; para enviar, conecte.")
        try:
            st.link_button("Conectar con QuickBooks", qbo_mod.url_autorizacion())
        except qbo_mod.QBOError as exc:
            st.error(str(exc))
        except Exception:  # noqa: BLE001
            st.error("No se pudo contactar a Intuit. Revise la conexion a internet y el archivo .env.")
    st.divider()
    hoy = date.today()
    anio = st.number_input("Año", 2020, 2100, hoy.year if hoy.month > 1 else hoy.year - 1)
    mes = st.selectbox("Mes a declarar", range(1, 13), index=(hoy.month - 2) % 12,
                       format_func=lambda m: MESES[m - 1])
    st.caption("La declaracion vence el 20 del mes siguiente (Texas Comptroller).")


@st.cache_data(ttl=300, show_spinner=False)
def lista_productos(conectado: bool) -> dict[str, bool]:
    """Nombre -> gravable. Desde QuickBooks si hay conexion; si no, desde el catalogo local."""
    if conectado:
        try:
            return {n: d["Taxable"] for n, d in productos_qbo(qbo_mod.QBO()).items()}
        except Exception:  # noqa: BLE001
            pass
    return {p["nombre"]: p["gravable"] for p in CATALOGO["productos"]}


gravables = lista_productos(qbo is not None)
productos = list(gravables)

tab_ventas, tab_recibos, tab_comisiones, tab_preparar, tab_ayuda = st.tabs(
    ["1. Ventas del mes", "2. Recibos con impuesto pagado", "3. Comisiones", "Preparar sandbox", "Ayuda"]
)

# ---------------- 1. ventas ----------------
with tab_ventas:
    st.subheader(f"Ventas de {MESES[mes - 1]} {anio}")
    c1, c2 = st.columns(2)
    with c1:
        f_vendor = st.file_uploader("Vendor list (maquinas)", type=["xlsx", "xls", "csv"])
    with c2:
        f_nayax = st.file_uploader("Reportes de Nayax", type=["xlsx", "xls", "csv"], accept_multiple_files=True)
        f_ab360 = st.file_uploader("Reportes de AB360", type=["xlsx", "xls", "csv"], accept_multiple_files=True)
        f_otro = st.file_uploader("Reportes de otro lector", type=["xlsx", "xls", "csv"], accept_multiple_files=True)

    if st.button("Unir y revisar", type="primary", disabled=not f_vendor):
        try:
            vendor = leer_vendor_list(f_vendor)
            tablas = [leer_ventas(f, "Nayax") for f in f_nayax] + [leer_ventas(f, "AB360") for f in f_ab360] \
                + [leer_ventas(f, "Otro") for f in f_otro]
            if not tablas:
                st.warning("Suba al menos un reporte de ventas.")
            else:
                detalle, problemas = consolidar(tablas, vendor, productos)
                st.session_state.update(detalle=detalle, problemas=problemas)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    if "detalle" in st.session_state:
        detalle = st.session_state["detalle"]
        problemas = st.session_state["problemas"]
        resumen = resumen_por_maquina(detalle)
        d_ok = detalle[detalle["producto"].notna()]
        exento = d_ok[~d_ok["producto"].map(lambda p: gravables.get(p, True))]["valor"].sum()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Lineas unidas", f"{len(detalle):,}")
        m2.metric("Ventas totales", dinero(detalle["valor"].sum()))
        m3.metric("Ventas exentas (agua)", dinero(exento))
        m4.metric("Por revisar", len(problemas))

        if not problemas.empty:
            st.warning("Esto no se enviara hasta que se corrija:")
            st.dataframe(problemas, use_container_width=True, hide_index=True)
            dudosos = problemas[problemas["tipo"] != "Maquina no esta en el vendor list"]
            if not dudosos.empty:
                with st.expander("Asignar productos no reconocidos"):
                    for _, p in dudosos.iterrows():
                        opciones = ["(dejar por fuera)"] + productos
                        idx = opciones.index(p["sugerencia"]) if p["sugerencia"] in opciones else 0
                        elegido = st.selectbox(f"'{p['texto']}' es:", opciones, index=idx, key=f"al_{p['texto']}")
                        if elegido != "(dejar por fuera)" and st.button("Guardar equivalencia", key=f"bt_{p['texto']}"):
                            guardar_alias(p["texto"], elegido)
                            st.success("Guardado. Vuelva a 'Unir y revisar'.")

        st.markdown("**Ventas por maquina listas para QuickBooks**")
        st.dataframe(resumen.groupby(["id_maquina", "locacion", "ciudad"]).agg(
            productos=("producto", "count"), unidades=("cantidad", "sum"), ventas=("valor", "sum")
        ).reset_index(), use_container_width=True, hide_index=True)

        previa = vista_previa_impuesto(detalle, gravables, TARIFAS)
        if not previa.empty:
            st.markdown("**Vista previa del impuesto** (estimado para comparar; el oficial lo calcula QuickBooks)")
            st.dataframe(previa, use_container_width=True, hide_index=True)

        st.download_button("Descargar detalle (CSV)", data=detalle.to_csv(index=False).encode("utf-8"),
                           file_name=f"ventas_consolidadas_{anio}-{mes:02d}.csv")

        if st.button("Enviar a QuickBooks", type="primary", disabled=qbo is None):
            with st.spinner("Creando recibos de venta en QuickBooks..."):
                items = productos_qbo(qbo)
                recibos = armar_recibos(resumen, items, anio, mes, id_cliente_ventas(qbo))
                res = enviar_recibos(qbo, recibos)
            st.dataframe(res, use_container_width=True, hide_index=True)
            st.info("En QuickBooks: Taxes > Sales tax muestra el impuesto por agencia para declarar.")

# ---------------- 2. recibos ----------------
with tab_recibos:
    st.subheader("Compras en Walmart, Restaurant Depot y H-E-B")
    st.caption("1) Suba la foto del recibo en QuickBooks (Receipts) o mandela al correo de recibos. "
               "2) Revisela y guardela alla. 3) Aqui se revisan los renglones.")
    desde = st.date_input("Desde", date(anio, mes, 1))
    hasta = st.date_input("Hasta", ultimo_dia(anio, mes))
    if st.button("Revisar recibos", disabled=qbo is None):
        st.session_state["recibos"] = revisar_recibos(qbo, desde, hasta, productos)
    if "recibos" in st.session_state:
        r = st.session_state["recibos"]
        if r.empty:
            st.info("No hay gastos guardados de proveedores minoristas en esas fechas.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Impuesto pagado en compras", dinero(r.loc[r["estado"] == "impuesto", "monto"].sum()))
            c2.metric("Productos con impuesto ya pagado", dinero(r.loc[r["estado"].isin(["alias", "seguro", "producto registrado"]), "monto"].sum()))
            c3.metric("Renglones por revisar", int(r["estado"].isin(["dudoso", "sin_coincidencia"]).sum()))
            st.dataframe(r, use_container_width=True, hide_index=True)
            for _, fila in r[r["estado"].isin(["dudoso", "sin_coincidencia"])].iterrows():
                opciones = ["(no es producto para vender)"] + productos
                idx = opciones.index(fila["producto"]) if fila["producto"] in opciones else 0
                elegido = st.selectbox(f"'{fila['texto_recibo']}' ({dinero(fila['monto'])}) es:", opciones,
                                       index=idx, key=f"rc_{fila['gasto_id']}_{fila['texto_recibo']}")
                if elegido != opciones[0] and st.button("Guardar", key=f"rb_{fila['gasto_id']}_{fila['texto_recibo']}"):
                    guardar_alias(fila["texto_recibo"], elegido)
                    st.success("Guardado para los proximos recibos.")

# ---------------- 3. comisiones ----------------
with tab_comisiones:
    st.subheader(f"Comisiones de {MESES[mes - 1]} {anio}")
    if "detalle" not in st.session_state:
        st.info("Primero una las ventas en la pestaña 1.")
    else:
        com = calcular_comisiones(st.session_state["detalle"])
        if com.empty:
            st.info("Ninguna maquina del vendor list tiene socio asignado.")
        else:
            st.dataframe(com, use_container_width=True, hide_index=True)
            st.metric("Total a pagar en comisiones", dinero(com["comision"].sum()))
            if st.button("Registrar en QuickBooks (factura de proveedor)", disabled=qbo is None):
                st.dataframe(registrar_comisiones(qbo, com, anio, mes), use_container_width=True, hide_index=True)

# ---------------- preparar sandbox ----------------
with tab_preparar:
    st.subheader("Preparar el sandbox (solo la primera vez)")
    if not es_sandbox():
        st.error("Esta pestaña solo funciona en el sandbox (QBO_ENVIRONMENT=sandbox).")
    elif qbo is None:
        st.info("Conecte QuickBooks primero (barra de la izquierda).")
    else:
        st.markdown("**Paso 1 · Quitar los datos de ejemplo de Intuit**")
        if st.button("Ver qué se quitaría (no cambia nada)"):
            with st.spinner("Consultando el sandbox..."):
                st.session_state["plan"] = plan_limpieza(qbo)
        if "plan" in st.session_state:
            st.dataframe(pd.DataFrame(resumen_plan(st.session_state["plan"])), hide_index=True)
            st.warning("Borrar transacciones no se puede deshacer. Clientes, proveedores y productos "
                       "de ejemplo quedan inactivos (QuickBooks no deja borrarlos).")
            confirmacion = st.text_input("Para continuar escriba BORRAR")
            if st.button("Quitar datos de ejemplo", type="primary", disabled=confirmacion.strip() != "BORRAR"):
                barra = st.progress(0.0)
                errores = ejecutar_limpieza(qbo, st.session_state.pop("plan"), barra.progress)
                st.success(f"Listo. {len(errores)} registros no se pudieron quitar (suelen ser del sistema).")
                if errores:
                    with st.expander("Ver detalle"):
                        st.write(errores)
        st.markdown("**Paso 2 · Cargar los datos de EzSnack**")
        if st.button("Cargar productos, proveedores y cuentas de EzSnack", type="primary"):
            with st.spinner("Creando datos en QuickBooks..."):
                try:
                    for linea in cargar_datos(qbo):
                        st.write("✅ " + linea)
                    lista_productos.clear()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

# ---------------- ayuda ----------------
with tab_ayuda:
    st.markdown("""
**Cada mes (entre el 2 y el 15):**
1. Descargue de Nayax, AB360 y el otro lector el reporte de ventas por producto del mes.
2. En la pestaña 1 suba el vendor list y los reportes, y dele *Unir y revisar*.
3. Corrija lo que aparezca en amarillo y dele *Enviar a QuickBooks*.
4. En la pestaña 2 revise los recibos de compras por fuera (Walmart, Restaurant Depot, H-E-B).
5. En la pestaña 3 revise y registre las comisiones.
6. En QuickBooks (Taxes > Sales tax) vea el impuesto por agencia y declarelo en comptroller.texas.gov antes del 20.

El programa no borra nada en QuickBooks. Si un mes ya se envio, no lo duplica.
""")
