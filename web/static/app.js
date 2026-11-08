const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
const $ = (s) => document.querySelector(s);
const dinero = (n) => (n ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const entero = (n) => (n ?? 0).toLocaleString("en-US");
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const estado = { conectado: false, anio: null, mes: null, union: null, ultimaUnion: null, productos: [], enviados: null, compras: null };

/* ---------- utilidades ---------- */
function avisar(texto, error = false) {
  const el = document.createElement("div");
  el.className = "avisito" + (error ? " error" : "");
  el.textContent = texto;
  $("#avisos").append(el);
  setTimeout(() => el.remove(), error ? 7000 : 4500);
}

async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, { credentials: "same-origin", ...opciones });
  let datos = null;
  try { datos = await r.json(); } catch { /* respuesta sin cuerpo */ }
  if (!r.ok) throw new Error(datos?.detail || `El servidor respondió ${r.status}.`);
  return datos;
}
const postJSON = (ruta, cuerpo) => api(ruta, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo ?? {}) });

async function ocupado(boton, fn) {
  boton.setAttribute("aria-busy", "true");
  boton.disabled = true;
  try { return await fn(); }
  catch (e) { avisar(e.message, true); }
  finally { boton.removeAttribute("aria-busy"); boton.disabled = false; refrescarBotones(); }
}

function tabla(el, columnas, filas, pie) {
  const cab = `<thead><tr>${columnas.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.t)}</th>`).join("")}</tr></thead>`;
  const cuerpo = filas.map((f) => `<tr>${columnas.map((c) => `<td class="${c.num ? "num" : ""}">${c.html ? c.html(f) : esc(c.v(f))}</td>`).join("")}</tr>`).join("");
  const p = pie ? `<tfoot><tr>${pie.map((x, i) => `<td class="${columnas[i]?.num ? "num" : ""}">${esc(x)}</td>`).join("")}</tr></tfoot>` : "";
  el.innerHTML = cab + `<tbody>${cuerpo}</tbody>` + p;
}

/* ---------- periodo ---------- */
function ponerPeriodo(anio, mes) {
  estado.anio = anio; estado.mes = mes;
  $("#mes").value = mes; $("#anio").value = anio;
  const sig = new Date(anio, mes, 20);
  $("#titulo-cierre").textContent = `Cierre de ${MESES[mes - 1]} ${anio}`;
  $("#vence").textContent = `La declaración ante el Texas Comptroller vence el 20 de ${MESES[sig.getMonth()]} de ${sig.getFullYear()}.`;
  $("#tq-periodo").textContent = `CIERRE ${String(mes).padStart(2, "0")}/${anio}`;
  const ult = new Date(anio, mes, 0).getDate();
  $("#desde").value = `${anio}-${String(mes).padStart(2, "0")}-01`;
  $("#hasta").value = `${anio}-${String(mes).padStart(2, "0")}-${ult}`;
}

function llenarSelectores(anio) {
  $("#mes").innerHTML = MESES.map((m, i) => `<option value="${i + 1}">${m[0].toUpperCase() + m.slice(1)}</option>`).join("");
  const anios = [anio - 1, anio, anio + 1];
  $("#anio").innerHTML = anios.map((a) => `<option>${a}</option>`).join("");
  const cambio = () => ponerPeriodo(+$("#anio").value, +$("#mes").value);
  $("#mes").addEventListener("change", cambio);
  $("#anio").addEventListener("change", cambio);
}

/* ---------- navegacion ---------- */
function ir(vista) {
  document.querySelectorAll(".vista").forEach((v) => (v.hidden = v.id !== `vista-${vista}`));
  document.querySelectorAll(".paso").forEach((p) => p.toggleAttribute("aria-current", p.dataset.ir === vista));
  document.querySelectorAll(".paso[aria-current]").forEach((p) => p.setAttribute("aria-current", "page"));
  $("#trabajo").focus({ preventScroll: true });
  if (window.matchMedia("(max-width: 760px)").matches) $("#trabajo").scrollIntoView({ behavior: "smooth" });
}
document.querySelectorAll(".paso").forEach((p) => p.addEventListener("click", () => ir(p.dataset.ir)));

/* ---------- conexion ---------- */
function refrescarBotones() {
  const sinConexion = !estado.conectado;
  ["#btn-enviar", "#btn-comisiones", "#btn-plan", "#btn-cargar", "#btn-recibos"].forEach((s) => {
    const b = $(s); if (b && !b.hasAttribute("aria-busy")) b.disabled = sinConexion;
  });
  $("#form-compras button").disabled = sinConexion;
  $("#envio-guia").dataset.sin = sinConexion ? "1" : "";
}

async function cargarEstado() {
  const e = await api("/api/estado");
  estado.conectado = e.conectado;
  if (!estado.anio) { llenarSelectores(e.anio); ponerPeriodo(e.anio, e.mes); }
  const entorno = e.entorno === "sandbox" ? "empresa de prueba" : "empresa real";
  $("#conexion-estado").innerHTML = e.conectado
    ? `Conectado a QuickBooks <strong>${esc(e.empresa)}</strong>${esc(entorno)}`
    : "Sin conexión a QuickBooks. Puede unir ventas igual; para enviarlas, conecte.";
  $("#btn-conectar").hidden = e.conectado;
  $("#btn-salir").hidden = !e.conectado;
  refrescarBotones();
  if (e.conectado) {
    api("/api/productos").then((d) => (estado.productos = d.productos)).catch(() => {});
  }
}

$("#btn-salir").addEventListener("click", async () => {
  await api("/auth/salir", { method: "POST" });
  avisar("Se desconectó de QuickBooks.");
  cargarEstado();
});

/* ---------- 1. ventas ---------- */
document.querySelectorAll(".ranura input").forEach((inp) => inp.addEventListener("change", () => {
  const nombres = [...inp.files].map((f) => f.name);
  inp.closest(".ranura").classList.toggle("lista", nombres.length > 0);
  inp.closest(".ranura").querySelector(".ranura-archivo").textContent = nombres.join(", ");
}));

async function unir(origen) {
  const datos = origen === "ejemplo"
    ? await api("/api/ventas/ejemplo", { method: "POST" })
    : await api("/api/ventas/unir", { method: "POST", body: origen });
  estado.union = datos;
  estado.ultimaUnion = origen;
  estado.enviados = null;
  if (datos.ejemplo) ponerPeriodo(datos.ejemplo.anio, datos.ejemplo.mes);
  if (!estado.productos.length) estado.productos = (await api("/api/productos")).productos;
  pintarVentas();
  pintarComisiones();
  imprimirTiquete();
  document.querySelector('.paso[data-ir="ventas"]').classList.add("hecho");
}

$("#form-ventas").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const hay = ["nayax", "ab360", "otro"].some((k) => fd.getAll(k).some((f) => f.size));
  if (!hay) { avisar("Suba al menos un reporte de ventas de algún lector.", true); return; }
  ocupado($("#btn-unir"), () => unir(fd));
});
$("#btn-ejemplo").addEventListener("click", () => ocupado($("#btn-ejemplo"), () => unir("ejemplo")));

function pintarVentas() {
  const d = estado.union;
  $("#resultado-ventas").hidden = false;
  const m = d.metricas;
  $("#cifras-ventas").innerHTML = `
    <div><dt>Ventas del mes</dt><dd>${dinero(m.ventas)}</dd></div>
    <div><dt>Exentas (agua)</dt><dd>${dinero(m.exentas)}</dd></div>
    <div><dt>Máquinas</dt><dd>${entero(m.maquinas)}</dd></div>
    <div><dt>Líneas unidas</dt><dd>${entero(m.lineas)}</dd></div>
    <div class="${m.por_revisar ? "alerta" : ""}"><dt>Por revisar</dt><dd>${entero(m.por_revisar)}</dd></div>`;

  const lista = $("#lista-problemas");
  $("#problemas").hidden = !d.problemas.length;
  lista.innerHTML = d.problemas.map((p, i) => {
    if (p.tipo === "Maquina no esta en el vendor list") {
      return `<li><strong>${esc(p.texto)}</strong><span class="detalle">Esta máquina no está en la lista de máquinas: ${entero(p.lineas)} ventas por ${dinero(p.valor)} quedan por fuera hasta que la agregue con su dirección.</span></li>`;
    }
    const opciones = estado.productos.map((x) => `<option ${x === p.sugerencia ? "selected" : ""}>${esc(x)}</option>`).join("");
    return `<li><strong>“${esc(p.texto)}” no coincide con un producto registrado</strong>
      <span class="detalle">${entero(p.lineas)} ventas por ${dinero(p.valor)}. Elija a qué producto corresponde y el programa lo recordará.</span>
      <span class="fila"><label class="oculto" for="al-${i}">Producto</label>
      <select id="al-${i}"><option value="">Elegir producto</option>${opciones}</select>
      <button class="boton boton-secundario" data-alias="${i}">Guardar</button></span></li>`;
  }).join("");
  lista.querySelectorAll("[data-alias]").forEach((b) => b.addEventListener("click", () => {
    const p = d.problemas[+b.dataset.alias];
    const producto = $(`#al-${b.dataset.alias}`).value;
    if (!producto) { avisar("Elija un producto antes de guardar.", true); return; }
    ocupado(b, async () => {
      await postJSON("/api/alias", { texto: p.texto, producto });
      avisar(`Guardado: “${p.texto}” es ${producto}.`);
      await unir(estado.ultimaUnion);
    });
  }));

  const filas = d.maquinas;
  tabla($("#tabla-maquinas"), [
    { t: "Máquina", v: (f) => f.id_maquina },
    { t: "Locación", v: (f) => f.locacion },
    { t: "Ciudad", v: (f) => f.ciudad },
    { t: "Unidades", num: true, v: (f) => entero(f.unidades) },
    { t: "Ventas", num: true, v: (f) => dinero(f.ventas) },
  ], filas, ["Total", "", "", entero(filas.reduce((a, f) => a + f.unidades, 0)), dinero(filas.reduce((a, f) => a + f.ventas, 0))]);
  const fuera = d.metricas.ventas - filas.reduce((a, f) => a + f.ventas, 0);
  $("#nota-maquinas").textContent = fuera > 0.005 ? `No incluye ${dinero(fuera)} de ventas que están por revisar.` : "";
  $("#btn-enviar").textContent = `Enviar ${filas.length} recibos`;
  $("#envoltura-enviados").hidden = true;
}

$("#btn-enviar").addEventListener("click", () => ocupado($("#btn-enviar"), async () => {
  const r = await postJSON("/api/ventas/enviar", { anio: estado.anio, mes: estado.mes, resumen: estado.union.resumen });
  estado.enviados = r.recibos;
  $("#envoltura-enviados").hidden = false;
  tabla($("#tabla-enviados"), [
    { t: "Recibo", v: (f) => f.recibo },
    { t: "Resultado", html: (f) => {
      const ok = f.estado === "creado" || f.estado === "ya existia";
      return `<span class="estado ${ok ? "estado-ok" : "estado-error"}">${esc(f.estado === "ya existia" ? "Ya estaba enviado" : f.estado === "creado" ? "Creado" : f.estado)}</span>`;
    } },
    { t: "Total", num: true, v: (f) => (f.total == null ? "" : dinero(f.total)) },
    { t: "Impuesto según QuickBooks", num: true, v: (f) => (f.impuesto == null ? "" : dinero(f.impuesto)) },
  ], r.recibos, ["Total", "", dinero(r.recibos.reduce((a, f) => a + (f.total || 0), 0)), dinero(r.recibos.reduce((a, f) => a + (f.impuesto || 0), 0))]);
  const errores = r.recibos.filter((f) => !["creado", "ya existia"].includes(f.estado)).length;
  avisar(errores ? `${errores} recibos no se pudieron crear. Revise la tabla.` : "Recibos enviados a QuickBooks.", !!errores);
  imprimirTiquete();
}));

/* ---------- 2. compras ---------- */
$("#form-compras").addEventListener("submit", (ev) => {
  ev.preventDefault();
  ocupado(ev.submitter || $("#form-compras button"), async () => {
    const d = await api(`/api/recibos?desde=${$("#desde").value}&hasta=${$("#hasta").value}`);
    estado.compras = d;
    pintarCompras();
    imprimirTiquete();
    document.querySelector('.paso[data-ir="compras"]').classList.add("hecho");
  });
});

function pintarCompras() {
  const d = estado.compras;
  $("#resultado-compras").hidden = false;
  if (!d.renglones.length) {
    $("#cifras-compras").innerHTML = "";
    $("#tabla-compras").innerHTML = `<tbody><tr><td>No hay compras guardadas de Walmart, Restaurant Depot o H-E-B en esas fechas.</td></tr></tbody>`;
    return;
  }
  $("#cifras-compras").innerHTML = `
    <div><dt>Impuesto pagado en compras</dt><dd>${dinero(d.impuesto_pagado)}</dd></div>
    <div><dt>Productos comprados con impuesto</dt><dd>${dinero(d.productos_con_impuesto)}</dd></div>
    <div class="${d.por_revisar ? "alerta" : ""}"><dt>Renglones por revisar</dt><dd>${entero(d.por_revisar)}</dd></div>`;
  const etiqueta = { impuesto: ["Impuesto", "estado-impuesto"], alias: ["Producto", "estado-ok"], seguro: ["Producto", "estado-ok"],
    "producto registrado": ["Producto", "estado-ok"], dudoso: ["Revisar", "estado-revisar"], sin_coincidencia: ["Revisar", "estado-revisar"] };
  tabla($("#tabla-compras"), [
    { t: "Fecha", v: (f) => f.fecha },
    { t: "Tienda", v: (f) => f.proveedor },
    { t: "Texto del recibo", v: (f) => f.texto_recibo },
    { t: "Valor", num: true, v: (f) => dinero(f.monto) },
    { t: "Es", html: (f) => {
      const [t, c] = etiqueta[f.estado] || ["Revisar", "estado-revisar"];
      if (c !== "estado-revisar") return `<span class="estado ${c}">${t}</span>${f.producto ? ` ${esc(f.producto)}` : ""}`;
      const opts = estado.productos.map((x) => `<option ${x === f.producto ? "selected" : ""}>${esc(x)}</option>`).join("");
      return `<span class="fila-compra"><select data-texto="${esc(f.texto_recibo)}" aria-label="Producto para ${esc(f.texto_recibo)}"><option value="">No es para vender</option>${opts}</select>
        <button class="enlace" data-guardar>Guardar</button></span>`;
    } },
  ], d.renglones);
  $("#tabla-compras").querySelectorAll("[data-guardar]").forEach((b) => b.addEventListener("click", () => {
    const sel = b.previousElementSibling;
    if (!sel.value) { avisar("Ese renglón queda como algo que no es para vender."); return; }
    ocupado(b, async () => {
      await postJSON("/api/alias", { texto: sel.dataset.texto, producto: sel.value });
      avisar(`Guardado: “${sel.dataset.texto}” es ${sel.value}.`);
      $("#form-compras").requestSubmit();
    });
  }));
}

/* ---------- 3. comisiones ---------- */
function pintarComisiones() {
  const c = estado.union?.comisiones || [];
  $("#comisiones-vacio").hidden = !!estado.union;
  $("#comisiones-vacio").textContent = estado.union && !c.length ? "Ninguna máquina de la lista tiene socio asignado." : "Primero una las ventas del mes.";
  if (estado.union && !c.length) $("#comisiones-vacio").hidden = false;
  $("#resultado-comisiones").hidden = !c.length;
  if (!c.length) return;
  tabla($("#tabla-comisiones"), [
    { t: "Socio", v: (f) => f.socio },
    { t: "Máquinas", v: (f) => f.maquinas },
    { t: "Ventas", num: true, v: (f) => dinero(f.ventas) },
    { t: "Porcentaje", num: true, v: (f) => `${f.pct_comision}%` },
    { t: "Comisión", num: true, v: (f) => dinero(f.comision) },
  ], c, ["Total", "", "", "", dinero(c.reduce((a, f) => a + f.comision, 0))]);
  $("#envoltura-com-res").hidden = true;
}

$("#btn-comisiones").addEventListener("click", () => ocupado($("#btn-comisiones"), async () => {
  const r = await postJSON("/api/comisiones/registrar", { anio: estado.anio, mes: estado.mes, comisiones: estado.union.comisiones });
  $("#envoltura-com-res").hidden = false;
  tabla($("#tabla-com-res"), [
    { t: "Socio", v: (f) => f.socio },
    { t: "Resultado", html: (f) => `<span class="estado estado-ok">${f.estado === "ya existia" ? "Ya estaba registrada" : "Registrada"}</span>` },
    { t: "Valor", num: true, v: (f) => dinero(f.valor) },
  ], r.resultado);
  avisar("Comisiones registradas en QuickBooks.");
  document.querySelector('.paso[data-ir="comisiones"]').classList.add("hecho");
}));

/* ---------- tiquete ---------- */
function imprimirTiquete() {
  const d = estado.union;
  if (!d) return;
  const L = [];
  const linea = (a, b = "", cls = "") => L.push(`<div class="tq-linea ${cls}"><span>${esc(a)}</span><span>${esc(b)}</span></div>`);
  const espacio = () => L.push(`<div class="tq-espacio"></div>`);
  linea("Ventas totales", dinero(d.metricas.ventas));
  linea("Exentas (agua)", "-" + dinero(d.metricas.exentas), "tq-sub");
  d.sistemas.forEach((s) => linea(`${s.sistema}`, dinero(s.ventas), "tq-sub"));
  espacio();
  let estimado = 0;
  d.previa.forEach((p) => { linea(`Gravable ${p.jurisdiccion}`, dinero(p.ventas_gravables)); estimado += p.impuesto_estimado; });
  linea("Impuesto estimado", dinero(estimado), "tq-sub");
  if (estado.enviados) {
    const oficial = estado.enviados.reduce((a, f) => a + (f.impuesto || 0), 0);
    linea("Impuesto QuickBooks", dinero(oficial), "tq-oficial");
  }
  if (estado.compras && estado.compras.impuesto_pagado) linea("Pagado en compras", "-" + dinero(estado.compras.impuesto_pagado), "tq-sub");
  const c = d.comisiones || [];
  if (c.length) { espacio(); linea("Comisiones socios", dinero(c.reduce((a, f) => a + f.comision, 0))); }
  const base = estado.enviados ? estado.enviados.reduce((a, f) => a + (f.impuesto || 0), 0) : estimado;
  const neto = base - (estado.compras?.impuesto_pagado || 0);
  linea(estado.enviados ? "A declarar" : "A declarar (estimado)", dinero(neto), "tq-total");
  const cuerpo = $("#tq-cuerpo");
  cuerpo.innerHTML = L.map((h, i) => h.replace("<div ", `<div style="--i:${i}" `)).join("");
  cuerpo.classList.remove("imprimiendo"); void cuerpo.offsetWidth; cuerpo.classList.add("imprimiendo");
}

/* ---------- sandbox ---------- */
async function seguir(tid, barra, nota) {
  barra.hidden = false;
  for (;;) {
    const t = await api(`/api/trabajos/${tid}`);
    barra.firstElementChild.style.width = `${Math.round((t.progreso || 0) * 100)}%`;
    if (t.estado !== "corriendo") {
      if (t.estado === "error") throw new Error(t.resultado);
      return t.resultado;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

$("#btn-plan").addEventListener("click", () => ocupado($("#btn-plan"), async () => {
  const r = await api("/api/preparar/plan", { method: "POST" });
  $("#plan").hidden = false;
  tabla($("#tabla-plan"), [
    { t: "Acción", v: (f) => f.accion },
    { t: "Qué", v: (f) => ({ Payment: "Pagos de clientes", BillPayment: "Pagos a proveedores", Deposit: "Depósitos", RefundReceipt: "Reembolsos", SalesReceipt: "Recibos de venta", CreditMemo: "Notas crédito", Invoice: "Facturas", Estimate: "Cotizaciones", Purchase: "Gastos", Bill: "Facturas de proveedor", PurchaseOrder: "Órdenes de compra", JournalEntry: "Asientos", TimeActivity: "Registros de tiempo", VendorCredit: "Créditos de proveedor", Transfer: "Transferencias", Customer: "Clientes", Vendor: "Proveedores", Item: "Productos" }[f.tipo] || f.tipo) },
    { t: "Cantidad", num: true, v: (f) => entero(f.cantidad) },
  ], r.plan);
  if (!r.plan.length) avisar("No quedan datos de ejemplo por quitar.");
}));
$("#confirmacion").addEventListener("input", (e) => ($("#btn-limpiar").disabled = e.target.value.trim() !== "BORRAR"));
$("#btn-limpiar").addEventListener("click", () => ocupado($("#btn-limpiar"), async () => {
  const { trabajo } = await postJSON("/api/preparar/limpiar", { confirmacion: $("#confirmacion").value });
  $("#plan").hidden = true;
  const errores = await seguir(trabajo, $("#prog-limpiar"), $("#res-limpiar"));
  $("#res-limpiar").textContent = errores.length
    ? `Listo. ${errores.length} registros quedaron porque QuickBooks no deja quitarlos (suelen ser del sistema o tener saldos).`
    : "Listo. Se quitaron todos los datos de ejemplo.";
  $("#confirmacion").value = "";
}));
$("#btn-cargar").addEventListener("click", () => ocupado($("#btn-cargar"), async () => {
  const { trabajo } = await api("/api/preparar/cargar", { method: "POST" });
  $("#res-cargar").textContent = (await seguir(trabajo, $("#prog-cargar"))).join("\n");
  estado.productos = (await api("/api/productos")).productos;
}));
$("#btn-recibos").addEventListener("click", () => ocupado($("#btn-recibos"), async () => {
  const { trabajo } = await api("/api/preparar/recibos-prueba", { method: "POST" });
  $("#res-recibos").textContent = (await seguir(trabajo, $("#prog-recibos"))).join("\n");
}));

/* ---------- inicio ---------- */
const p = new URLSearchParams(location.search);
if (p.get("conexion") === "ok") avisar("Conectado a QuickBooks.");
if (p.get("conexion") === "cancelada") avisar("La conexión con QuickBooks se canceló.", true);
if (p.get("conexion") === "invalida") avisar("La conexión venció. Inténtelo de nuevo.", true);
if (p.has("conexion")) history.replaceState(null, "", "/");
cargarEstado().catch((e) => avisar(e.message, true));
