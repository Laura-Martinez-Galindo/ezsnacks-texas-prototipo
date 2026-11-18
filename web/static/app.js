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
  ajustes: { exentos: null, pagados: null, cupones_empresa: null }, mapeos: {}, cfg: null, usuario: null, roles: {},
};
const puede = (rol) => ({ consulta: 0, operador: 1, admin: 2 }[estado.usuario?.rol] ?? -1) >= { consulta: 0, operador: 1, admin: 2 }[rol];
const fecha = (iso) => (iso ? new Date(iso).toLocaleString("es", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "");

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
  if (r.status === 401 && !ruta.startsWith("/api/sesion")) pedirEntrada();
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
  if (!estado.anio) { llenarSelectores(e.anio); ponerPeriodo(e.anio, e.mes); }
  if (e.requiere_login) { pedirEntrada(); return false; }
  $("#entrada").hidden = true;
  estado.reglas = e.reglas;
  estado.usuario = e.usuario;
  estado.roles = e.roles;
  estado.almacen = e.almacen;
  estado.qbo = e.qbo_disponible;
  estado.conectado = e.conectado;
  estado.empresa = e.empresa;
  estado.maquinasGuardadas = e.maquinas_guardadas;
  document.body.dataset.rol = e.usuario.rol;
  $("#sesion").hidden = e.usuario.abierto;
  $("#sesion-estado").innerHTML = `<strong>${esc(e.usuario.nombre)}</strong>${esc(e.roles[e.usuario.rol])}`;
  $("#btn-cerrar-sesion").hidden = e.usuario.abierto;
  $("#ayuda-maquinas").textContent = e.maquinas_guardadas
    ? `${e.maquinas_guardadas} guardadas. Suba el vendor list solo si cambió.` : "Vendor list";
  const conQbo = e.reglas.contabilidad.destino === "quickbooks";
  $("#conexion").hidden = !e.qbo_disponible || !conQbo;
  const entorno = e.entorno === "sandbox" ? "empresa de prueba" : "empresa real";
  $("#conexion-estado").innerHTML = e.conectado
    ? `Conectado a <strong>${esc(e.empresa)}</strong>${esc(entorno)}`
    : "Sin conexión a QuickBooks.";
  $("#btn-conectar").hidden = e.conectado || !puede("admin");
  $("#btn-salir").hidden = !e.conectado || !puede("admin");
  $("#bloque-qbo").hidden = !e.qbo_disponible || !conQbo;
  $("#btn-qbo").disabled = !e.conectado;
  if (!e.conectado) $("#guia-qbo").textContent = "Conecte QuickBooks para que calcule el impuesto.";
  pintarComo();
  return true;
}
function pedirEntrada() {
  $("#entrada").hidden = false;
  setTimeout(() => $("#ent-usuario").focus(), 50);
}
$("#form-entrada").addEventListener("submit", (ev) => {
  ev.preventDefault();
  ocupado($("#btn-entrar"), async () => {
    await postJSON("/api/sesion/entrar", { usuario: $("#ent-usuario").value, clave: $("#ent-clave").value });
    $("#ent-clave").value = "";
    await iniciar();
  });
});
$("#btn-cerrar-sesion").addEventListener("click", async () => {
  await api("/api/sesion/salir", { method: "POST" });
  location.reload();
});
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

function ajustes() {
  return { exentos: estado.ajustes.exentos, pagados: estado.ajustes.pagados, cupones_empresa: estado.ajustes.cupones_empresa };
}

async function subir(form) {
  const fd = new FormData();
  const lista = form.get("maquinas");
  if (lista && lista.size) fd.append("maquinas", lista);
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
  if (!d.ejemplo) cargarConfig().catch(() => {});
  const g = d.maquinas_guardadas;
  if (g && (g.nuevas || g.cambiadas)) { avisar(`Lista de máquinas guardada: ${g.nuevas} nuevas y ${g.cambiadas} con cambios.`); cargarEstado(); cargarConfig(); }
}

$("#form-archivos").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  if (!fd.get("maquinas")?.size && !estado.maquinasGuardadas) { avisar("Elija la lista de máquinas.", true); return; }
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
  pintarComparacion(d);
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
    { t: "Lector", html: (f) => `${esc(f.fuente)}${f.generico ? `<span class="sub">Columnas reconocidas</span>` : ""}${f.registrado ? `<span class="sub">Sistema registrado</span>` : ""}` },
    { t: "Filas usadas", num: true, html: (f) => {
      const fuera = Object.entries(f.descartadas).filter(([, v]) => v).map(([k, v]) => `${entero(v)} ${DESCARTE[k] || k}`).join("; ");
      const avisos = (f.avisos || []).map((a) => `<span class="sub">${esc(a)}</span>`).join("");
      return `${entero(f.usadas)}${fuera ? `<span class="sub">No se contaron ${esc(fuera)}</span>` : ""}${avisos}`;
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
      <div class="mapeo-guardar">
        <label>Nombre del sistema<input type="text" data-sistema maxlength="24" placeholder="Por ejemplo, Cantaloupe" value="${esc(f.falla ? "" : f.fuente)}"></label>
        <button class="boton" data-registrar="${i}">Registrar este sistema</button>
        <button class="boton boton-secundario" data-aplicar="${i}">Usar solo esta vez</button>
      </div>
    </li>`).join("");
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-aplicar], [data-registrar]");
  if (!b) return;
  const li = b.closest(".mapeo");
  const m = {};
  li.querySelectorAll("select").forEach((sel) => { if (sel.value) m[sel.dataset.campo] = sel.value; });
  if (!m.maquina || !m.producto || !(m.total || m.efectivo || m.tarjeta)) { avisar("Indique la máquina, el producto y un valor vendido.", true); return; }
  if (b.dataset.registrar !== undefined) {
    const nombre = li.querySelector("[data-sistema]").value.trim();
    if (!nombre) { avisar("Póngale un nombre al sistema, por ejemplo Cantaloupe.", true); return; }
    ocupado(b, async () => {
      estado.cfg.formatos = (await postJSON("/api/config/formatos", { nombre, mapeo: m })).formatos;
      pintarFormatos();
      delete estado.mapeos[li.dataset.archivo];
      avisar(`${nombre} quedó registrado. Sus próximos reportes se reconocen solos.`);
      if (estado.form) await empezar(estado.form);
    });
    return;
  }
  estado.mapeos[li.dataset.archivo] = m;
  if (estado.form) ocupado(b, () => empezar(estado.form));
});
function pintarFormatos() {
  const el = $("#tabla-formatos"); if (!el || !estado.cfg) return;
  const campos = { maquina: "Máquina", producto: "Producto", cantidad: "Cantidad", efectivo: "Efectivo", tarjeta: "Tarjeta", cupones: "Cupones", total: "Total vendido", metodo: "Forma de pago" };
  const propios = ["Nayax", "AV360", "XMAI", "Qingo"].map((n) => ({ nombre: n, fijo: true }));
  tabla(el, [
    { t: "Sistema", html: (f) => `<strong>${esc(f.nombre)}</strong>` },
    { t: "Cómo se reconoce", html: (f) => (f.fijo ? "Viene con la aplicación" : Object.entries(f.mapeo).map(([k, v]) => `${esc(campos[k] || k)}: <em>${esc(v)}</em>`).join(" · ")) },
    { t: "Registrado por", v: (f) => (f.fijo ? "" : f.por || "") },
    { t: "", html: (f) => (f.fijo || !puede("operador") ? "" : `<button class="enlace" data-olvidar="${esc(f.nombre)}">Quitar</button>`) },
  ], [...propios, ...estado.cfg.formatos]);
}
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-olvidar]");
  if (!b) return;
  try {
    estado.cfg.formatos = (await postJSON("/api/config/formatos/quitar", { nombre: b.dataset.olvidar, mapeo: {} })).formatos;
    pintarFormatos();
    avisar(`Se quitó ${b.dataset.olvidar}.`);
  } catch (e) { avisar(e.message, true); }
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
  const porPct = d.pasos.devoluciones_metodo === "porcentaje";
  $("#vista-productos .guia").textContent = porPct
    ? `Las devoluciones se calculan como el ${pct(d.pasos.devoluciones_pct)} de lo vendido (regla de porcentaje fijo). Los cupones del reporte, ${dinero(d.pasos.cupones_reporte)}, no entran en la cuenta.`
    : d.pasos.cupones_empresa_cuentan
      ? "Los que compra una empresa para sus empleados son venta. Los demás se devolvieron a clientes que reclamaron y se restan."
      : `Los que compra una empresa para sus empleados (${dinero(d.pasos.cupones_empresa_fuera)} este mes) no cuentan: ni venta ni devolución. Los demás se devolvieron a clientes que reclamaron y se restan.`;
  tabla($("#tabla-cupones"), [
    { t: "Lo compró una empresa", html: (f) => `<input type="checkbox" data-cupon="${esc(f.id_maquina)}" ${f.de_empresa ? "checked" : ""} ${porPct ? "disabled" : ""} aria-label="Cupones de empresa: ${esc(f.maquina)}">` },
    { t: "Máquina", html: (f) => `<strong>${esc(f.id_maquina)}</strong><span class="sub">${esc(f.locacion || f.maquina)}</span>` },
    { t: "Cupones del mes", num: true, v: (f) => dinero(f.valor) },
    { t: "Cuenta como", v: (f) => (porPct ? "No se usa" : f.de_empresa ? (d.pasos.cupones_empresa_cuentan ? "Venta" : "No cuenta") : "Devolución") },
  ], C, porPct ? ["", "Cupones del reporte", dinero(d.pasos.cupones_reporte), ""] : ["", "Venta / devolución", dinero(d.pasos.cupones_empresa.total), dinero(d.pasos.devoluciones.total)]);
  if (!C.length) $("#tabla-cupones").innerHTML = `<tbody><tr><td>Ningún reporte trae cupones este mes.</td></tr></tbody>`;
}

const marcados = (sel, attr) => $$(sel).filter((c) => c.checked).map((c) => c.dataset[attr]);
document.addEventListener("change", (ev) => {
  if (ev.target.matches("[data-exento]")) {
    const fuera = (estado.ajustes.exentos || []).filter((p) => !$$("[data-exento]").some((c) => c.dataset.exento === p));
    estado.ajustes.exentos = [...marcados("[data-exento]", "exento"), ...fuera];
    recordar({ nombre: ev.target.dataset.exento, exento: ev.target.checked });
    recalcular();
  }
  if (ev.target.matches("[data-pagado]")) {
    estado.ajustes.pagados = marcados("[data-pagado]", "pagado");
    recordar({ nombre: ev.target.dataset.pagado, pagado_habitual: ev.target.checked });
    recalcular();
  }
  if (ev.target.matches("[data-cupon]")) { estado.ajustes.cupones_empresa = marcados("[data-cupon]", "cupon"); recalcular(); }
});
/* lo que se marca en el paso 2 queda guardado para los meses siguientes */
async function recordar(cambio) {
  if (estado.ejemplo || !puede("operador")) return;
  try { estado.cfg.productos = (await postJSON("/api/config/productos", cambio)).productos; pintarCatalogo(); } catch { /* el cierre sigue igual */ }
}
function agregar(input, clave) {
  const nombre = input.value.trim();
  if (!estado.res.productos.includes(nombre)) { avisar("Elija un producto de la lista.", true); return; }
  const marcadosAhora = clave === "exentos"
    ? estado.res.exentos.filter((f) => f.marcado).map((f) => f.producto)
    : estado.res.pagados.filter((f) => f.marcado).map((f) => f.producto);
  estado.ajustes[clave] = [...new Set([...(estado.ajustes[clave] ?? marcadosAhora), nombre])];
  recordar(clave === "exentos" ? { nombre, exento: true } : { nombre, pagado_habitual: true });
  input.value = "";
  recalcular();
}
$("#btn-otro-exento").addEventListener("click", () => agregar($("#otro-exento"), "exentos"));
$("#btn-otro-pagado").addEventListener("click", () => agregar($("#otro-pagado"), "pagados"));

/* ---------- 3. declaracion ---------- */
function pintarDeclaracion(d) {
  const p = d.pasos, c = d.declaracion;
  const porPct = p.devoluciones_metodo === "porcentaje";
  const filas = [
    { c: "Ventas en efectivo y tarjeta", k: "ventas" },
    ...(porPct || !p.cupones_empresa_cuentan ? [] : [{ c: "Cupones que compró una empresa", k: "cupones_empresa" }, { c: "Ventas totales", k: "total", _clase: "fila-fuerte" }]),
    { c: porPct ? `Devoluciones a clientes, ${pct(p.devoluciones_pct)} de lo vendido` : "Cupones devueltos a clientes", k: "devoluciones", menos: true },
    { c: "Ventas netas", k: "neto", _clase: "fila-fuerte" },
    { c: "Agua", k: "agua", menos: true },
    { c: "Comprado con impuesto pagado", k: "walmart", menos: true },
    { c: "Ventas gravables", k: "gravable", _clase: "fila-fuerte" },
    ...Object.entries(d.reglas.jurisdicciones).flatMap(([n, j]) => [
      { c: `Máquinas de ${j.ciudades.join(", ")}: ventas netas`, k: `bruto_${n}` },
      { c: "Agua de esas máquinas", k: `agua_${n}`, menos: true },
      { c: "Comprado con impuesto pagado de esas máquinas", k: `pagadas_${n}`, menos: true },
      { c: `Base de ${j.nombre_comptroller}`, k: `base_${n}`, _clase: "fila-fuerte" },
    ]),
  ];
  tabla($("#tabla-cascada"), [
    { t: "", v: (f) => (f.menos ? "menos " : "") + f.c },
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
}

function pintarComparacion(d) {
  const c = d.comparacion;
  $("#res-comparar").hidden = !c;
  $("#btn-comparar").textContent = c ? "Cambiar Excel" : "Elegir Excel";
  if (!c) return;
  const v = d.verificacion?.comptroller;
  const declarado = v ? { "Ventas netas": v.total_ventas, "Ventas gravables": v.ventas_gravables, "Base de HOUSTON-CITY": v.houston, "Base de HOUSTON MTA": v.mta } : {};
  const cols = [
    { t: "", html: (f) => `<strong>${esc(f.concepto)}</strong>${f.causas.map((x) => `<span class="sub">${esc(x)}</span>`).join("")}` },
    { t: "Excel a mano", num: true, v: (f) => (f.original == null ? "" : dinero(f.original)) },
    { t: "Aplicación", num: true, v: (f) => dinero(f.app) },
    { t: "Diferencia", num: true, html: (f) => (f.dif == null ? "" : `<span class="${Math.abs(f.dif) < 0.005 ? "igual" : "distinto"}">${Math.abs(f.dif) < 0.005 ? "igual" : (f.dif > 0 ? "+" : "−") + dinero(Math.abs(f.dif))}</span>`) },
  ];
  if (v) cols.push({ t: "Declarado", num: true, v: (f) => (declarado[f.concepto] == null ? "" : dinero(declarado[f.concepto])) });
  tabla($("#tabla-comparar"), cols, c.filas);
  $("#nota-comparar").textContent = `${c.archivo}: ${c.iguales} de ${c.total} renglones iguales. Debajo de cada renglón distinto está la causa que se encontró en los datos.`;
}
$("#archivo-original").addEventListener("change", (ev) => {
  const archivo = ev.target.files[0];
  if (!archivo) return;
  if (!estado.codigo) { avisar("Primero suba los reportes del mes.", true); ev.target.value = ""; return; }
  ocupado($("#btn-comparar"), async () => {
    const fd = new FormData();
    fd.append("original", archivo);
    fd.append("ajustes", JSON.stringify(ajustes()));
    const d = await api(`/api/cierre/${estado.codigo}/comparar?anio=${estado.anio}&mes=${estado.mes}`, { method: "POST", body: fd });
    mostrar(d);
    avisar(`Comparado con ${archivo.name}.`);
  }).finally(() => { ev.target.value = ""; });
});

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

$("#btn-guardar-cierre").addEventListener("click", () => ocupado($("#btn-guardar-cierre"), async () => {
  let r;
  try { r = await postJSON(`/api/cierre/${estado.codigo}/guardar`, { anio: estado.anio, mes: estado.mes, ajustes: ajustes() }); }
  catch (e) { if (e.status === 410) { await volverASubir(); throw new Error("Se volvieron a leer los archivos. Intente de nuevo."); } throw e; }
  estado.cierres = r.cierres;
  pintarCierres();
  avisar(`Cierre de ${MESES[estado.mes - 1]} guardado en el historial.`);
  cargarConfig();
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
    if (estado.envio.aviso) avisar(estado.envio.aviso, true);
    if (estado.envio.cierre) cargarCierres();
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
  const marca = (ok) => `<span class="${ok ? "igual" : "distinto"}">${ok ? "igual" : "distinto"}</span>`;
  if (r.cuadre?.length) {
    tabla($("#tabla-qbo"), [
      { t: "Tasa", v: (f) => f.jurisdiccion },
      { t: "Porcentaje", num: true, v: (f) => pct(f.tasa) },
      { t: "Base en la aplicación", num: true, v: (f) => dinero(f.base_app) },
      { t: "Base en QuickBooks", num: true, v: (f) => dinero(f.base_qbo) },
      { t: "Impuesto en la aplicación", num: true, v: (f) => dinero(f.impuesto_app) },
      { t: "Impuesto en QuickBooks", num: true, v: (f) => dinero(f.impuesto_qbo) },
      { t: "", html: (f) => marca(f.igual) },
    ], r.cuadre, ["Total", "", "", "", dinero(r.cuadre.reduce((a, f) => a + f.impuesto_app, 0)), dinero(r.impuesto), ""]);
  } else {
    tabla($("#tabla-qbo"), [
      { t: "Tasa", v: (f) => f.jurisdiccion },
      { t: "Porcentaje", num: true, v: (f) => pct(f.tasa) },
      { t: "Taxable sales", num: true, v: (f) => dinero(f.base) },
      { t: "Impuesto", num: true, v: (f) => dinero(f.impuesto) },
    ], r.por_jurisdiccion, ["Total según QuickBooks", "", "", dinero(r.impuesto)]);
  }
  const c = estado.res?.declaracion;
  const comp = c ? ` El Comptroller redondea las bases a dólares enteros y calcula ${dinero(c.impuesto_total)}; la diferencia de centavos con QuickBooks es ese redondeo.` : "";
  $("#nota-qbo").textContent = `${r.creados} recibos creados y ${r.actualizados} actualizados. `
    + (r.cuadre?.length ? (r.cuadra ? "QuickBooks devolvió las mismas bases y el mismo impuesto que calculó la aplicación." : "Hay diferencias entre QuickBooks y la aplicación: revise las filas marcadas.") : "")
    + ` QuickBooks recibió ${dinero(r.gravable)} como taxable sales y ${dinero(r.exento)} como nontaxable sales.` + comp
    + (r.productos?.en_quickbooks ? ` Las reglas quedaron en QuickBooks: ${entero(r.productos.en_quickbooks)} productos como items, el agua marcada como no gravable`
      + (r.productos.creados || r.productos.cambiados ? ` (${r.productos.creados} creados y ${r.productos.cambiados} con la marca corregida en este envío)` : "")
      + ", y las devoluciones como un renglón de cada recibo." : "");
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

/* ---------- configuracion ---------- */
async function cargarConfig() {
  estado.cfg = await api("/api/config");
  estado.reglas = estado.cfg.reglas;
  pintarConfig();
}
const lista = (t) => t.split(",").map((x) => x.trim()).filter(Boolean);
const soloAdmin = () => (puede("admin") ? "" : "disabled");
const soloOperador = () => (puede("operador") ? "" : "disabled");

function filaJur(nombre, j) {
  return `<tr>
    <td><input type="text" data-j="nombre" value="${esc(nombre)}" placeholder="Sugar Land" aria-label="Nombre" ${soloAdmin()}></td>
    <td><input type="text" data-j="nombre_comptroller" value="${esc(j.nombre_comptroller || "")}" placeholder="SUGAR LAND-CITY" aria-label="Nombre en el Comptroller" ${soloAdmin()}></td>
    <td><input type="text" data-j="codigo" value="${esc(j.codigo || "")}" placeholder="2079060" aria-label="Código" ${soloAdmin()}></td>
    <td class="num"><input type="number" data-j="tasa" value="${esc(j.tasa ?? 1)}" min="0" max="30" step="0.01" aria-label="Tasa" ${soloAdmin()}></td>
    <td><input type="text" data-j="ciudades" value="${esc((j.ciudades || []).join(", "))}" placeholder="Ciudades, separadas por coma" aria-label="Ciudades" ${soloAdmin()}></td>
    <td>${puede("admin") ? `<button class="enlace" type="button" data-jur-quitar>Quitar</button>` : ""}</td>
  </tr>`;
}
function verCamposDev() {
  const porPct = $("#cfg-dev").value === "porcentaje";
  $("#cfg-pct-campo").hidden = !porPct;
  $("#cfg-cupones-campo").hidden = porPct;
}
$("#cfg-dev").addEventListener("change", verCamposDev);
$("#btn-jur-nueva").addEventListener("click", () => {
  $("#tabla-jur tbody").insertAdjacentHTML("beforeend", filaJur("", { tasa: 1, ciudades: [] }));
  $("#tabla-jur tbody tr:last-child input").focus();
});
document.addEventListener("click", (ev) => { ev.target.closest("[data-jur-quitar]")?.closest("tr").remove(); });

function pintarConfig() {
  const c = estado.cfg; if (!c) return;
  const R = c.reglas;
  const a = c.almacen;
  $("#aviso-almacen").hidden = a.persistente;
  $("#aviso-almacen p").textContent = "Esta instalación guarda la configuración en un archivo temporal: se pierde cuando el servidor se reinicia. Para que quede fija hay que conectarle una base de datos PostgreSQL (variable DATABASE_URL).";
  $("#cfg-estado").value = R.tasa_estado;
  $("#cfg-descuento").value = R.descuento_a_tiempo_pct;
  $("#tabla-jur").innerHTML = `<thead><tr><th>Jurisdicción</th><th>Nombre en el Comptroller</th><th>Código</th><th class="num">Tasa %</th><th>Ciudades</th><th></th></tr></thead>
    <tbody>${Object.entries(R.jurisdicciones).map(([n, j]) => filaJur(n, j)).join("")}</tbody>`;
  $("#cfg-dev").value = R.devoluciones.metodo;
  $("#cfg-pct").value = R.devoluciones.porcentaje;
  $("#cfg-cupones").value = R.cupones_empresa_minimo;
  $("#cfg-cupones-empresas").value = (R.cupones_empresas || []).join(", ");
  $("#cfg-cupones-cuentan").value = R.cupones_empresa_cuentan ? "si" : "no";
  $("#cfg-agua").value = R.agua_palabras.join(", ");
  $("#cfg-agua-no").value = R.agua_excepciones.join(", ");
  $("#cfg-destino").value = R.contabilidad.destino;
  $("#cfg-cuenta").value = R.contabilidad.cuenta;
  $("#cfg-cliente").value = R.contabilidad.cliente;
  $("#cfg-desde").value = `${estado.anio}-${String(estado.mes).padStart(2, "0")}`;
  $("#cfg-nota").value = "";
  $$("#form-reglas input, #form-reglas select").forEach((el) => { if (!el.closest(".guardar-reglas")) el.disabled = !puede("admin"); });
  verCamposDev();
  const v = R._version;
  $("#cfg-version").textContent = v ? `Reglas vigentes: aplican desde ${v.desde}, guardadas por ${v.por || "la instalación"} el ${fecha(v.creado)}. Hay ${c.versiones.length} versiones guardadas.` : "";
  pintarCatalogo(); pintarSugerencias(); pintarCfgMaquinas(); pintarFormatos(); pintarUsuarios(); pintarBitacora();
}

function reglasDelFormulario() {
  const jur = {};
  $$("#tabla-jur tbody tr").forEach((tr) => {
    const v = (k) => tr.querySelector(`[data-j="${k}"]`).value.trim();
    if (!v("nombre")) return;
    jur[v("nombre")] = { nombre_comptroller: v("nombre_comptroller") || v("nombre"), codigo: v("codigo"), tasa: +v("tasa"), ciudades: lista(v("ciudades")) };
  });
  return {
    tasa_estado: +$("#cfg-estado").value, tasa_compras: +$("#cfg-estado").value,
    descuento_a_tiempo_pct: +$("#cfg-descuento").value || 0,
    cupones_empresa_minimo: +$("#cfg-cupones").value || 0, cupones_empresas: lista($("#cfg-cupones-empresas").value),
    cupones_empresa_cuentan: $("#cfg-cupones-cuentan").value === "si",
    devoluciones: { metodo: $("#cfg-dev").value, porcentaje: +$("#cfg-pct").value || 0 },
    agua_palabras: lista($("#cfg-agua").value), agua_excepciones: lista($("#cfg-agua-no").value),
    jurisdicciones: jur,
    contabilidad: { destino: $("#cfg-destino").value, cuenta: $("#cfg-cuenta").value, cliente: $("#cfg-cliente").value },
  };
}
$("#form-reglas").addEventListener("submit", (ev) => {
  ev.preventDefault();
  ocupado(ev.submitter || $("#form-reglas button[type=submit]"), async () => {
    const r = await postJSON("/api/config/reglas", { reglas: reglasDelFormulario(), desde: $("#cfg-desde").value, nota: $("#cfg-nota").value });
    avisar("Reglas guardadas.");
    await cargarEstado();
    await cargarConfig();
    if (estado.codigo) { estado.ajustes.cupones_empresa = null; estado.envio = null; recalcular(); }
    if (estado.conectado && r.reglas.contabilidad.destino === "quickbooks") {
      try {
        const t = await api("/api/quickbooks/tasas"); estado.tasas = t.tasas; pintarComo();
        const st = t.catalogo.sin_tocar?.length || 0;
        avisar(`Las reglas nuevas se migraron a QuickBooks: ${Object.keys(t.tasas).length} códigos de impuesto y ${t.catalogo.en_quickbooks} productos, ${t.catalogo.agua} de ellos agua sin impuesto.`
          + (st ? ` ${st} productos que la empresa ya tenía con otra marca no se tocaron; en los recibos de la aplicación igual salen con la regla correcta.` : ""));
      }
      catch (e) { avisar(`Las reglas se guardaron, pero QuickBooks no se pudo actualizar: ${e.message}`, true); }
    }
  });
});

/* productos */
function pintarCatalogo() {
  const el = $("#tabla-catalogo"); if (!el || !estado.cfg) return;
  const q = ($("#prod-nuevo")?.value || "").trim().toLowerCase();
  const todas = Object.entries(estado.cfg.productos).map(([nombre, p]) => ({ nombre, ...p })).sort((a, b) => a.nombre.localeCompare(b.nombre));
  const filas = todas.filter((f) => !q || f.nombre.toLowerCase().includes(q));
  if (!filas.length) { el.innerHTML = `<tbody><tr><td>Todavía no hay productos clasificados a mano. Se guardan solos cuando se marcan en el paso 2.</td></tr></tbody>`; return; }
  tabla(el, [
    { t: "Producto", html: (f) => `${esc(f.nombre)}${f.otros_nombres?.length ? `<span class="sub">También: ${f.otros_nombres.map((o) => `${esc(o)} <button class="enlace" data-separar="${esc(o)}">separar</button>`).join(" · ")}</span>` : ""}` },
    { t: "Impuesto", html: (f) => `<select data-cat="${esc(f.nombre)}" aria-label="Impuesto de ${esc(f.nombre)}" ${soloOperador()}>
        <option value="auto" ${f.exento == null ? "selected" : ""}>Automático: ${f.regla_agua ? "agua, sin impuesto" : "con impuesto"}</option>
        <option value="exento" ${f.exento === true ? "selected" : ""}>Sin impuesto (agua)</option>
        <option value="gravable" ${f.exento === false ? "selected" : ""}>Con impuesto</option></select>` },
    { t: "Se compra por fuera", html: (f) => `<input type="checkbox" data-cat-pag="${esc(f.nombre)}" ${f.pagado_habitual ? "checked" : ""} ${soloOperador()} aria-label="Se compra por fuera: ${esc(f.nombre)}">` },
    { t: "Último cambio", html: (f) => `${esc(f.por || "")}<span class="sub">${esc(fecha(f.actualizado))}</span>` },
  ], filas, ["", "", "", `${filas.length} de ${todas.length} productos`]);
}
async function clasificar(cambio) {
  try {
    estado.cfg.productos = (await postJSON("/api/config/productos", cambio)).productos;
    pintarCatalogo();
    if (estado.codigo) { estado.ajustes.exentos = null; estado.ajustes.pagados = null; recalcular(); }
  } catch (e) { avisar(e.message, true); }
}
document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.matches("[data-cat]")) clasificar(t.value === "auto" ? { nombre: t.dataset.cat, automatico: true } : { nombre: t.dataset.cat, exento: t.value === "exento" });
  if (t.matches("[data-cat-pag]")) clasificar({ nombre: t.dataset.catPag, pagado_habitual: t.checked });
});
$("#prod-nuevo").addEventListener("input", pintarCatalogo);
$("#btn-prod-nuevo").addEventListener("click", () => {
  const nombre = $("#prod-nuevo").value.trim();
  if (!nombre) { avisar("Escriba el nombre del producto.", true); return; }
  $("#prod-nuevo").value = "";
  clasificar({ nombre, exento: true });
});

/* nombres del mismo producto */
function pintarSugerencias() {
  const el = $("#tabla-sugerencias"); if (!el || !estado.cfg) return;
  const S = estado.cfg.sugerencias_nombres || [];
  if (!S.length) { el.innerHTML = `<tbody><tr><td>No hay nombres por revisar. Suba los reportes de un mes para ver sugerencias.</td></tr></tbody>`; return; }
  tabla(el, [
    { t: "Nombre en un sistema", v: (f) => f.alias },
    { t: "Parece el mismo que", html: (f) => `<strong>${esc(f.producto)}</strong>` },
    { t: "", html: (f) => (puede("operador") ? `<button class="enlace" data-unir="${esc(f.alias)}" data-a="${esc(f.producto)}">Unir</button> <button class="enlace" data-distinto="${esc(f.alias)}" data-a="${esc(f.producto)}">No es el mismo</button>` : "") },
  ], S, ["", `${S.length} por revisar`, ""]);
}
document.addEventListener("click", async (ev) => {
  const u = ev.target.closest("[data-unir], [data-distinto], [data-separar]");
  if (!u) return;
  try {
    if (u.dataset.separar !== undefined) await postJSON("/api/config/equivalencias/separar", { alias: u.dataset.separar, producto: "" });
    else await postJSON("/api/config/equivalencias", { alias: u.dataset.unir ?? u.dataset.distinto, producto: u.dataset.a, unir: u.dataset.unir !== undefined });
    await cargarConfig();
    if (estado.codigo) recalcular();
  } catch (e) { avisar(e.message, true); }
});

/* maquinas */
function jurisdiccionDe(ciudad) {
  const c = String(ciudad || "").toLowerCase();
  const hallada = Object.entries(estado.reglas.jurisdicciones).find(([, j]) => j.ciudades.some((x) => x.toLowerCase() === c));
  return hallada ? hallada[1].nombre_comptroller : "Solo estado";
}
function pintarCfgMaquinas() {
  const el = $("#tabla-cfg-maquinas"); if (!el || !estado.cfg) return;
  const q = $("#buscar-cfg-maquina").value.trim().toLowerCase();
  const filas = estado.cfg.maquinas.filter((m) => !q || `${m.id_maquina} ${m.locacion} ${m.ciudad} ${m.direccion}`.toLowerCase().includes(q));
  if (!estado.cfg.maquinas.length) { el.innerHTML = `<tbody><tr><td>Todavía no hay máquinas guardadas. Suba el vendor list aquí o en el paso 1.</td></tr></tbody>`; return; }
  tabla(el, [
    { t: "Máquina", html: (f) => `<strong>${esc(f.id_maquina)}</strong><span class="sub">${esc(f.locacion || "")}</span>` },
    { t: "Dirección", v: (f) => f.direccion || "" },
    { t: "Ciudad", html: (f) => `<input type="text" data-maq-ciudad="${esc(f.id_maquina)}" value="${esc(f.ciudad || "")}" aria-label="Ciudad de la máquina ${esc(f.id_maquina)}" ${soloOperador()}>` },
    { t: "Impuesto local", v: (f) => jurisdiccionDe(f.ciudad) },
    { t: "Activa", html: (f) => `<input type="checkbox" data-maq-activa="${esc(f.id_maquina)}" ${f.activa ? "checked" : ""} ${soloOperador()} aria-label="Activa: máquina ${esc(f.id_maquina)}">` },
  ], filas, ["", "", "", "", `${filas.length} de ${estado.cfg.maquinas.length}`]);
}
$("#buscar-cfg-maquina").addEventListener("input", pintarCfgMaquinas);
document.addEventListener("change", async (ev) => {
  const t = ev.target;
  const id = t.dataset.maqCiudad ?? t.dataset.maqActiva;
  if (id === undefined) return;
  try {
    const cambio = t.dataset.maqCiudad !== undefined ? { ciudad: t.value } : { activa: t.checked };
    estado.cfg.maquinas = (await postJSON(`/api/config/maquinas/${encodeURIComponent(id)}`, cambio)).maquinas;
    pintarCfgMaquinas();
    avisar(`Máquina ${id} actualizada. Vuelva a unir las ventas para que el cierre la tome.`);
  } catch (e) { avisar(e.message, true); }
});
$("#archivo-maquinas").addEventListener("change", async (ev) => {
  const archivo = ev.target.files[0]; if (!archivo) return;
  const fd = new FormData(); fd.append("lista", archivo);
  try {
    const r = await api("/api/config/maquinas", { method: "POST", body: fd });
    estado.cfg.maquinas = r.maquinas;
    pintarCfgMaquinas();
    avisar(`${r.total} máquinas guardadas: ${r.nuevas} nuevas y ${r.cambiadas} con cambios.`);
    cargarEstado();
  } catch (e) { avisar(e.message, true); }
  ev.target.value = "";
});

/* usuarios */
const PERMISOS = [
  { a: "Ver el historial de cierres y la configuración", consulta: true, operador: true, admin: true },
  { a: "Subir reportes, hacer el cierre y descargar el Excel", operador: true, admin: true },
  { a: "Clasificar productos, editar máquinas y registrar sistemas", operador: true, admin: true },
  { a: "Enviar el cierre a contabilidad y marcarlo como declarado", operador: true, admin: true },
  { a: "Cambiar tasas, jurisdicciones, devoluciones y contabilidad", admin: true },
  { a: "Conectar QuickBooks y manejar los usuarios", admin: true },
];
function pintarUsuarios() {
  if (!estado.cfg || !puede("admin")) return;
  const R = estado.roles, U = estado.cfg.usuarios;
  $("#usr-rol").innerHTML = Object.entries(R).map(([k, v]) => `<option value="${k}" ${k === (U.length ? "operador" : "admin") ? "selected" : ""}>${esc(v)}</option>`).join("");
  $("#guia-usuarios").textContent = U.length
    ? "Cada persona entra con su usuario y solo puede hacer lo que su rol permite."
    : "Todavía no hay usuarios: cualquiera que abra la página puede cambiar todo. Cree primero un administrador; desde ese momento la página pide usuario y clave.";
  const opciones = (rol) => Object.entries(R).map(([k, v]) => `<option value="${k}" ${k === rol ? "selected" : ""}>${esc(v)}</option>`).join("");
  if (U.length) {
    tabla($("#tabla-usuarios"), [
      { t: "Nombre", html: (f) => `<strong>${esc(f.nombre)}</strong><span class="sub">${esc(f.usuario)}</span>` },
      { t: "Rol", html: (f) => `<select data-usr-rol="${f.id}" aria-label="Rol de ${esc(f.nombre)}">${opciones(f.rol)}</select>` },
      { t: "Activo", html: (f) => `<input type="checkbox" data-usr-activo="${f.id}" ${f.activo ? "checked" : ""} aria-label="Activo: ${esc(f.nombre)}">` },
    ], U);
  } else { $("#tabla-usuarios").innerHTML = ""; }
  const si = (x) => (x ? `<span class="igual">Sí</span>` : "");
  tabla($("#tabla-roles"), [
    { t: "Qué puede hacer", v: (f) => f.a },
    ...["consulta", "operador", "admin"].map((k) => ({ t: R[k], html: (f) => si(f[k]) })),
  ], PERMISOS);
}
document.addEventListener("change", async (ev) => {
  const t = ev.target;
  const id = t.dataset.usrRol ?? t.dataset.usrActivo;
  if (id === undefined) return;
  try {
    await postJSON(`/api/config/usuarios/${id}`, t.dataset.usrRol !== undefined ? { rol: t.value } : { activo: t.checked });
    avisar("Usuario actualizado.");
    await cargarConfig(); return;
  } catch (e) { avisar(e.message, true); }
  pintarUsuarios();
});
$("#form-usuario").addEventListener("submit", (ev) => {
  ev.preventDefault();
  ocupado(ev.submitter, async () => {
    const r = await postJSON("/api/config/usuarios", { nombre: $("#usr-nombre").value, usuario: $("#usr-usuario").value, clave: $("#usr-clave").value, rol: $("#usr-rol").value });
    ev.target.reset();
    if (r.primero) { avisar("Administrador creado. Entre con ese usuario."); await iniciar(); return; }
    await cargarConfig();
    avisar("Usuario creado.");
  });
});

function pintarBitacora() {
  if (!estado.cfg) return;
  tabla($("#tabla-bitacora"), [
    { t: "Cuándo", v: (f) => fecha(f.fecha) },
    { t: "Quién", v: (f) => f.usuario || "" },
    { t: "Qué hizo", html: (f) => `<strong>${esc(f.accion)}</strong>${f.detalle ? `<span class="sub">${esc(f.detalle)}</span>` : ""}` },
  ], estado.cfg.bitacora);
  if (!estado.cfg.bitacora.length) $("#tabla-bitacora").innerHTML = `<tbody><tr><td>Todavía no hay cambios registrados.</td></tr></tbody>`;
}

/* ---------- historial de cierres ---------- */
const ESTADOS = { guardado: ["Guardado", "estado-revisar"], enviado: ["Enviado a contabilidad", "estado-impuesto"], declarado: ["Declarado", "estado-ok"] };
async function cargarCierres() {
  estado.cierres = (await api("/api/cierres")).cierres;
  pintarCierres();
}
function pintarCierres() {
  const C = estado.cierres || [];
  if (!C.length) { $("#tabla-cierres").innerHTML = `<tbody><tr><td>Todavía no hay cierres guardados. Se guardan desde el paso 3, o solos al enviar a contabilidad.</td></tr></tbody>`; return; }
  tabla($("#tabla-cierres"), [
    { t: "Mes", html: (f) => `<strong>${MESES[f.mes - 1][0].toUpperCase() + MESES[f.mes - 1].slice(1)} ${f.anio}</strong><span class="sub">${esc(f.por || "")} · ${esc(fecha(f.guardado))}</span>` },
    { t: "Estado", html: (f) => `<span class="estado ${ESTADOS[f.estado][1]}">${ESTADOS[f.estado][0]}</span>` },
    { t: "Ventas netas", num: true, v: (f) => dinero(f.total_ventas) },
    { t: "Gravables", num: true, v: (f) => dinero(f.ventas_gravables) },
    { t: "Impuesto", num: true, v: (f) => dinero(f.impuesto) },
    { t: "En contabilidad", num: true, html: (f) => (f.impuesto_contabilidad == null ? "" : `${dinero(f.impuesto_contabilidad)}<span class="sub ${f.cuadra ? "igual" : "distinto"}">${f.cuadra ? "cuadra" : "no cuadra"}</span>`) },
    { t: "", html: (f) => `<button class="enlace" data-ver-cierre="${f.id}">Ver</button>${puede("operador") ? ` <button class="enlace" data-estado-cierre="${f.id}" data-nuevo="${f.estado === "declarado" ? "guardado" : "declarado"}">${f.estado === "declarado" ? "Reabrir" : "Marcar declarado"}</button>` : ""}` },
  ], C);
}
document.addEventListener("click", async (ev) => {
  const ver = ev.target.closest("[data-ver-cierre]");
  const est = ev.target.closest("[data-estado-cierre]");
  try {
    if (est) {
      estado.cierres = (await postJSON(`/api/cierres/${est.dataset.estadoCierre}/estado`, { estado: est.dataset.nuevo })).cierres;
      pintarCierres();
      avisar(est.dataset.nuevo === "declarado" ? "Cierre marcado como declarado." : "Cierre reabierto.");
    }
    if (ver) {
      const c = await api(`/api/cierres/${ver.dataset.verCierre}`);
      const p = c.resumen, d = c.declaracion;
      $("#detalle-cierre").hidden = false;
      $("#titulo-detalle").textContent = `Cierre de ${MESES[c.mes - 1]} ${c.anio}`;
      const fila = (t, k) => ({ t, v: p[k]?.total });
      tabla($("#tabla-detalle"), [{ t: "", v: (f) => f.t }, { t: "Valor", num: true, v: (f) => dinero(f.v) }], [
        fila("Ventas en efectivo y tarjeta", "ventas"), fila("Devoluciones a clientes", "devoluciones"), fila("Ventas netas", "neto"),
        fila("Agua", "agua"), fila("Comprado con impuesto pagado", "walmart"), fila("Ventas gravables", "gravable"),
        ...d.locales.map((l) => ({ t: `Base de ${l.nombre_comptroller} (${pct(l.tasa)})`, v: l.base_exacta ?? l.base })),
        { t: "Impuesto según el Comptroller", v: d.impuesto_total },
      ]);
      const dev = c.reglas.devoluciones;
      $("#nota-detalle").textContent = `Reglas de ese cierre: estado ${pct(c.reglas.tasa_estado)}, devoluciones ${dev.metodo === "porcentaje" ? `al ${pct(dev.porcentaje)}` : "por cupones"}. `
        + `Archivos: ${c.archivos.map((a) => `${a.fuente} (${a.archivo})`).join(", ")}.`;
      tabla($("#tabla-detalle-maquinas"), [
        { t: "Máquina", html: (f) => `<strong>${esc(f.id_maquina)}</strong><span class="sub">${esc(f.maquina)}</span>` },
        { t: "Ciudad", v: (f) => f.ciudad }, { t: "Impuesto local", v: (f) => f.jurisdiccion },
        { t: "Ventas", num: true, v: (f) => dinero(f.ventas) }, { t: "Gravable", num: true, v: (f) => dinero(f.gravable) },
      ], c.maquinas.sort((a, b) => (+a.id_maquina || 0) - (+b.id_maquina || 0)));
      $("#detalle-cierre").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (e) { avisar(e.message, true); }
});

/* ---------- como funciona ---------- */
function pintarComo() {
  const R = estado.reglas; if (!R) return;

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
    { p: "Restar las devoluciones a clientes", antes: "3 % fijo en una fórmula", quien: "La aplicación, con los cupones o con el porcentaje", c: "estado-ok" },
    { p: "Comprobar que QuickBooks dio lo mismo", antes: "No se hacía", quien: "La aplicación", c: "estado-ok" },
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
  const J = R.jurisdicciones;
  tabla($("#tabla-tasas"), [
    { t: "Tasa en QuickBooks", v: (f) => f.n },
    { t: "Se arma con", v: (f) => f.d },
    { t: "Se aplica a", v: (f) => f.a },
    { t: "Id", v: (f) => tasas[f.k] || "" },
  ], [
    ...Object.entries(J).map(([k, j]) => ({ k, n: `EzSnack ${k}`, d: `${pct(R.tasa_estado)} estado + ${pct(j.tasa)} ${j.nombre_comptroller}`, a: j.ciudades.join(", ") })),
    { k: "Solo estado", n: "EzSnack Solo estado", d: `${pct(R.tasa_estado)} estado`, a: "Las demás ciudades" },
  ]);
  $("#nota-tasas").textContent = estado.tasas
    ? `Creadas en ${estado.empresa}. Se ven en QuickBooks, en Sales Tax, Sales tax settings.`
    : "Conecte QuickBooks y envíe un cierre para ver los identificadores de estas tasas.";

  dosCol($("#tabla-tecnica"), [
    { a: "<strong>Servidor</strong>", b: "Python con FastAPI. Los archivos se leen en memoria con pandas y openpyxl, y se borran a las tres horas." },
    { a: "<strong>Base de datos</strong>", b: `${esc(estado.almacen?.motor || "")}. Guarda las reglas con su historial, las máquinas, los productos clasificados, los sistemas registrados, los usuarios y cada cierre. Los archivos de ventas no se guardan.` },
    { a: "<strong>Autorización</strong>", b: "OAuth 2. La página manda al usuario a Intuit, Intuit devuelve un código y el servidor lo cambia por un token de acceso y uno de refresco." },
    { a: "<strong>Dónde quedan los tokens</strong>", b: "Cifrados en una cookie del navegador de cada usuario, no en el servidor. Cada quien ve solo la empresa que autorizó." },
    { a: "<strong>Renovación</strong>", b: "El token de acceso dura una hora. Cuando vence, el servidor lo renueva con el de refresco y vuelve a intentar la llamada." },
    { a: "<strong>API</strong>", b: "Accounting API v3. Consultas con el lenguaje de Intuit y creación de los recibos en lotes de 25 con el endpoint batch." },
    { a: "<strong>Entorno</strong>", b: `Sandbox mientras la aplicación use las llaves de desarrollo. Para la empresa real hay que pasar la revisión de Intuit.` },
  ], ["", ""]);
}

/* ---------- inicio ---------- */
const q = new URLSearchParams(location.search);
if (q.get("conexion") === "ok") avisar(q.get("reglas") === "ok"
  ? "Conectado. Las reglas de impuestos se migraron a QuickBooks: códigos de impuesto por jurisdicción y cada producto con su marca de gravable."
  : "Conectado a QuickBooks.");
if (q.get("conexion") === "cancelada") avisar("La conexión con QuickBooks se canceló.", true);
if (q.get("conexion") === "invalida") avisar("La conexión venció. Inténtelo de nuevo.", true);
if (q.has("conexion")) history.replaceState(null, "", "/");
async function iniciar() {
  // la comparacion con el Excel hecho a mano es una herramienta del equipo, no del gerente
  $("#bloque-comparar").hidden = !new URLSearchParams(location.search).has("interno");
  if (!(await cargarEstado())) return;
  await cargarConfig();
  await cargarCierres();
  // los sistemas que antes se guardaban en este navegador pasan a la base de la empresa
  try {
    const viejos = JSON.parse(localStorage.getItem("ezsnack_formatos") || "[]");
    if (viejos.length && puede("operador")) {
      for (const f of viejos) await postJSON("/api/config/formatos", f).catch(() => {});
      localStorage.removeItem("ezsnack_formatos");
      localStorage.removeItem("ezsnack_reglas");
      await cargarConfig();
    }
  } catch { /* sin almacenamiento */ }
  if (!puede("operador")) ir("historial");
  if (estado.conectado && puede("operador") && estado.reglas.contabilidad.destino === "quickbooks") {
    api("/api/quickbooks/tasas").then((d) => { estado.tasas = d.tasas; pintarComo(); }).catch(() => {});
  }
}
iniciar().catch((e) => avisar(e.message, true));
