const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];
const MES_EN = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"];
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const dinero = (n) => (n ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const entero = (n) => (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
const pct = (n) => `${Number(n).toLocaleString("en-US", { maximumFractionDigits: 2 })} %`;
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const estado = {
  anio: null, mes: null, reglas: null, qbo: false, conectado: false, empresa: null,
  codigo: null, ejemplo: false, form: null, res: null, envio: null,
  ajustes: { exentos: null, pagados: null, cupones_empresa: null }, mapeos: {}, config: null,
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
  if (!r.ok) { const e = new Error(datos?.detail || `El servidor respondió ${r.status}.`); e.status = r.status; e.datos = datos; throw e; }
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
const dosCol = (el, filas, cab = ["", ""]) => tabla(el, [{ t: cab[0], html: (f) => f.a }, { t: cab[1], html: (f) => f.b }], filas);

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
  estado.empresa = e.empresa;
  if (!estado.anio) { llenarSelectores(e.anio); ponerPeriodo(e.anio, e.mes); }
  $("#conexion").hidden = !e.qbo_disponible;
  const entorno = e.entorno === "sandbox" ? "empresa de prueba" : "empresa real";
  $("#conexion-estado").innerHTML = e.conectado
    ? `Conectado a <strong>${esc(e.empresa)}</strong>${esc(entorno)}`
    : "Sin conexión a QuickBooks.";
  $("#btn-conectar").hidden = e.conectado;
  $("#btn-salir").hidden = !e.conectado;
  $("#bloque-qbo").hidden = !e.qbo_disponible;
  $("#btn-qbo").disabled = !e.conectado;
  if (!e.conectado) $("#guia-qbo").textContent = "Conecte QuickBooks para que calcule el impuesto.";
  pintarComo();
}
$("#btn-salir").addEventListener("click", async () => {
  await api("/auth/salir", { method: "POST" });
  avisar("Se desconectó de QuickBooks.");
  cargarEstado();
});

/* ---------- 1. archivos ---------- */
$$(".ranura input").forEach((inp) => inp.addEventListener("change", () => {
  const archivos = [...inp.files];
  const ranura = inp.closest(".ranura");
  ranura.classList.toggle("lista", archivos.length > 0);
  const corto = (n) => n.replace(/\.(xlsx|xls|csv)$/i, "").replace(/[_\-]+/g, " ").trim();
  const recorte = (n) => (n.length > 24 ? n.slice(0, 23) + "…" : n);
  const campo = ranura.querySelector(".ranura-archivo");
  campo.title = archivos.map((f) => f.name).join("\n");
  campo.innerHTML = archivos.length === 1
    ? `<span class="ranura-cuenta">${esc(recorte(corto(archivos[0].name)))}</span>`
    : archivos.length
      ? `<span class="ranura-cuenta">${archivos.length} archivos</span>`
      : "";
}));

function leerConfig() {
  try { return JSON.parse(localStorage.getItem("ezsnack_reglas") || "null"); } catch { return null; }
}
function ajustes() {
  const c = estado.config;
  return {
    exentos: estado.ajustes.exentos, pagados: estado.ajustes.pagados,
    cupones_empresa: estado.ajustes.cupones_empresa,
    cupones_empresa_minimo: c ? c.cupones_empresa_minimo : null,
    ciudades: c ? c.ciudades : null,
  };
}

async function subir(form) {
  const fd = new FormData();
  fd.append("maquinas", form.get("maquinas"));
  form.getAll("reportes").forEach((f) => f.size && fd.append("reportes", f));
  const pag = form.get("pagados");
  if (pag && pag.size) fd.append("pagados", pag);
  fd.append("mapeos", JSON.stringify(estado.mapeos));
  fd.append("ajustes", JSON.stringify(ajustes()));
  return api(`/api/cierre/archivos?anio=${estado.anio}&mes=${estado.mes}`, { method: "POST", body: fd });
}

async function empezar(origen) {
  estado.ajustes = { exentos: null, pagados: null, cupones_empresa: null };
  estado.envio = null;
  let d;
  if (origen === "ejemplo") {
    d = await api("/api/cierre/ejemplo", { method: "POST" });
    estado.form = null; estado.ejemplo = true;
    ponerPeriodo(d.anio, d.mes);
    if (estado.config) d = { ...(await postJSON(`/api/cierre/${d.codigo}/calcular`, { anio: d.anio, mes: d.mes, ajustes: ajustes() })), codigo: d.codigo };
  } else {
    estado.form = origen; estado.ejemplo = false;
    try { d = await subir(origen); }
    catch (e) {
      if (e.status === 422 && e.datos?.sin_leer) { pintarSinLeer(e.datos.sin_leer, e.datos.campos); $("#res-archivos").hidden = true; }
      throw e;
    }
  }
  estado.codigo = d.codigo;
  mostrar(d);
  $$(".paso").forEach((p) => (p.disabled = false));
  avisar(`${d.archivos.length} reportes, ${entero(d.maquinas.length)} máquinas.`);
}

$("#form-archivos").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  if (!fd.get("maquinas")?.size) { avisar("Elija la lista de máquinas.", true); return; }
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
      mostrar(await postJSON(`/api/cierre/${estado.codigo}/calcular`, { anio: estado.anio, mes: estado.mes, ajustes: ajustes() }));
    } catch (e) {
      if (e.status === 410) { await volverASubir(); return; }
      avisar(e.message, true);
    }
  }, 250);
}
async function volverASubir() {
  const a = estado.ajustes;
  if (estado.ejemplo) await empezar("ejemplo");
  else if (estado.form) await empezar(estado.form);
  else return;
  estado.ajustes = a;
  recalcular();
}

function mostrar(d) {
  estado.res = d;
  pintarArchivos(d);
  pintarProductos(d);
  pintarDeclaracion(d);
  imprimirTiquete(d);
}

const DESCARTE = { "filas de total o vacias": "filas de totales del reporte, sin venta propia", "transacciones rechazadas (valor 0)": "cobros rechazados por la tarjeta, en $0", "filas sin valor": "filas en $0" };
function pintarArchivos(d) {
  $("#res-archivos").hidden = false;
  const p = d.pasos;
  $("#cifras-archivos").innerHTML = `
    <div><dt>Ventas del mes</dt><dd>${dinero(p.total.total)}</dd></div>
    <div><dt>Efectivo</dt><dd>${dinero(p.total.efectivo)}</dd></div>
    <div><dt>Tarjeta</dt><dd>${dinero(p.total.tarjeta)}</dd></div>
    <div><dt>Máquinas</dt><dd>${entero(d.maquinas.length)}</dd></div>
    <div class="${d.revisar.length ? "alerta" : ""}"><dt>Para revisar</dt><dd>${entero(d.revisar.length)}</dd></div>`;
  $("#revisar").hidden = !d.revisar.length;
  pintarSinLeer(d.sin_leer, d.campos, d.archivos.filter((a) => a.generico));
  $("#lista-revisar").innerHTML = d.revisar.map((r) => `<li><strong>${esc(r.texto)}</strong><span class="detalle">${esc(r.detalle)}</span></li>`).join("");

  const A = d.archivos;
  const suma = (k) => A.reduce((a, f) => a + f[k], 0);
  tabla($("#tabla-archivos"), [
    { t: "Archivo", html: (f) => `<span class="archivo">${esc(f.archivo)}</span>${f.periodo ? `<span class="sub">${esc(f.periodo)}</span>` : ""}` },
    { t: "Lector", html: (f) => `${esc(f.fuente)}${f.generico ? `<span class="sub">Columnas reconocidas</span>` : ""}` },
    { t: "Filas usadas", num: true, html: (f) => {
      const fuera = Object.entries(f.descartadas).filter(([, v]) => v).map(([k, v]) => `${entero(v)} ${DESCARTE[k] || k}`).join("; ");
      return `${entero(f.usadas)}${fuera ? `<span class="sub">No se contaron ${esc(fuera)}</span>` : ""}`;
    } },
    { t: "Efectivo", num: true, v: (f) => dinero(f.efectivo) },
    { t: "Tarjeta", num: true, v: (f) => dinero(f.tarjeta) },
  ], A, ["Total", "", entero(suma("usadas")), dinero(suma("efectivo")), dinero(suma("tarjeta"))]);
  pintarMaquinas();
}

function pintarSinLeer(sinLeer = [], campos = {}, genericos = []) {
  const todos = [...sinLeer.map((f) => ({ ...f, falla: true })), ...genericos];
  $("#mapeos").hidden = !todos.length;
  $("#lista-mapeos").innerHTML = todos.map((f, i) => `
    <li class="mapeo" data-archivo="${esc(f.archivo)}">
      <p><strong>${esc(f.archivo)}</strong> <span class="estado ${f.falla ? "estado-revisar" : "estado-ok"}">${f.falla ? "Falta indicar columnas" : "Reconocido"}</span></p>
      <div class="mapeo-campos">${Object.entries(campos).map(([k, nombre]) => `
        <label>${esc(nombre)}<select data-campo="${k}"><option value="">No tiene</option>${
          f.columnas.map((c) => `<option ${f.mapeo[k] === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>`).join("")}
      </div>
      <button class="boton boton-secundario" data-aplicar="${i}">Usar estas columnas</button>
    </li>`).join("");
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-aplicar]");
  if (!b) return;
  const li = b.closest(".mapeo");
  const m = {};
  li.querySelectorAll("select").forEach((sel) => { if (sel.value) m[sel.dataset.campo] = sel.value; });
  if (!m.maquina || !m.producto || !(m.total || m.efectivo || m.tarjeta)) { avisar("Indique la máquina, el producto y un valor vendido.", true); return; }
  estado.mapeos[li.dataset.archivo] = m;
  if (estado.form) ocupado(b, () => empezar(estado.form));
});

function pintarMaquinas() {
  const d = estado.res; if (!d) return;
  const q = $("#buscar-maquina").value.trim().toLowerCase();
  const filas = d.maquinas.filter((m) => !q || `${m.id_maquina} ${m.maquina} ${m.ciudad} ${m.locacion}`.toLowerCase().includes(q))
    .map((m) => ({ ...m, _clase: m.en_lista ? "" : "fila-alerta" }));
  tabla($("#tabla-maquinas"), [
    { t: "Máquina", html: (f) => `<strong>${esc(f.id_maquina || "?")}</strong><span class="sub">${esc(f.locacion || f.maquina)}</span>` },
    { t: "Lector", v: (f) => f.fuente },
    { t: "Ciudad", html: (f) => (f.en_lista ? esc(f.ciudad || "Sin ciudad") : `<span class="estado estado-revisar">No está en la lista</span>`) },
    { t: "Impuesto local", v: (f) => f.jurisdiccion || "" },
    { t: "Ventas", num: true, v: (f) => dinero(f.ventas) },
    { t: "Gravable", num: true, v: (f) => dinero(f.gravable) },
  ], filas, ["Total", "", "", `${filas.length} máquinas`, dinero(filas.reduce((a, f) => a + f.ventas, 0)), dinero(filas.reduce((a, f) => a + f.gravable, 0))]);
}
$("#buscar-maquina").addEventListener("input", pintarMaquinas);

/* ---------- 2. productos y cupones ---------- */
function pintarProductos(d) {
  $("#lista-productos").innerHTML = d.productos.map((p) => `<option value="${esc(p)}">`).join("");
  const exentos = d.exentos;
  tabla($("#tabla-exentos"), [
    { t: "Exento", html: (f) => `<input type="checkbox" data-exento="${esc(f.producto)}" ${f.marcado ? "checked" : ""} aria-label="Exento: ${esc(f.producto)}">` },
    { t: "Producto", v: (f) => f.producto },
    { t: "Unidades", num: true, v: (f) => entero(f.cantidad) },
    { t: "Ventas", num: true, v: (f) => dinero(f.ventas) },
  ], exentos, ["", "Total exento", "", dinero(d.pasos.agua.total)]);
  if (!exentos.length) $("#tabla-exentos").innerHTML = `<tbody><tr><td>No se encontró agua entre los productos vendidos.</td></tr></tbody>`;

  const P = d.pagados;
  const etiqueta = { seguro: "", dudoso: `<span class="estado estado-revisar">Revisar tamaño</span>`, sin_ventas: `<span class="estado estado-revisar">Sin ventas este mes</span>`, manual: `<span class="estado estado-impuesto">Agregado aquí</span>` };
  const extra = (estado.ajustes.pagados || []).filter((p) => !P.some((f) => f.producto === p)).map((p) => ({ buscado: "", producto: p, ventas: null, estado: "manual", marcado: true }));
  const filas = [...P, ...extra];
  tabla($("#tabla-pagados"), [
    { t: "Descontar", html: (f) => (f.producto ? `<input type="checkbox" data-pagado="${esc(f.producto)}" ${f.marcado ? "checked" : ""} ${f.exento ? "disabled" : ""} aria-label="Comprado con impuesto: ${esc(f.producto)}">` : "") },
    { t: "En su lista", v: (f) => f.buscado },
    { t: "Producto vendido", html: (f) => `${esc(f.producto || "")} ${etiqueta[f.estado] || ""}${f.exento ? `<span class="sub">Ya es exento</span>` : ""}` },
    { t: "Ventas", num: true, v: (f) => (f.ventas == null ? "" : dinero(f.ventas)) },
  ], filas, ["", "", "Total a descontar", dinero(d.pasos.walmart.total)]);
  if (!filas.length) $("#tabla-pagados").innerHTML = `<tbody><tr><td>Sin productos. Suba la lista en el paso 1 o agréguelos aquí.</td></tr></tbody>`;

  const C = d.cupones;
  tabla($("#tabla-cupones"), [
    { t: "Lo compró una empresa", html: (f) => `<input type="checkbox" data-cupon="${esc(f.id_maquina)}" ${f.de_empresa ? "checked" : ""} aria-label="Cupones de empresa: ${esc(f.maquina)}">` },
    { t: "Máquina", html: (f) => `<strong>${esc(f.id_maquina)}</strong><span class="sub">${esc(f.locacion || f.maquina)}</span>` },
    { t: "Cupones del mes", num: true, v: (f) => dinero(f.valor) },
    { t: "Cuenta como", v: (f) => (f.de_empresa ? "Venta" : "Devolución") },
  ], C, ["", "Venta / devolución", dinero(d.pasos.cupones_empresa.total), dinero(d.pasos.devoluciones.total)]);
  if (!C.length) $("#tabla-cupones").innerHTML = `<tbody><tr><td>Ningún reporte trae cupones este mes.</td></tr></tbody>`;
}

const marcados = (sel, attr) => $$(sel).filter((c) => c.checked).map((c) => c.dataset[attr]);
document.addEventListener("change", (ev) => {
  if (ev.target.matches("[data-exento]")) {
    const fuera = (estado.ajustes.exentos || []).filter((p) => !$$("[data-exento]").some((c) => c.dataset.exento === p));
    estado.ajustes.exentos = [...marcados("[data-exento]", "exento"), ...fuera];
    recalcular();
  }
  if (ev.target.matches("[data-pagado]")) { estado.ajustes.pagados = marcados("[data-pagado]", "pagado"); recalcular(); }
  if (ev.target.matches("[data-cupon]")) { estado.ajustes.cupones_empresa = marcados("[data-cupon]", "cupon"); recalcular(); }
});
function agregar(input, clave) {
  const nombre = input.value.trim();
  if (!estado.res.productos.includes(nombre)) { avisar("Elija un producto de la lista.", true); return; }
  const marcadosAhora = clave === "exentos"
    ? estado.res.exentos.filter((f) => f.marcado).map((f) => f.producto)
    : estado.res.pagados.filter((f) => f.marcado).map((f) => f.producto);
  estado.ajustes[clave] = [...new Set([...(estado.ajustes[clave] ?? marcadosAhora), nombre])];
  input.value = "";
  recalcular();
}
$("#btn-otro-exento").addEventListener("click", () => agregar($("#otro-exento"), "exentos"));
$("#btn-otro-pagado").addEventListener("click", () => agregar($("#otro-pagado"), "pagados"));

/* ---------- 3. declaracion ---------- */
function pintarDeclaracion(d) {
  const p = d.pasos, c = d.declaracion;
  const filas = [
    { c: "Ventas en efectivo y tarjeta", k: "ventas" },
    { c: "Cupones que compró una empresa", k: "cupones_empresa" },
    { c: "Ventas totales", k: "total", _clase: "fila-fuerte" },
    { c: "Cupones devueltos a clientes", k: "devoluciones" },
    { c: "Ventas netas", k: "neto", _clase: "fila-fuerte" },
    { c: "Agua", k: "agua" },
    { c: "Comprado con impuesto pagado", k: "walmart" },
    { c: "Ventas gravables", k: "gravable", _clase: "fila-fuerte" },
    { c: "Máquinas de Houston", k: "bruto_Houston" },
    { c: "Base de HOUSTON-CITY", k: "base_Houston", _clase: "fila-fuerte" },
    { c: `Base de HOUSTON MTA (${d.reglas.jurisdicciones["Houston MTA"].ciudades.join(", ")})`, k: "base_Houston MTA", _clase: "fila-fuerte" },
  ];
  tabla($("#tabla-cascada"), [
    { t: "", v: (f) => f.c },
    { t: "Efectivo", num: true, v: (f) => dinero(p[f.k].efectivo) },
    { t: "Tarjeta", num: true, v: (f) => dinero(p[f.k].tarjeta) },
    { t: "Total", num: true, v: (f) => dinero(p[f.k].total) },
  ], filas);

  tabla($("#tabla-comptroller"), [
    { t: "Campo", html: (f) => `${esc(f.c)}${f.s ? `<span class="sub">${esc(f.s)}</span>` : ""}` },
    { t: "Tasa", num: true, v: (f) => f.t || "" },
    { t: "Valor", num: true, html: (f) => copiable(f.v, entero(f.v)) },
  ], [
    { c: "Total Texas Sales", v: c.total_ventas },
    { c: "Taxable Sales", v: c.ventas_gravables, t: pct(c.tasa_estado) },
    { c: "Taxable Purchases", v: 0 },
    ...c.locales.map((l) => ({ c: l.nombre_comptroller, s: `${l.codigo} · ${l.maquinas} máquinas`, v: l.base, t: pct(l.tasa) })),
  ]);
  pintarEnvio();
  pintarVerificacion(d);
}

function pintarVerificacion(d) {
  const v = d.verificacion;
  $("#verificacion").hidden = !v;
  if (!v) return;
  const p = d.pasos, ex = v.excel, co = v.comptroller;
  const fila = (concepto, prog, excel, comp) => ({ concepto, prog, excel, comp, dif: excel == null ? null : prog - excel });
  tabla($("#tabla-verif"), [
    { t: "", v: (f) => f.concepto },
    { t: "Este programa", num: true, v: (f) => dinero(f.prog) },
    { t: "Excel", num: true, v: (f) => (f.excel == null ? "" : dinero(f.excel)) },
    { t: "Diferencia", num: true, html: (f) => (f.dif == null ? "" : `<span class="${Math.abs(f.dif) < 0.01 ? "igual" : "distinto"}">${Math.abs(f.dif) < 0.01 ? "igual" : (f.dif > 0 ? "+" : "−") + dinero(Math.abs(f.dif))}</span>`) },
    { t: "Declarado", num: true, v: (f) => (f.comp == null ? "" : dinero(f.comp)) },
  ], [
    fila("Ventas en efectivo y tarjeta", p.ventas.total, ex.total, null),
    fila("Ventas netas", p.neto.total, ex.neto, co.total_ventas),
    fila("Agua", p.agua.total, ex.exentas, null),
    fila("Comprado con impuesto pagado", p.walmart.total, ex.pagadas, null),
    fila("Ventas gravables", p.gravable.total, ex.gravable, co.ventas_gravables),
    fila("Máquinas de Houston", p.bruto_Houston.total, ex.houston_bruto, null),
    fila("Base de HOUSTON-CITY", p.base_Houston.total, ex.houston, co.houston),
    fila("Base de HOUSTON MTA", p["base_Houston MTA"].total, ex.mta_bruto, co.mta),
  ]);
}

/* ---------- Excel ---------- */
$("#btn-libro").addEventListener("click", () => ocupado($("#btn-libro"), async () => {
  let r;
  try { r = await api(`/api/cierre/${estado.codigo}/libro`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ anio: estado.anio, mes: estado.mes, ajustes: ajustes() }) }); }
  catch (e) { if (e.status === 410) { await volverASubir(); throw new Error("Se volvieron a leer los archivos. Intente de nuevo."); } throw e; }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob());
  a.download = `Integrated_Sales_EzSnack_${MES_EN[estado.mes - 1]}${estado.anio}.xlsx`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}));

/* ---------- QuickBooks ---------- */
$("#btn-qbo").addEventListener("click", () => {
  const barra = $("#prog-qbo");
  barra.hidden = false;
  let avance = 0;
  const reloj = setInterval(() => {
    avance = Math.min(avance + 3, 92);
    barra.firstElementChild.style.width = `${avance}%`;
  }, 700);
  ocupado($("#btn-qbo"), async () => {
    try {
      estado.envio = await postJSON(`/api/cierre/${estado.codigo}/quickbooks`, { anio: estado.anio, mes: estado.mes, ajustes: ajustes() });
    } catch (e) {
      if (e.status === 410) { await volverASubir(); throw new Error("Se volvieron a leer los archivos. Intente de nuevo."); }
      throw e;
    }
    barra.firstElementChild.style.width = "100%";
    pintarEnvio();
    imprimirTiquete(estado.res);
    if (estado.envio.errores.length) avisar(`${estado.envio.errores.length} recibos con error: ${estado.envio.errores[0].error}`, true);
    else avisar("QuickBooks calculó el impuesto.");
  }).finally(() => {
    clearInterval(reloj);
    setTimeout(() => { barra.hidden = true; barra.firstElementChild.style.width = "0"; }, 800);
  });
});

function pintarEnvio() {
  const r = estado.envio;
  $("#res-qbo").hidden = !r;
  $("#btn-qbo").disabled = !estado.conectado;
  if (!r) return;
  tabla($("#tabla-qbo"), [
    { t: "Tasa", v: (f) => f.jurisdiccion },
    { t: "Porcentaje", num: true, v: (f) => pct(f.tasa) },
    { t: "Taxable sales", num: true, v: (f) => dinero(f.base) },
    { t: "Impuesto", num: true, v: (f) => dinero(f.impuesto) },
  ], r.por_jurisdiccion, ["Total según QuickBooks", "", "", dinero(r.impuesto)]);
  $("#nota-qbo").textContent = `${r.creados} recibos creados y ${r.actualizados} actualizados. `
    + `QuickBooks recibió ${dinero(r.gravable)} como taxable sales y ${dinero(r.exento)} como nontaxable sales.`;
}

/* ---------- tiquete ---------- */
function imprimirTiquete(d) {
  const p = d.pasos, c = d.declaracion;
  const L = [];
  const linea = (a, b = "", cls = "") => L.push(`<div class="tq-linea ${cls}"><span>${esc(a)}</span><span>${esc(b)}</span></div>`);
  const espacio = () => L.push(`<div class="tq-espacio"></div>`);
  linea("Efectivo y tarjeta", dinero(p.ventas.total));
  if (p.cupones_empresa.total) linea("Cupones a empresas", "+" + dinero(p.cupones_empresa.total), "tq-sub");
  if (p.devoluciones.total) linea("Devueltos a clientes", "-" + dinero(p.devoluciones.total), "tq-sub");
  linea("Agua", "-" + dinero(p.agua.total), "tq-sub");
  linea("Ya pagadas", "-" + dinero(p.walmart.total), "tq-sub");
  linea("Gravables", dinero(p.gravable.total));
  espacio();
  c.locales.forEach((l) => linea(l.nombre_comptroller, dinero(l.base), "tq-sub"));
  espacio();
  if (estado.envio) {
    const q = estado.envio.por_jurisdiccion;
    const estatal = q.filter((x) => /estado|state/i.test(x.jurisdiccion)).reduce((a, x) => a + x.impuesto, 0);
    linea("Impuesto QuickBooks");
    linea(`Estado ${pct(c.tasa_estado)}`, dinero(estatal), "tq-sub");
    linea("Ciudad y MTA 1 %", dinero(estado.envio.impuesto - estatal), "tq-sub");
    linea("Total", dinero(estado.envio.impuesto), "tq-total");
  } else {
    linea("Impuesto en Houston 8.25 %");
    linea("6.25 estado + 1 ciudad + 1 MTA", "", "tq-sub");
    linea("Lo calcula QuickBooks", "", "tq-sub");
  }
  const cuerpo = $("#tq-cuerpo");
  cuerpo.innerHTML = L.map((h, i) => h.replace("<div ", `<div style="--i:${i}" `)).join("");
  cuerpo.classList.remove("imprimiendo"); void cuerpo.offsetWidth; cuerpo.classList.add("imprimiendo");
  $("#tq-pie").textContent = `Un solo pago al Texas Comptroller. Vence el ${new Date(c.vence + "T12:00").toLocaleDateString("es", { day: "numeric", month: "long" })}.`;
}

/* ---------- reglas ---------- */
function pintarConfig() {
  const base = estado.reglas;
  const c = estado.config || {
    cupones_empresa_minimo: base.cupones_empresa_minimo,
    ciudades: Object.fromEntries(Object.entries(base.jurisdicciones).map(([k, v]) => [k, v.ciudades])),
  };
  $("#cfg-houston").value = (c.ciudades.Houston || []).join(", ");
  $("#cfg-mta").value = (c.ciudades["Houston MTA"] || []).join(", ");
  $("#cfg-cupones").value = c.cupones_empresa_minimo;
}
const lista = (t) => t.split(",").map((x) => x.trim()).filter(Boolean);
$("#form-config").addEventListener("submit", (ev) => {
  ev.preventDefault();
  estado.config = {
    cupones_empresa_minimo: +$("#cfg-cupones").value || 0,
    ciudades: { Houston: lista($("#cfg-houston").value), "Houston MTA": lista($("#cfg-mta").value) },
  };
  try { localStorage.setItem("ezsnack_reglas", JSON.stringify(estado.config)); } catch { /* sin almacenamiento */ }
  avisar("Reglas guardadas.");
  pintarComo();
  if (estado.codigo) { estado.ajustes.cupones_empresa = null; recalcular(); }
});
$("#btn-cfg-reset").addEventListener("click", () => {
  estado.config = null;
  try { localStorage.removeItem("ezsnack_reglas"); } catch { /* sin almacenamiento */ }
  pintarConfig();
  pintarComo();
  avisar("Reglas originales.");
  if (estado.codigo) { estado.ajustes.cupones_empresa = null; recalcular(); }
});

/* ---------- como funciona ---------- */
function pintarComo() {
  const R = estado.reglas; if (!R) return;
  const ciudades = estado.config ? estado.config.ciudades
    : Object.fromEntries(Object.entries(R.jurisdicciones).map(([k, v]) => [k, v.ciudades]));

  tabla($("#tabla-pasos"), [
    { t: "Paso del cierre", v: (f) => f.p },
    { t: "Antes", v: (f) => f.antes },
    { t: "Ahora", html: (f) => `<span class="estado ${f.c}">${esc(f.quien)}</span>` },
  ], [
    { p: "Descargar los reportes de cada lector", antes: "El gerente", quien: "El gerente", c: "estado-impuesto" },
    { p: "Unir los cuatro reportes", antes: "ChatGPT", quien: "La aplicación", c: "estado-ok" },
    { p: "Revisar duplicados y nombres distintos", antes: "El gerente, a ojo", quien: "La aplicación", c: "estado-ok" },
    { p: "Separar el agua", antes: "Filtro en Excel", quien: "La aplicación", c: "estado-ok" },
    { p: "Separar lo comprado con impuesto pagado", antes: "Filtro en Excel", quien: "La aplicación", c: "estado-ok" },
    { p: "Separar cupones de venta y de devolución", antes: "Estimado del 3 %", quien: "La aplicación", c: "estado-ok" },
    { p: "Cruzar las máquinas de Houston y del MTA", antes: "Dos pantallas en paralelo", quien: "La aplicación", c: "estado-ok" },
    { p: "Calcular el impuesto", antes: "Tasa fija en Excel", quien: "QuickBooks", c: "estado-impuesto" },
    { p: "Guardar el respaldo para una auditoría", antes: "Excel a mano", quien: "La aplicación", c: "estado-ok" },
    { p: "Digitar y pagar en el Comptroller", antes: "El gerente", quien: "El gerente", c: "estado-impuesto" },
  ]);

  dosCol($("#tabla-modulos"), [
    { a: "<strong>Sales Tax</strong>", b: "Calcula el impuesto de cada recibo y arma la declaración del periodo con su fecha de vencimiento." },
    { a: "<strong>Sales Receipts</strong>", b: "Guarda un recibo por máquina. Es la venta contabilizada y el respaldo de la declaración." },
    { a: "<strong>Items</strong>", b: "Tres productos de servicio. El de ventas gravables está marcado como gravable y los otros dos no." },
    { a: "<strong>Customers</strong>", b: "Un cliente genérico, <em>Consumidores en maquinas</em>, porque en una máquina no hay cliente con nombre." },
    { a: "<strong>Accounts</strong>", b: "La cuenta de ingresos <em>Ventas en maquinas</em>, donde queda el valor de los recibos." },
    { a: "<strong>Tax agencies y tax rates</strong>", b: "El Texas Comptroller y las tres tasas propias de EzSnack." },
  ], ["Módulo de QuickBooks", "Para qué lo usamos"]);

  tabla($("#tabla-renglones"), [
    { t: "Renglón del recibo", v: (f) => f.r },
    { t: "Item en QuickBooks", v: (f) => f.i },
    { t: "Marca", html: (f) => `<span class="estado ${f.c}">${f.m}</span>` },
    { t: "Entra en", v: (f) => f.e },
  ], [
    { r: "Ventas gravables", i: "Ventas gravables", m: "TAX", c: "estado-ok", e: "Taxable sales" },
    { r: "Agua", i: "Agua (exenta)", m: "NON", c: "estado-impuesto", e: "Nontaxable sales" },
    { r: "Comprado con impuesto pagado", i: "Comprado con impuesto ya pagado", m: "NON", c: "estado-impuesto", e: "Nontaxable sales" },
  ]);

  const tasas = estado.tasas || {};
  tabla($("#tabla-tasas"), [
    { t: "Tasa en QuickBooks", v: (f) => f.n },
    { t: "Se arma con", v: (f) => f.d },
    { t: "Se aplica a", v: (f) => f.a },
    { t: "Id", v: (f) => tasas[f.k] || "" },
  ], [
    { k: "Houston", n: "EzSnack Houston", d: `${pct(R.tasa_estado)} estado + ${pct(R.jurisdicciones.Houston.tasa)} HOUSTON-CITY`, a: (ciudades.Houston || []).join(", ") },
    { k: "Houston MTA", n: "EzSnack Houston MTA", d: `${pct(R.tasa_estado)} estado + ${pct(R.jurisdicciones["Houston MTA"].tasa)} HOUSTON MTA`, a: (ciudades["Houston MTA"] || []).join(", ") },
    { k: "Solo estado", n: "EzSnack Solo estado", d: `${pct(R.tasa_estado)} estado`, a: "Las demás ciudades" },
  ]);
  $("#nota-tasas").textContent = estado.tasas
    ? `Creadas en ${estado.empresa}. Se ven en QuickBooks, en Sales Tax, Sales tax settings.`
    : "Conecte QuickBooks y envíe un cierre para ver los identificadores de estas tasas.";

  dosCol($("#tabla-tecnica"), [
    { a: "<strong>Servidor</strong>", b: "Python con FastAPI. Los archivos se leen en memoria con pandas y openpyxl, y se borran a las tres horas." },
    { a: "<strong>Autorización</strong>", b: "OAuth 2. La página manda al usuario a Intuit, Intuit devuelve un código y el servidor lo cambia por un token de acceso y uno de refresco." },
    { a: "<strong>Dónde quedan los tokens</strong>", b: "Cifrados en una cookie del navegador de cada usuario, no en el servidor. Cada quien ve solo la empresa que autorizó." },
    { a: "<strong>Renovación</strong>", b: "El token de acceso dura una hora. Cuando vence, el servidor lo renueva con el de refresco y vuelve a intentar la llamada." },
    { a: "<strong>API</strong>", b: "Accounting API v3. Consultas con el lenguaje de Intuit y creación de los recibos en lotes de 25 con el endpoint batch." },
    { a: "<strong>Entorno</strong>", b: `Sandbox mientras la aplicación use las llaves de desarrollo. Para la empresa real hay que pasar la revisión de Intuit.` },
  ], ["", ""]);
}

/* ---------- inicio ---------- */
const q = new URLSearchParams(location.search);
if (q.get("conexion") === "ok") avisar("Conectado a QuickBooks.");
if (q.get("conexion") === "cancelada") avisar("La conexión con QuickBooks se canceló.", true);
if (q.get("conexion") === "invalida") avisar("La conexión venció. Inténtelo de nuevo.", true);
if (q.has("conexion")) history.replaceState(null, "", "/");
estado.config = leerConfig();
cargarEstado().then(() => {
  pintarConfig();
  if (estado.conectado) api("/api/quickbooks/tasas").then((d) => { estado.tasas = d.tasas; pintarComo(); }).catch(() => {});
}).catch((e) => avisar(e.message, true));
