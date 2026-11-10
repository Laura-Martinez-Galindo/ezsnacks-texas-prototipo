const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const dinero = (n) => (n ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const entero = (n) => (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
const dolares = (n) => "$" + entero(n);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const estado = {
  anio: null, mes: null, reglas: null, qbo: false, conectado: false,
  codigo: null, ejemplo: false, form: null, res: null,
  ajustes: { exentos: null, pagados: null, comisiones: null },
};

/* ---------- utilidades ---------- */
function avisar(texto, error = false) {
  const el = document.createElement("div");
  el.className = "avisito" + (error ? " error" : "");
  el.textContent = texto;
  $("#avisos").append(el);
  setTimeout(() => el.remove(), error ? 8000 : 4000);
}

async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, { credentials: "same-origin", ...opciones });
  if (r.headers.get("content-type")?.includes("spreadsheet")) {
    if (!r.ok) throw new Error(`El servidor respondió ${r.status}.`);
    return r;
  }
  let datos = null;
  try { datos = await r.json(); } catch { /* sin cuerpo */ }
  if (!r.ok) { const e = new Error(datos?.detail || `El servidor respondió ${r.status}.`); e.status = r.status; throw e; }
  return datos;
}
const postJSON = (ruta, cuerpo) => api(ruta, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo ?? {}) });

async function ocupado(boton, fn) {
  boton.setAttribute("aria-busy", "true");
  boton.disabled = true;
  try { return await fn(); }
  catch (e) { avisar(e.message, true); }
  finally { boton.removeAttribute("aria-busy"); boton.disabled = false; }
}

function tabla(el, columnas, filas, pie) {
  const cab = `<thead><tr>${columnas.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.t)}</th>`).join("")}</tr></thead>`;
  const cuerpo = filas.map((f) => `<tr class="${f._clase || ""}">${columnas.map((c) => `<td class="${c.num ? "num" : ""}">${c.html ? c.html(f) : esc(c.v(f))}</td>`).join("")}</tr>`).join("");
  const p = pie ? `<tfoot><tr>${pie.map((x, i) => `<td class="${columnas[i]?.num ? "num" : ""}">${esc(x)}</td>`).join("")}</tr></tfoot>` : "";
  el.innerHTML = cab + `<tbody>${cuerpo}</tbody>` + p;
}
const copiable = (valor, texto) => `<button class="copiar" data-copiar="${esc(valor)}" title="Copiar ${esc(valor)}">${esc(texto)}</button>`;

/* ---------- periodo ---------- */
function ponerPeriodo(anio, mes) {
  estado.anio = anio; estado.mes = mes;
  $("#mes").value = mes; $("#anio").value = anio;
  const sig = new Date(anio, mes, 20);
  $("#titulo-cierre").textContent = `Cierre de ${MESES[mes - 1]} ${anio}`;
  $("#vence").textContent = `La declaración ante el Texas Comptroller vence el 20 de ${MESES[sig.getMonth()]} de ${sig.getFullYear()}.`;
  $("#tq-periodo").textContent = `CIERRE ${String(mes).padStart(2, "0")}/${anio}`;
}
function llenarSelectores(anio) {
  $("#mes").innerHTML = MESES.map((m, i) => `<option value="${i + 1}">${m[0].toUpperCase() + m.slice(1)}</option>`).join("");
  $("#anio").innerHTML = [anio - 1, anio, anio + 1].map((a) => `<option>${a}</option>`).join("");
  const cambio = () => { ponerPeriodo(+$("#anio").value, +$("#mes").value); if (estado.codigo) recalcular(); };
  $("#mes").addEventListener("change", cambio);
  $("#anio").addEventListener("change", cambio);
}

/* ---------- navegacion ---------- */
function ir(vista) {
  $$(".vista").forEach((v) => (v.hidden = v.id !== `vista-${vista}`));
  $$(".paso").forEach((p) => (p.dataset.ir === vista ? p.setAttribute("aria-current", "page") : p.removeAttribute("aria-current")));
  $("#trabajo").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-ir]");
  if (b && !b.disabled) ir(b.dataset.ir);
  const c = ev.target.closest("[data-copiar]");
  if (c) navigator.clipboard?.writeText(c.dataset.copiar).then(() => avisar(`Copiado: ${c.dataset.copiar}`), () => {});
});

/* ---------- conexion con QuickBooks ---------- */
async function cargarEstado() {
  const e = await api("/api/estado");
  estado.reglas = e.reglas;
  estado.qbo = e.qbo_disponible;
  estado.conectado = e.conectado;
  if (!estado.anio) { llenarSelectores(e.anio); ponerPeriodo(e.anio, e.mes); }
  $("#conexion").hidden = !e.qbo_disponible;
  const entorno = e.entorno === "sandbox" ? "empresa de prueba" : "empresa real";
  $("#conexion-estado").innerHTML = e.conectado
    ? `Conectado a QuickBooks <strong>${esc(e.empresa)}</strong>${esc(entorno)}`
    : "QuickBooks es opcional: sirve para dejar registrado el impuesto por pagar y las comisiones.";
  $("#btn-conectar").hidden = e.conectado;
  $("#btn-salir").hidden = !e.conectado;
  $("#bloque-qbo").hidden = !e.qbo_disponible;
  $("#btn-registrar").disabled = !e.conectado;
  $("#guia-qbo").dataset.sin = e.conectado ? "" : "1";
}
$("#btn-salir").addEventListener("click", async () => {
  await api("/auth/salir", { method: "POST" });
  avisar("Se desconectó de QuickBooks.");
  cargarEstado();
});

/* ---------- 1. archivos ---------- */
$$(".ranura input").forEach((inp) => inp.addEventListener("change", () => {
  const nombres = [...inp.files].map((f) => f.name);
  inp.closest(".ranura").classList.toggle("lista", nombres.length > 0);
  inp.closest(".ranura").querySelector(".ranura-archivo").textContent = nombres.join(", ");
}));

function ajustes() {
  return {
    devoluciones_pct: +$("#aj-devoluciones").value || 0,
    equipos_efectivo: +$("#aj-eq-efectivo").value || 0,
    equipos_tarjeta: +$("#aj-eq-tarjeta").value || 0,
    incluir_prepago: $("#aj-prepago").checked,
    a_tiempo: $("#aj-tiempo").checked,
    exentos: estado.ajustes.exentos,
    pagados: estado.ajustes.pagados,
    comisiones: estado.ajustes.comisiones,
  };
}

async function subir(form) {
  const fd = new FormData();
  fd.append("maquinas", form.get("maquinas"));
  form.getAll("reportes").forEach((f) => f.size && fd.append("reportes", f));
  const pag = form.get("pagados");
  if (pag && pag.size) fd.append("pagados", pag);
  return api(`/api/cierre/archivos?anio=${estado.anio}&mes=${estado.mes}`, { method: "POST", body: fd });
}

async function empezar(origen) {
  estado.ajustes = { exentos: null, pagados: null, comisiones: null };
  let d;
  if (origen === "ejemplo") {
    d = await api("/api/cierre/ejemplo", { method: "POST" });
    estado.form = null; estado.ejemplo = true;
    ponerPeriodo(d.anio, d.mes);
  } else {
    d = await subir(origen);
    estado.form = origen; estado.ejemplo = false;
  }
  estado.codigo = d.codigo;
  if (d.errores?.length) d.errores.forEach((e) => avisar(e, true));
  const aj = ajustes();
  if (aj.devoluciones_pct !== 3 || aj.equipos_efectivo || aj.equipos_tarjeta || aj.incluir_prepago || !aj.a_tiempo) {
    d = await postJSON(`/api/cierre/${estado.codigo}/calcular`, { anio: estado.anio, mes: estado.mes, ajustes: ajustes() });
  }
  mostrar(d);
  $$(".paso").forEach((p) => (p.disabled = false));
  avisar(`Se leyeron ${d.archivos.length} reportes y ${entero(d.maquinas.length)} máquinas con ventas.`);
}

$("#form-archivos").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  if (!fd.get("maquinas")?.size) { avisar("Elija la lista de máquinas (vendor list).", true); return; }
  if (!fd.getAll("reportes").some((f) => f.size)) { avisar("Elija al menos un reporte de ventas.", true); return; }
  ocupado($("#btn-calcular"), () => empezar(fd));
});
$("#btn-ejemplo").addEventListener("click", () => ocupado($("#btn-ejemplo"), () => empezar("ejemplo")));

let espera = null;
function recalcular() {
  clearTimeout(espera);
  espera = setTimeout(async () => {
    if (!estado.codigo) return;
    try {
      const d = await postJSON(`/api/cierre/${estado.codigo}/calcular`, { anio: estado.anio, mes: estado.mes, ajustes: ajustes() });
      mostrar(d);
    } catch (e) {
      if (e.status === 410) { await volverASubir(); return; }
      avisar(e.message, true);
    }
  }, 250);
}
async function volverASubir() {
  // El servidor se reinició o pasó mucho tiempo: se vuelven a subir los mismos archivos
  const a = estado.ajustes;
  if (estado.ejemplo) await empezar("ejemplo");
  else if (estado.form) await empezar(estado.form);
  else return;
  estado.ajustes = a;
  recalcular();
}
["#aj-devoluciones", "#aj-eq-efectivo", "#aj-eq-tarjeta", "#aj-prepago", "#aj-tiempo"].forEach((s) => $(s).addEventListener("change", recalcular));

function mostrar(d) {
  estado.res = d;
  pintarArchivos(d);
  pintarProductos(d);
  pintarDeclaracion(d);
  pintarComisiones(d);
  imprimirTiquete(d);
}

const DESCARTE = { "filas de total o vacias": "sin producto o de total", "transacciones rechazadas (valor 0)": "rechazadas" };
function pintarArchivos(d) {
  $("#res-archivos").hidden = false;
  const p = d.pasos;
  $("#cifras-archivos").innerHTML = `
    <div><dt>Ventas del mes</dt><dd>${dinero(p.total)}</dd></div>
    <div><dt>En efectivo</dt><dd>${dinero(p.efectivo)}</dd></div>
    <div><dt>Con tarjeta</dt><dd>${dinero(p.tarjeta)}</dd></div>
    <div><dt>Máquinas con ventas</dt><dd>${entero(d.maquinas.length)}</dd></div>
    <div class="${d.revisar.length ? "alerta" : ""}"><dt>Para revisar</dt><dd>${entero(d.revisar.length)}</dd></div>`;
  $("#revisar").hidden = !d.revisar.length;
  $("#lista-revisar").innerHTML = d.revisar.map((r) => `<li><strong>${esc(r.texto)}</strong><span class="detalle">${esc(r.detalle)}</span></li>`).join("");

  const A = d.archivos;
  const suma = (k) => A.reduce((a, f) => a + f[k], 0);
  tabla($("#tabla-archivos"), [
    { t: "Archivo", html: (f) => `<span class="archivo">${esc(f.archivo)}</span>${f.periodo ? `<span class="sub">${esc(f.periodo)}</span>` : ""}` },
    { t: "Lector", v: (f) => f.fuente },
    { t: "Filas usadas", num: true, html: (f) => {
      const fuera = Object.entries(f.descartadas).filter(([, v]) => v).map(([k, v]) => `${entero(v)} ${DESCARTE[k] || k}`).join(", ");
      return `${entero(f.usadas)}${fuera ? `<span class="sub">${esc(fuera)}</span>` : ""}`;
    } },
    { t: "Efectivo", num: true, v: (f) => dinero(f.efectivo) },
    { t: "Tarjeta", num: true, v: (f) => dinero(f.tarjeta) },
    { t: "Cupones", num: true, v: (f) => (f.cupones ? dinero(f.cupones) : "") },
    { t: "Prepago", num: true, v: (f) => (f.prepago ? dinero(f.prepago) : "") },
  ], A, ["Total", "", entero(suma("usadas")), dinero(suma("efectivo")), dinero(suma("tarjeta")), dinero(suma("cupones")), dinero(suma("prepago"))]);
  pintarMaquinas();
}

function pintarMaquinas() {
  const d = estado.res; if (!d) return;
  const q = $("#buscar-maquina").value.trim().toLowerCase();
  const filas = d.maquinas.filter((m) => !q || `${m.id_maquina} ${m.maquina} ${m.ciudad} ${m.locacion}`.toLowerCase().includes(q))
    .map((m) => ({ ...m, _clase: m.en_lista ? "" : "fila-alerta" }));
  tabla($("#tabla-maquinas"), [
    { t: "Máquina", html: (f) => `<strong>${esc(f.id_maquina || "?")}</strong><span class="sub">${esc(f.locacion || f.maquina)}</span>` },
    { t: "Lector", v: (f) => f.fuente },
    { t: "Ciudad", html: (f) => (f.en_lista ? esc(f.ciudad || "Sin ciudad") : `<span class="estado estado-revisar">No está en la lista</span>`) },
    { t: "Impuesto local", v: (f) => f.jurisdiccion || "Solo estado" },
    { t: "Ventas", num: true, v: (f) => dinero(f.ventas) },
    { t: "Gravable", num: true, v: (f) => dinero(f.gravable) },
  ], filas, ["Total", "", "", `${filas.length} máquinas`, dinero(filas.reduce((a, f) => a + f.ventas, 0)), dinero(filas.reduce((a, f) => a + f.gravable, 0))]);
}
$("#buscar-maquina").addEventListener("input", pintarMaquinas);

/* ---------- 2. productos ---------- */
function pintarProductos(d) {
  $("#lista-productos").innerHTML = d.productos.map((p) => `<option value="${esc(p)}">`).join("");
  const exentos = d.exentos;
  tabla($("#tabla-exentos"), [
    { t: "Exento", html: (f) => `<input type="checkbox" data-exento="${esc(f.producto)}" ${f.marcado ? "checked" : ""} aria-label="Exento: ${esc(f.producto)}">` },
    { t: "Producto", v: (f) => f.producto },
    { t: "Unidades", num: true, v: (f) => entero(f.cantidad) },
    { t: "Ventas", num: true, v: (f) => dinero(f.ventas) },
  ], exentos, ["", "Total exento", "", dinero(exentos.filter((f) => f.marcado).reduce((a, f) => a + f.ventas, 0))]);
  if (!exentos.length) $("#tabla-exentos").innerHTML = `<tbody><tr><td>No se encontró agua entre los productos vendidos.</td></tr></tbody>`;

  const P = d.pagados;
  $("#guia-pagados").textContent = d.lista_pagados.length
    ? `Su lista tiene ${d.lista_pagados.length} productos: ${d.lista_pagados.join(", ")}. Cada uno se busca entre lo vendido; si dice el tamaño, solo se marcan los de ese tamaño.`
    : "No se subió la lista de compras con impuesto pagado. Puede agregar productos aquí abajo o volver al primer paso y subir el Excel con la columna Product.";
  const etiqueta = { seguro: "", dudoso: `<span class="estado estado-revisar">Revisar tamaño</span>`, sin_ventas: `<span class="estado estado-revisar">Sin ventas este mes</span>`, manual: `<span class="estado estado-impuesto">Agregado aquí</span>` };
  const extra = (estado.ajustes.pagados || []).filter((p) => !P.some((f) => f.producto === p)).map((p) => ({ buscado: "", producto: p, ventas: null, estado: "manual", marcado: true }));
  const filas = [...P, ...extra];
  tabla($("#tabla-pagados"), [
    { t: "Descontar", html: (f) => (f.producto ? `<input type="checkbox" data-pagado="${esc(f.producto)}" ${f.marcado ? "checked" : ""} ${f.exento ? "disabled" : ""} aria-label="Comprado con impuesto: ${esc(f.producto)}">` : "") },
    { t: "En su lista", v: (f) => f.buscado },
    { t: "Producto vendido", html: (f) => `${esc(f.producto || "")} ${etiqueta[f.estado] || ""}${f.exento ? `<span class="sub">Ya cuenta como exento, no se descuenta dos veces</span>` : ""}` },
    { t: "Ventas", num: true, v: (f) => (f.ventas == null ? "" : dinero(f.ventas)) },
  ], filas, ["", "", "Total a descontar", dinero(d.pasos.pagadas)]);
  if (!filas.length) $("#tabla-pagados").innerHTML = `<tbody><tr><td>Todavía no hay productos marcados.</td></tr></tbody>`;
}

function marcados(sel, attr) { return $$(sel).filter((c) => c.checked).map((c) => c.dataset[attr]); }
document.addEventListener("change", (ev) => {
  if (ev.target.matches("[data-exento]")) {
    const fuera = estado.res.exentos.map((f) => f.producto).filter((p) => !$$("[data-exento]").some((c) => c.dataset.exento === p));
    estado.ajustes.exentos = [...marcados("[data-exento]", "exento"), ...(estado.ajustes.exentos || []).filter((p) => fuera.includes(p))];
    recalcular();
  }
  if (ev.target.matches("[data-pagado]")) {
    estado.ajustes.pagados = marcados("[data-pagado]", "pagado");
    recalcular();
  }
});
function agregar(input, clave) {
  const nombre = input.value.trim();
  if (!estado.res.productos.includes(nombre)) { avisar("Elija un producto de la lista de productos vendidos.", true); return; }
  if (clave === "exentos") {
    const actuales = estado.ajustes.exentos ?? estado.res.exentos.filter((f) => f.marcado).map((f) => f.producto);
    estado.ajustes.exentos = [...new Set([...actuales, nombre])];
  } else {
    const actuales = estado.ajustes.pagados ?? estado.res.pagados.filter((f) => f.marcado).map((f) => f.producto);
    estado.ajustes.pagados = [...new Set([...actuales, nombre])];
  }
  input.value = "";
  recalcular();
}
$("#btn-otro-exento").addEventListener("click", () => agregar($("#otro-exento"), "exentos"));
$("#btn-otro-pagado").addEventListener("click", () => agregar($("#otro-pagado"), "pagados"));

/* ---------- 3. declaracion ---------- */
function pintarDeclaracion(d) {
  const p = d.pasos, c = d.declaracion;
  const filas = [
    { c: "Ventas en efectivo", v: p.efectivo },
    { c: "Ventas con tarjeta", v: p.tarjeta },
    ...(p.equipos ? [{ c: "Venta de máquinas", v: p.equipos }] : []),
    { c: "Ventas totales", v: p.total, _clase: "fila-fuerte" },
    { c: `Devoluciones a clientes (${p.devoluciones_pct} %)`, v: -p.devoluciones },
    { c: "Ventas netas", v: p.neto, _clase: "fila-fuerte" },
    { c: "Agua y otros exentos", v: -p.exentas },
    { c: "Productos comprados con impuesto pagado", v: -p.pagadas, n: p.pagadas ? `en la compra se pagaron cerca de ${dinero(p.impuesto_ya_pagado)} de impuesto` : "" },
    { c: "Ventas gravables", v: p.gravable, _clase: "fila-fuerte" },
  ];
  tabla($("#tabla-cascada"), [
    { t: "Concepto", html: (f) => `${esc(f.c)}${f.n ? `<span class="sub">${esc(f.n)}</span>` : ""}` },
    { t: "Valor", num: true, v: (f) => (f.v < 0 ? `−${dinero(-f.v)}` : dinero(f.v)) },
  ], filas);

  tabla($("#tabla-ubicacion"), [{ t: "Campo del formulario", v: (f) => f.c }, { t: "Valor", num: true, html: (f) => f.h }], [
    { c: "Total Texas Sales", h: copiable(c.total_ventas, entero(c.total_ventas)) },
    { c: "Taxable Sales", h: copiable(c.ventas_gravables, entero(c.ventas_gravables)) },
    { c: "Taxable Purchases", h: copiable(0, "0") },
    { c: "Subject to State Tax (Rate .0625)", h: esc(entero(c.sujeto_estado)) },
    { c: "State Tax Due", h: esc(dinero(c.impuesto_estado)), _clase: "fila-fuerte" },
  ]);

  tabla($("#tabla-lista"), [
    { t: "Jurisdiction", html: (f) => `${esc(f.codigo)}<span class="sub">${esc(f.nombre_comptroller)}</span>` },
    { t: "Máquinas", num: true, v: (f) => entero(f.maquinas) },
    { t: "Amount Subject to Local Tax", num: true, html: (f) => copiable(f.base, entero(f.base)) },
    { t: "Rate", num: true, v: (f) => (f.tasa / 100).toFixed(5) },
    { t: "Local Tax Due", num: true, v: (f) => dinero(f.impuesto) },
  ], c.locales, ["Total Tax for List", "", "", "", dinero(c.impuesto_local)]);
  const ciudades = Object.entries(estado.reglas?.jurisdicciones || {}).map(([k, v]) => `${k}: ${v.ciudades.join(", ")}`).join(". ");
  $("#nota-lista").textContent = `Cada máquina va a la jurisdicción de la ciudad que tiene en el vendor list (${ciudades}). A cada base se le aplican las mismas devoluciones, exentos y productos ya pagados que al total.`;

  tabla($("#tabla-total"), [{ t: "Concepto", v: (f) => f.c }, { t: "Valor", num: true, v: (f) => f.v }], [
    { c: "Total Tax Due", v: dinero(c.impuesto_total) },
    { c: "Timely Filing Discount", v: c.descuento ? `−${dinero(c.descuento)}` : dinero(0) },
    { c: "Total Amount Due and Payable", v: dinero(c.a_pagar), _clase: "fila-fuerte" },
    { c: `Vence`, v: new Date(c.vence + "T12:00").toLocaleDateString("es", { day: "numeric", month: "long", year: "numeric" }) },
  ]);
  pintarVerificacion(d);
}

function pintarVerificacion(d) {
  const v = d.verificacion;
  $("#verificacion").hidden = !v;
  if (!v) return;
  const p = d.pasos, c = d.declaracion, ex = v.excel, co = v.comptroller;
  const hou = c.locales.find((l) => l.codigo === "2101017"), mta = c.locales.find((l) => l.codigo === "3101990");
  $("#verif-guia").textContent = "Mismos archivos de septiembre que entregó el gerente. Se compara con el Excel que él armó con ChatGPT y con lo que pagó en el Comptroller el 13 de octubre.";
  const fila = (concepto, prog, excel, comp) => ({ concepto, prog, excel, comp, dif: excel == null ? null : prog - excel });
  const filas = [
    fila("Ventas en efectivo y tarjeta", p.efectivo + p.tarjeta - p.equipos, ex.total, null),
    fila("Ventas netas (menos 3 %)", p.neto, ex.neto, co.total_ventas),
    fila("Agua y exentos", p.exentas, ex.exentas, null),
    fila("Productos con impuesto pagado", p.pagadas, ex.pagadas, null),
    fila("Ventas gravables", p.gravable, ex.gravable, co.ventas_gravables),
    fila("Ventas de las máquinas de Houston", hou?.ventas ?? 0, ex.houston_bruto, null),
    fila("Base Houston", hou?.base ?? 0, ex.houston, co.houston),
    fila("Ventas de las máquinas de Bellaire, Katy y Spring", mta?.ventas ?? 0, ex.mta_bruto, null),
    fila("Base Houston MTA", mta?.base ?? 0, null, co.mta),
    fila("Impuesto total", c.impuesto_total, null, co.impuesto_total),
  ];
  tabla($("#tabla-verif"), [
    { t: "Concepto", v: (f) => f.concepto },
    { t: "Este programa", num: true, v: (f) => dinero(f.prog) },
    { t: "Excel", num: true, v: (f) => (f.excel == null ? "" : dinero(f.excel)) },
    { t: "Diferencia", num: true, html: (f) => (f.dif == null ? "" : `<span class="${Math.abs(f.dif) < 0.01 ? "igual" : "distinto"}">${Math.abs(f.dif) < 0.01 ? "igual" : (f.dif > 0 ? "+" : "−") + dinero(Math.abs(f.dif))}</span>`) },
    { t: "Comptroller", num: true, v: (f) => (f.comp == null ? "" : dinero(f.comp)) },
  ], filas);
}

/* ---------- 4. comisiones ---------- */
function pintarComisiones(d) {
  const reglas = estado.ajustes.comisiones || estado.reglas.comisiones;
  const det = d.comisiones.detalle;
  $("#lista-socios").innerHTML = d.comisiones.socios.map((s, i) => {
    const r = reglas[i];
    const filas = det.filter((f) => f.socio === s.socio);
    const tablaDet = filas.length ? `<div class="tabla-envoltura"><table class="tabla"><thead><tr><th>Máquina</th><th class="num">Ventas</th><th class="num">Descuentos</th><th class="num">Base</th><th class="num">Comisión</th></tr></thead><tbody>${
      filas.map((f) => `<tr class="${f.aplica ? "" : "fila-tenue"}"><td><strong>${esc(f.id_maquina)}</strong><span class="sub">${esc(f.maquina)}</span></td><td class="num">${dinero(f.ventas)}</td><td class="num">${f.descuento_tarjeta + f.costo_lector ? "−" + dinero(f.descuento_tarjeta + f.costo_lector) : ""}</td><td class="num">${dinero(f.base)}</td><td class="num">${f.aplica ? dinero(f.comision) : "No aplica"}</td></tr>`).join("")
    }</tbody></table></div>` : `<p class="vacio">Ninguna máquina con ventas este mes.</p>`;
    return `<article class="socio">
      <header class="socio-cabeza">
        <div><h3>${esc(s.socio)}</h3><p class="guia">${esc(s.regla)}</p></div>
        <p class="socio-total">${s.por_confirmar ? `<span class="estado estado-revisar">Regla por confirmar</span>` : dinero(s.comision)}<span class="sub">${s.con_comision} de ${s.maquinas} máquinas · ventas ${dinero(s.ventas)}</span></p>
      </header>
      <div class="regla" data-socio="${i}">
        <label>Porcentaje<span class="campo-unidad"><input type="number" step="0.1" min="0" data-campo="porcentaje" value="${r.porcentaje ?? ""}" placeholder="?"><span>%</span></span></label>
        <label>Mínimo por máquina<span class="campo-unidad"><span>$</span><input type="number" step="1" min="0" data-campo="minimo_por_maquina" value="${r.minimo_por_maquina}"></span></label>
        <label>Descuento por tarjeta<span class="campo-unidad"><input type="number" step="0.01" min="0" data-campo="descuento_tarjeta_pct" value="${r.descuento_tarjeta_pct}"><span>%</span></span></label>
        <label>Lector al mes<span class="campo-unidad"><span>$</span><input type="number" step="0.01" min="0" data-campo="costo_lector_mes" value="${r.costo_lector_mes}"></span></label>
      </div>
      ${filas.length ? `<details><summary>Ver las ${filas.length} máquinas</summary>${tablaDet}</details>` : `<p class="vacio">Ninguna máquina de este socio tuvo ventas este mes.</p>`}
    </article>`;
  }).join("");
}
document.addEventListener("change", (ev) => {
  const inp = ev.target.closest(".regla input");
  if (!inp) return;
  const i = +inp.closest(".regla").dataset.socio;
  const reglas = structuredClone(estado.ajustes.comisiones || estado.reglas.comisiones);
  reglas[i][inp.dataset.campo] = inp.value === "" ? (inp.dataset.campo === "porcentaje" ? null : 0) : +inp.value;
  estado.ajustes.comisiones = reglas;
  recalcular();
});

/* ---------- 5. guardar ---------- */
$("#btn-libro").addEventListener("click", () => ocupado($("#btn-libro"), async () => {
  let r;
  try { r = await api(`/api/cierre/${estado.codigo}/libro`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ anio: estado.anio, mes: estado.mes, ajustes: ajustes() }) }); }
  catch (e) { if (e.status === 410) { await volverASubir(); throw new Error("Se volvieron a leer los archivos. Intente de nuevo."); } throw e; }
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `Cierre_impuestos_EzSnack_${estado.anio}-${String(estado.mes).padStart(2, "0")}.xlsx`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}));

$("#btn-registrar").addEventListener("click", () => ocupado($("#btn-registrar"), async () => {
  const r = await postJSON(`/api/cierre/${estado.codigo}/registrar`, { anio: estado.anio, mes: estado.mes, ajustes: ajustes() });
  $("#envoltura-registros").hidden = false;
  tabla($("#tabla-registros"), [
    { t: "Qué", v: (f) => f.concepto },
    { t: "A nombre de", v: (f) => f.a_nombre_de },
    { t: "Documento", v: (f) => f.documento },
    { t: "Resultado", html: (f) => `<span class="estado estado-ok">${f.estado === "ya existia" ? "Ya estaba registrado" : "Creado"}</span>` },
    { t: "Valor", num: true, v: (f) => dinero(f.valor) },
  ], r.registros);
  avisar("Cierre registrado en QuickBooks.");
}));

/* ---------- tiquete ---------- */
function imprimirTiquete(d) {
  const p = d.pasos, c = d.declaracion;
  const L = [];
  const linea = (a, b = "", cls = "") => L.push(`<div class="tq-linea ${cls}"><span>${esc(a)}</span><span>${esc(b)}</span></div>`);
  const espacio = () => L.push(`<div class="tq-espacio"></div>`);
  linea("Ventas totales", dinero(p.total));
  linea(`Devoluciones ${p.devoluciones_pct}%`, "-" + dinero(p.devoluciones), "tq-sub");
  linea("Exentas (agua)", "-" + dinero(p.exentas), "tq-sub");
  linea("Ya pagadas", "-" + dinero(p.pagadas), "tq-sub");
  linea("Gravables", dinero(p.gravable));
  espacio();
  linea("Estado 6.25%", dinero(c.impuesto_estado));
  c.locales.forEach((l) => linea(`${l.nombre_comptroller} ${l.tasa}%`, dinero(l.impuesto), "tq-sub"));
  if (c.descuento) linea("Pago a tiempo", "-" + dinero(c.descuento), "tq-sub");
  linea("A pagar", dinero(c.a_pagar), "tq-total");
  const com = d.comisiones.socios.reduce((a, s) => a + s.comision, 0);
  if (com) { espacio(); linea("Comisiones", dinero(com)); }
  const cuerpo = $("#tq-cuerpo");
  cuerpo.innerHTML = L.map((h, i) => h.replace("<div ", `<div style="--i:${i}" `)).join("");
  cuerpo.classList.remove("imprimiendo"); void cuerpo.offsetWidth; cuerpo.classList.add("imprimiendo");
  $("#tq-pie").textContent = `Vence el ${new Date(c.vence + "T12:00").toLocaleDateString("es", { day: "numeric", month: "long" })}. Las ventas se declaran en dólares enteros.`;
}

/* ---------- inicio ---------- */
const q = new URLSearchParams(location.search);
if (q.get("conexion") === "ok") avisar("Conectado a QuickBooks.");
if (q.get("conexion") === "cancelada") avisar("La conexión con QuickBooks se canceló.", true);
if (q.get("conexion") === "invalida") avisar("La conexión venció. Inténtelo de nuevo.", true);
if (q.has("conexion")) history.replaceState(null, "", "/");
cargarEstado().catch((e) => avisar(e.message, true));
