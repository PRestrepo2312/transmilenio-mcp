// datos fijos
const SISTEMAS = {
  "Troncal": { c: "#d7141a", orden: 5 },
  "TransMiCable": { c: "#00999a", orden: 6 },
  "Dual": { c: "#e89a00", orden: 4, oscura: true },
  "Alimentador": { c: "#2e9e3e", orden: 3 },
  "Zonal complementario": { c: "#f26b21", orden: 2 },
  "Zonal especial": { c: "#7b4bb7", orden: 1 },
  "Zonal": { c: "#1565c0", orden: 0 },
};
const ZOOM_ICONOS = 13.3;
const ESTILOS = {
  dia: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  noche: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
};
const ICONOS = {
  dia: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7z" fill="currentColor"/></svg>',
  noche: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3.2" fill="currentColor"/><path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3 3l1.1 1.1M11.9 11.9 13 13M3 13l1.1-1.1M11.9 4.1 13 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
};

const col = (s) => (SISTEMAS[s] || { c: "#8b949e" }).c;
// Íconos: bus de frente (troncal, zonal, alimentador, dual) y cabina para TransMiCable.
// Cuerpo blanco y ventanas del color del sistema, sobre una placa de ese color.
const GLIFO_BUS = '<rect x="5" y="2.5" width="14" height="15.5" rx="3" fill="#fff"/><rect x="7" y="5" width="10" height="6.5" rx="1.2" fill="{c}"/><circle cx="8.7" cy="14.7" r="1.25" fill="{c}"/><circle cx="15.3" cy="14.7" r="1.25" fill="{c}"/><rect x="7" y="17.4" width="3" height="3.4" rx="1" fill="#fff"/><rect x="14" y="17.4" width="3" height="3.4" rx="1" fill="#fff"/>';
const GLIFO_CABLE = '<path d="M2.5 5.5 21.5 2.5" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/><path d="M12 4v3.5" stroke="#fff" stroke-width="1.7"/><rect x="5.5" y="7.5" width="13" height="13" rx="3.5" fill="#fff"/><rect x="7.7" y="9.7" width="8.6" height="5" rx="1.2" fill="{c}"/>';
const glifo = (sistema) => (sistema === "TransMiCable" ? GLIFO_CABLE : GLIFO_BUS).replaceAll("{c}", col(sistema));
const iconoSvg = (sistema, px = 13) => `<svg width="${px}" height="${px}" viewBox="0 0 24 24" aria-hidden="true">${glifo(sistema)}</svg>`;

const ICONOS_MAPA = { dia: {}, noche: {} };
const iconosListos = Promise.all(["dia", "noche"].flatMap((t) => Object.keys(SISTEMAS).map(async (s) => {
  const borde = t === "noche" ? "#181b1f" : "#ffffff";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="56" height="56" viewBox="0 0 28 28"><rect x="1.2" y="1.2" width="25.6" height="25.6" rx="7" fill="${col(s)}" stroke="${borde}" stroke-width="2.2"/><g transform="translate(2 2)">${glifo(s)}</g></svg>`;
  const img = new Image(56, 56);
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  await img.decode();
  ICONOS_MAPA[t][s] = img;
})));
const fmt = new Intl.NumberFormat("es-CO");
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const placa = (codigo, sistema, cls = "") =>
  `<span class="placa ${cls} ${SISTEMAS[sistema]?.oscura ? "oscura" : ""}" style="background:${col(sistema)}">${iconoSvg(sistema, cls === "mediana" ? 17 : 13)}${esc(codigo)}</span>`;
const metros = (m) => (m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1).replace(".", ",")} km`);
const quieto = matchMedia("(prefers-reduced-motion: reduce)").matches;
const pareceRuta = (q) => /^[a-z]{0,3}\d{1,4}[a-z]?(-\d{1,3})?$/i.test(q.trim());
const minutos = (m) => (m < 1 ? "Llegando" : `${Math.round(m)} min`);

// tema día / noche
function temaInicial() {
  try { const t = localStorage.getItem("tema"); if (t === "dia" || t === "noche") return t; } catch (_) {}
  const h = Number(new Intl.DateTimeFormat("es-CO", { hour: "numeric", hourCycle: "h23", timeZone: "America/Bogota" }).format(new Date()));
  return h >= 18 || h < 6 ? "noche" : "dia";
}
let tema = temaInicial();
document.documentElement.dataset.tema = tema;
function botonTema() {
  $("tema").innerHTML = ICONOS[tema];
  const txt = tema === "noche" ? "Cambiar a modo día" : "Cambiar a modo noche";
  $("tema").setAttribute("aria-label", txt);
  $("tema").title = txt;
}
botonTema();

// estado
let buses = new Map();          // clave -> bus
let estacionesGeo = { type: "FeatureCollection", features: [] };
let yo = null;
let vista = { tipo: "inicio" };
let foco = null; // null | { variantes: Set } | { claves: Set(bus|placa) } | { bus: "numero|placa" }
let capa = { lineas: [], paradas: [], marca: null };  // lineas: [{coords:[[lat,lon]], color, o}]
let chips = new Map();          // clave -> maplibregl.Marker
let timerVista = null;
// Cada cambio de vista sube este número; una respuesta que llega tarde de una vista
// anterior lo compara y se descarta en vez de pintar encima de la actual.
let vistaId = 0;
let ultimoAviso = null;
let iniciado = false;

const map = new maplibregl.Map({
  container: "map", style: ESTILOS[tema], center: [-74.1, 4.655], zoom: 11, attributionControl: false,
});
map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Buses: TransMilenio S.A." }), "bottom-right");
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
// En celular la atribución arranca cerrada (botón i) para no tapar el mapa.
if (innerWidth <= 680) map.once("load", () => document.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show"));

// Cada vez que cambia el mapa base (día/noche) se vuelven a montar las capas propias.
map.on("style.load", async () => {
  await iconosListos;
  agregarCapas();
  if (!iniciado) {
    iniciado = true;
    map.fitBounds([[-74.22, 4.47], [-74.01, 4.83]], { padding: pad(24), duration: 0 });
    pintarVista();
    cargarEstaciones();
    cargarFlota();
    setInterval(cargarFlota, 15000);
  }
});

// Respaldo: si tras un cambio de estilo faltan las capas propias, se montan de nuevo.
map.on("styledata", () => {
  if (iniciado && map.isStyleLoaded() && !map.getSource("buses")) agregarCapas();
});

function agregarCapas() {
  if (map.getSource("buses")) return;
  const noche = tema === "noche";
  const vacio = { type: "FeatureCollection", features: [] };
  const borde = noche ? "#181b1f" : "#ffffff";
  map.addSource("trazado", { type: "geojson", data: vacio });
  map.addLayer({ id: "trazado-borde", type: "line", source: "trazado", layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": borde, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 6, 15, 11] } });
  map.addLayer({ id: "trazado", type: "line", source: "trazado", layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": ["get", "color"], "line-opacity": ["get", "o"], "line-width": ["interpolate", ["linear"], ["zoom"], 10, 3, 15, 6] } });
  map.addSource("paradas-ruta", { type: "geojson", data: vacio });
  map.addLayer({ id: "paradas-ruta", type: "circle", source: "paradas-ruta",
    paint: { "circle-color": borde, "circle-stroke-color": ["get", "color"], "circle-stroke-width": 2.5,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 3, 16, 6] } });

  map.addSource("estaciones", { type: "geojson", data: estacionesGeo });
  map.addLayer({ id: "estaciones", type: "circle", source: "estaciones", minzoom: 12,
    paint: { "circle-color": borde, "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 2.5, 16, 5],
      "circle-stroke-color": noche ? "#8b949e" : "#59636e", "circle-stroke-width": 1.2, "circle-opacity": 0.9, "circle-stroke-opacity": 0.9 } });

  for (const [s, img] of Object.entries(ICONOS_MAPA[tema])) {
    if (!map.hasImage("bus-" + s)) map.addImage("bus-" + s, img, { pixelRatio: 2 });
  }
  map.addSource("buses", { type: "geojson", data: vacio });
  // De lejos, puntos (la ciudad completa); de cerca, el ícono de cada bus.
  map.addLayer({ id: "buses", type: "circle", source: "buses", maxzoom: ZOOM_ICONOS, layout: { "circle-sort-key": ["get", "orden"] },
    paint: { "circle-color": ["get", "color"], "circle-stroke-color": borde,
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 10, 0.3, 13, 1] } });
  map.addLayer({ id: "buses-icono", type: "symbol", source: "buses", minzoom: ZOOM_ICONOS,
    layout: { "icon-image": ["concat", "bus-", ["get", "s"]], "icon-allow-overlap": true, "icon-ignore-placement": true,
      "symbol-sort-key": ["get", "orden"] } });

  map.addSource("marca", { type: "geojson", data: vacio });
  map.addLayer({ id: "marca", type: "circle", source: "marca",
    paint: { "circle-radius": 9, "circle-color": borde, "circle-stroke-color": noche ? "#e8eaed" : "#1f2328", "circle-stroke-width": 3 } });

  map.addSource("yo", { type: "geojson", data: vacio });
  map.addLayer({ id: "yo-halo", type: "circle", source: "yo", paint: { "circle-radius": 16, "circle-color": "rgba(11,98,196,0.18)" } });
  map.addLayer({ id: "yo", type: "circle", source: "yo",
    paint: { "circle-radius": 6.5, "circle-color": "#0b62c4", "circle-stroke-color": "#fff", "circle-stroke-width": 2.5 } });

  pintarCapas();
}

function pintarCapas() {
  if (!map.getSource("buses")) return;
  map.getSource("buses").setData(geoBuses());
  map.getSource("estaciones").setData(estacionesGeo);
  map.getSource("trazado").setData({ type: "FeatureCollection", features: capa.lineas.filter((l) => l.coords.length > 1).map((l) =>
    ({ type: "Feature", geometry: { type: "LineString", coordinates: l.coords.map(([la, lo]) => [lo, la]) }, properties: { color: l.color, o: l.o ?? 1 } })) });
  map.getSource("paradas-ruta").setData({ type: "FeatureCollection", features: capa.paradas.map((x) =>
    ({ type: "Feature", geometry: { type: "Point", coordinates: [x.lon, x.lat] }, properties: { color: x.color, nombre: x.nombre } })) });
  map.getSource("marca").setData(punto(capa.marca));
  map.getSource("yo").setData(punto(yo ? [yo.lon, yo.lat] : null));
  const hay = foco !== null;
  const dentro = ["==", ["get", "f"], 1];
  map.setPaintProperty("buses", "circle-opacity", hay ? ["case", dentro, 1, tema === "noche" ? 0.1 : 0.12] : 0.92);
  map.setPaintProperty("buses", "circle-radius", hay
    ? ["interpolate", ["linear"], ["zoom"], 10, ["case", dentro, 4.5, 1.5], ZOOM_ICONOS, ["case", dentro, 6, 2.5]]
    : ["interpolate", ["linear"], ["zoom"], 10, 2, ZOOM_ICONOS, 3.8]);
  map.setPaintProperty("buses-icono", "icon-opacity", hay ? ["case", dentro, 1, tema === "noche" ? 0.14 : 0.18] : 1);
  map.setLayoutProperty("buses-icono", "icon-size", hay
    ? ["interpolate", ["linear"], ["zoom"], ZOOM_ICONOS, ["case", dentro, 0.95, 0.55], 17, ["case", dentro, 1.25, 0.8]]
    : ["interpolate", ["linear"], ["zoom"], ZOOM_ICONOS, 0.72, 17, 1.1]);
  map.setPaintProperty("estaciones", "circle-opacity", hay ? 0.35 : 0.9);
  map.setPaintProperty("estaciones", "circle-stroke-opacity", hay ? 0.35 : 0.9);
}
const punto = (lngLat) => ({ type: "FeatureCollection", features: lngLat ? [{ type: "Feature", geometry: { type: "Point", coordinates: lngLat }, properties: {} }] : [] });

function enFoco(b) {
  if (!foco) return false;
  if (foco.variantes) return foco.variantes.has(b.variante);
  if (foco.bus) return b.k === foco.bus;
  return foco.claves.has(b.k);
}
function geoBuses() {
  const f = [];
  for (const b of buses.values()) {
    const dentro = enFoco(b);
    if (dentro && (foco.claves || foco.bus)) continue; // esos se dibujan como marcadores HTML
    f.push({ type: "Feature", geometry: { type: "Point", coordinates: [b.cLon, b.cLat] },
      properties: { k: b.k, s: b.sistema, color: col(b.sistema), f: dentro ? 1 : 0, orden: (SISTEMAS[b.sistema]?.orden ?? 0) + (dentro ? 10 : 0) } });
  }
  return { type: "FeatureCollection", features: f };
}

function cambiarTema() {
  tema = tema === "dia" ? "noche" : "dia";
  document.documentElement.dataset.tema = tema;
  try { localStorage.setItem("tema", tema); } catch (_) {}
  botonTema();
  // diff:false para que vuelva a disparar "style.load" y se monten de nuevo las capas propias.
  map.setStyle(ESTILOS[tema], { diff: false });
}

// flota
async function cargarFlota() {
  let d;
  try { d = await (await fetch("/api/flota")).json(); }
  catch (e) { estado("detenido", "Sin conexión con el servidor local"); return; }
  if (d.preparando) { estado("", "Preparando rutas y paradas (solo la primera vez)"); setTimeout(cargarFlota, 4000); return; }
  if (d.error) { estado("detenido", d.error); return; }
  const nuevos = new Map();
  for (const [lat, lon, ruta, destino, sistema, bus, placaV, ultima, hace, variante] of d.buses) {
    const k = bus + "|" + placaV, prev = buses.get(k);
    nuevos.set(k, { k, lat, lon, ruta, destino, sistema, bus, placa: placaV, ultima, hace, variante,
      dLat: prev ? prev.cLat : lat, dLon: prev ? prev.cLon : lon, cLat: prev ? prev.cLat : lat, cLon: prev ? prev.cLon : lon });
  }
  buses = nuevos;
  animar();
  resumen(d);
}

let anim = 0;
function animar() {
  const id = ++anim, t0 = performance.now(), dur = quieto ? 0 : 1400;
  const paso = () => {
    if (id !== anim) return;
    const f = dur ? Math.min(1, (performance.now() - t0) / dur) : 1;
    const e = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
    for (const b of buses.values()) { b.cLat = b.dLat + (b.lat - b.dLat) * e; b.cLon = b.dLon + (b.lon - b.dLon) * e; }
    map.getSource("buses")?.setData(geoBuses());
    for (const [k, m] of chips) { const b = buses.get(k); if (b) m.setLngLat([b.cLon, b.cLat]); }
    if (f < 1) setTimeout(() => requestAnimationFrame(paso), 40);
  };
  requestAnimationFrame(paso);
}

function estado(tipo, txt) { $("estado").className = "estado " + tipo; $("estado-txt").textContent = txt; }

function resumen(d) {
  const hora = d.ultimo_reporte
    ? new Date(d.ultimo_reporte).toLocaleTimeString("es-CO", { hour: "numeric", minute: "2-digit", timeZone: "America/Bogota" }) : "";
  ultimoAviso = d.aviso || null;
  if (d.aviso) estado("detenido", `TransMilenio no reporta desde las ${hora}`);
  else estado("vivo", `En vivo, actualizado hace ${d.edad_s ?? 0} s`);
  const conteo = {};
  for (const b of buses.values()) conteo[b.sistema] = (conteo[b.sistema] || 0) + 1;
  const orden = Object.entries(conteo).sort((a, b) => b[1] - a[1]);
  const barra = orden.map(([s, n]) => `<span style="width:${(n / buses.size) * 100}%;background:${col(s)}" title="${esc(s)}: ${fmt.format(n)}"></span>`).join("");
  $("barra").innerHTML = barra;
  $("hud-barra").innerHTML = barra;
  $("flota-txt").innerHTML = `<strong class="num">${fmt.format(buses.size)}</strong> buses en vía` +
    `<span class="leyenda">${orden.map(([s, n]) => `<span title="${esc(s)}"><span class="ico" style="background:${col(s)}">${iconoSvg(s, 12)}</span>${esc(s.replace("Zonal ", ""))} <span class="num">${fmt.format(n)}</span></span>`).join("")}</span>`;
  $("hud-total").textContent = fmt.format(buses.size);
  $("hud-hora").textContent = hora;
}

async function cargarEstaciones() {
  try {
    const d = await (await fetch("/api/estaciones")).json();
    if (d.preparando) { setTimeout(cargarEstaciones, 4000); return; }
    estacionesGeo = { type: "FeatureCollection", features: d.estaciones.map(([id, nombre, lat, lon]) =>
      ({ type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties: { id, nombre } })) };
    pintarCapas();
  } catch (_) {}
}

// vistas
function ir(v) { vista = v; vistaId++; clearTimeout(timerVista); pintarVista(); }
const traer = async (url) => (await fetch(url)).json();

function limpiarMapa() {
  foco = null; capa.lineas = []; capa.paradas = []; capa.marca = null;
  for (const m of chips.values()) m.remove();
  chips.clear();
  pintarCapas();
}

function pintarVista() {
  const el = $("vista");
  if (vista.tipo === "inicio") {
    limpiarMapa();
    el.innerHTML = `<p class="ayuda">Escribe el código de una ruta, como C25 o B10, para ver por dónde va y en qué sentido.
      O el nombre de una estación, como Calle 72, para ver qué buses vienen.</p>
      <p class="ayuda">Con tu ubicación te digo en cuánto pasa el bus por tu paradero.</p>`;
    return;
  }
  if (vista.tipo === "cerca") return vistaCerca(el);
  if (vista.tipo === "parada") return vistaParada(el);
  if (vista.tipo === "ruta") return vistaRuta(el);
  if (vista.tipo === "bus") return vistaBus(el);
}

const abrirBus = (bus, placaV) => ir({ tipo: "bus", bus, placa: placaV, volver: vista.tipo === "bus" ? vista.volver : { ...vista } });

// un bus: su recorrido como línea de tiempo
async function vistaBus(el, refresco = false) {
  const id = vistaId;
  if (!refresco) el.innerHTML = `<p class="ayuda">Cargando el recorrido del bus…</p>`;
  const d = await traer(`/api/bus?bus=${encodeURIComponent(vista.bus)}&placa=${encodeURIComponent(vista.placa || "")}`);
  if (id !== vistaId) return;
  if (d.preparando) { el.innerHTML = `<p class="ayuda">${esc(d.mensaje)}</p>`; return; }
  const volver = vista.volver && vista.volver.tipo !== "inicio"
    ? `<button class="enlace" id="volver" style="margin-top:12px">Volver</button>` : "";
  if (d.error) { el.innerHTML = `${volver}<p class="ayuda">${esc(d.error)} Puede que ya haya terminado su recorrido.</p>`; enlazarVolver(); return; }

  const c = col(d.sistema);
  const tarde = d.retraso_s > 120 ? ` Va ${Math.round(d.retraso_s / 60)} min tarde frente al horario.` : d.retraso_s < -120 ? ` Va ${Math.round(-d.retraso_s / 60)} min adelantado.` : "";
  const filas = [];
  for (const p of d.paradas) {
    const nombre = `<span class="r-nombre">${esc(p.nombre)}</span>${p.vagon && p.vagon !== p.nombre ? `<span class="r-vagon">${esc(p.vagon.replace(/[.\s]+$/, ""))}</span>` : ""}`;
    if (p.estado === "pasada") filas.push(`<li class="pasada"><div>${nombre}</div></li>`);
    if (p.estado === "ultima") {
      filas.push(`<li class="pasada ultima"><div>${nombre}</div><span class="r-hora">Pasó</span></li>`);
      filas.push(`<li class="aqui"><span class="r-bus" style="background:${c}">${iconoSvg(d.sistema, 14)}</span><div><span class="r-nombre">El bus va aquí</span><span class="r-vagon num">Reportó hace ${d.hace_s} s</span></div></li>`);
    }
    if (p.estado === "proxima") {
      filas.push(`<li class="proxima" data-lat="${p.lat}" data-lon="${p.lon}"><div>${nombre}</div><span class="r-hora num">${p.llega_en_min == null ? "Sin dato" : p.llega_en_min < 1 ? "Llegando" : `${Math.round(p.llega_en_min)} min`}<small>${esc(p.hora || "")}</small></span></li>`);
    }
  }
  el.innerHTML = `
    ${volver}
    <div class="ruta-cab">${placa(d.ruta, d.sistema, "mediana")}<div style="min-width:0">
      <div class="encabezado" style="margin:0">${esc(/^(Hacia|Regresa)/.test(d.sentido || "") ? d.sentido : `Hacia ${d.destino}`)}</div>
      <div class="sub">${esc(/^(Hacia|Regresa)/.test(d.sentido || "") ? `Ruta circular, termina en ${d.destino}` : (d.sentido ? `Sentido ${d.sentido}` : d.sistema))}</div></div></div>
    <p class="sub" style="margin-top:8px">${esc(d.sistema)}, bus ${esc(d.bus)}, placa ${esc(d.placa)}.${esc(tarde)}</p>
    ${avisoHtml()}
    ${d.aviso_bus ? `<p class="aviso">${esc(d.aviso_bus)}</p>` : ""}
    <ol class="recorrido" style="--c:${c}">${filas.join("")}</ol>
    <p class="sub" style="margin-top:10px">${esc(d.nota || "")}</p>
    <button class="enlace" id="ver-ruta">Ver todos los buses de la ruta ${esc(d.ruta)}</button>`;
  enlazarVolver();
  $("ver-ruta").addEventListener("click", () => { $("q").value = d.ruta; ir({ tipo: "ruta", ruta: d.ruta, sel: d.variante }); });
  el.querySelectorAll(".recorrido .proxima").forEach((li) => li.addEventListener("click", () =>
    map.easeTo({ center: [+li.dataset.lon, +li.dataset.lat], zoom: Math.max(map.getZoom(), 15), padding: pad(), duration: quieto ? 0 : 600 })));

  // Mapa: lo recorrido en gris, lo que falta en el color del sistema, y las paradas que vienen.
  const t = d.trazado || [], u = Math.max(0, d.indice_ultima ?? 0);
  const yaBus = [d.lat, d.lon];
  capa.lineas = [
    { coords: [...t.slice(0, u + 1), yaBus], color: tema === "noche" ? "#5c6570" : "#a8b0ba", o: 0.9 },
    { coords: [yaBus, ...t.slice(u + 1)], color: c },
  ];
  capa.paradas = d.paradas.filter((p) => p.estado === "proxima").map((p) => ({ lat: p.lat, lon: p.lon, color: c, nombre: p.nombre }));
  capa.marca = null;
  for (const m of chips.values()) m.remove();
  chips.clear();
  foco = { bus: d.bus + "|" + d.placa };
  const sel = document.createElement("div");
  sel.className = "bus-sel";
  sel.style.background = c;
  sel.innerHTML = iconoSvg(d.sistema, 20);
  const bb = buses.get(foco.bus);
  chips.set(foco.bus, new maplibregl.Marker({ element: sel }).setLngLat(bb ? [bb.cLon, bb.cLat] : [d.lon, d.lat]).addTo(map));
  pintarCapas();
  if (!refresco) {
    const caja = new maplibregl.LngLatBounds([d.lon, d.lat], [d.lon, d.lat]);
    d.paradas.filter((p) => p.estado === "proxima").slice(0, 10).forEach((p) => caja.extend([p.lon, p.lat]));
    map.fitBounds(caja, { padding: pad(70), maxZoom: 15.5, duration: quieto ? 0 : 800 });
  }
  timerVista = setTimeout(() => id === vistaId && vistaBus(el, true), 15000);

  function enlazarVolver() { $("volver")?.addEventListener("click", () => ir(vista.volver)); }
}

const avisoHtml = () => (ultimoAviso ? `<p class="aviso">${esc(ultimoAviso)}</p>` : "");

// cerca de mí
async function vistaCerca(el) {
  const id = vistaId;
  limpiarMapa();
  el.innerHTML = `<p class="encabezado">Cerca de ti</p><p class="sub">Buscando paraderos…</p>`;
  const d = await traer(`/api/cerca?lat=${yo.lat}&lon=${yo.lon}&radio=900`);
  if (id !== vistaId) return;
  if (d.preparando) { el.innerHTML = `<p class="ayuda">${esc(d.mensaje)}</p>`; return; }
  if (!d.paradas?.length) {
    el.innerHTML = `<p class="encabezado">Cerca de ti</p><p class="ayuda">No hay paraderos con servicio a menos de 900 m. Busca tu estación por nombre.</p>`;
    return;
  }
  el.innerHTML = `<p class="encabezado">Cerca de ti</p><p class="sub">Elige tu paradero para ver qué buses vienen.</p>
    <ul class="lista">${d.paradas.map((p) => `<li><button data-parada="${esc(p.id)}">
      <span class="n">${esc(p.nombre)}</span><span class="d num">${metros(p.distancia_m)}</span>
      <span class="r">${p.rutas.slice(0, 12).map((r) => placa(r, sistemaDe(r))).join("")}${p.rutas.length > 12 ? `<span class="d">+${p.rutas.length - 12}</span>` : ""}</span>
    </button></li>`).join("")}</ul>`;
  el.querySelectorAll("[data-parada]").forEach((b) => b.addEventListener("click", () => ir({ tipo: "parada", parada: b.dataset.parada })));
}
function sistemaDe(codigo) {
  for (const b of buses.values()) if (b.ruta === codigo) return b.sistema;
  return /^[A-Z]?\d{1,2}$/.test(codigo) ? "Troncal" : "Zonal";
}

// estación: tablero + solo sus buses
async function vistaParada(el, refresco = false) {
  const id = vistaId;
  if (!refresco) el.innerHTML = `<p class="ayuda">Buscando llegadas…</p>`;
  const filtro = vista.ruta ? `&ruta=${encodeURIComponent(vista.ruta)}` : "";
  const d = await traer(`/api/llegadas?parada=${encodeURIComponent(vista.parada)}&minutos=25&limite=12${filtro}`);
  if (id !== vistaId) return;
  if (d.preparando) { el.innerHTML = `<p class="ayuda">${esc(d.mensaje)}</p>`; return; }
  if (d.error) { limpiarMapa(); el.innerHTML = `<p class="ayuda">${esc(d.error)} Prueba con otro nombre o con el código de una ruta.</p>`; return; }

  const p = d.parada;
  const lejos = yo ? ` A ${metros(distancia(yo, p))} de ti.` : "";
  const filas = d.llegadas.map((l, i) => {
    const vagon = l.llega_a && l.llega_a !== p.nombre ? `para en ${l.llega_a.replace(/[.\s]+$/, "")}` : "";
    const faltan = l.paradas_antes === 0 ? "es su próxima parada" : `a ${l.paradas_antes} paradas`;
    const tarde = l.retraso_s > 120 ? `, ${Math.round(l.retraso_s / 60)} min de retraso` : "";
    const detalle = [l.sentido, vagon, faltan].filter(Boolean).join(", ") + tarde;
    return `<li data-i="${i}">
      ${placa(l.ruta, l.sistema)}
      <div style="min-width:0"><div class="l-destino">${esc(l.destino)}</div><div class="l-detalle">${esc(detalle)}</div></div>
      <div class="l-min num ${l.llega_en_min < 1 ? "ya" : ""}">${l.llega_en_min < 1 ? "Llegando" : `${Math.round(l.llega_en_min)}<small>min</small>`}</div>
    </li>`;
  }).join("");
  el.innerHTML = `
    <p class="encabezado">${esc(p.nombre)}</p>
    <p class="sub">${p.tipo === "estación" ? "Estación" : "Paradero"}.${lejos} ${vista.ruta ? `Solo la ruta ${esc(vista.ruta)}, p` : "P"}róximos 25 minutos.</p>
    ${avisoHtml()}
    ${filas ? `<ul class="llegadas">${filas}</ul>` : `<p class="ayuda">Ningún bus llega aquí en los próximos 25 minutos.</p>`}
    ${vista.ruta ? `<button class="enlace" id="todas">Ver todas las rutas de esta estación</button>` : ""}`;
  $("todas")?.addEventListener("click", () => ir({ tipo: "parada", parada: vista.parada }));

  // Mapa: solo los buses que vienen, como etiquetas con ruta y minutos.
  for (const m of chips.values()) m.remove();
  chips.clear();
  const claves = new Set();
  d.llegadas.forEach((l, i) => {
    const k = l.bus + "|" + l.placa, b = buses.get(k);
    if (!b) return;
    claves.add(k);
    const div = document.createElement("div");
    div.className = "chip";
    div.innerHTML = `${placa(l.ruta, l.sistema)}<span class="num">${minutos(l.llega_en_min)}</span>`;
    div.addEventListener("click", () => abrirBus(l.bus, l.placa));
    div.addEventListener("mouseenter", () => resaltarFila(i, true));
    chips.set(k, new maplibregl.Marker({ element: div, anchor: "bottom", offset: [0, -2] }).setLngLat([b.cLon, b.cLat]).addTo(map));
  });
  foco = { claves };
  capa.lineas = []; capa.paradas = []; capa.marca = [p.lon, p.lat];
  pintarCapas();
  el.querySelectorAll(".llegadas li").forEach((li) => {
    const l = d.llegadas[+li.dataset.i];
    li.addEventListener("click", () => abrirBus(l.bus, l.placa));
    li.addEventListener("mouseenter", () => resaltarFila(+li.dataset.i, false));
  });

  if (!refresco) {
    // Encuadre: la estación y de dónde vienen sus buses.
    const caja = new maplibregl.LngLatBounds([p.lon, p.lat], [p.lon, p.lat]);
    for (const k of claves) { const b = buses.get(k); caja.extend([b.cLon, b.cLat]); }
    map.fitBounds(caja, { padding: pad(70), maxZoom: 15.5, duration: quieto ? 0 : 800 });
  }
  timerVista = setTimeout(() => id === vistaId && vistaParada(el, true), 20000);

  function resaltarFila(i, desplazar) {
    const lis = el.querySelectorAll(".llegadas li");
    lis.forEach((x) => (x.style.background = ""));
    if (lis[i]) { lis[i].style.background = "var(--suave)"; if (desplazar) lis[i].scrollIntoView({ block: "nearest" }); }
    const k = d.llegadas[i].bus + "|" + d.llegadas[i].placa;
    for (const [kk, m] of chips) m.getElement().classList.toggle("activo", kk === k);
  }
}

// ruta: variantes y sentido
async function vistaRuta(el, refresco = false) {
  const id = vistaId;
  if (!refresco) el.innerHTML = `<p class="ayuda">Buscando la ruta…</p>`;
  const pos = yo ? `&lat=${yo.lat}&lon=${yo.lon}` : "";
  const d = await traer(`/api/ruta?ruta=${encodeURIComponent(vista.ruta)}${pos}`);
  if (id !== vistaId) return;
  if (d.preparando) { el.innerHTML = `<p class="ayuda">${esc(d.mensaje)}</p>`; return; }
  if (d.error) {
    if (vista.desdeBusqueda) return ir({ tipo: "parada", parada: vista.ruta });
    el.innerHTML = `<p class="ayuda">${esc(d.error)}${d.parecidas?.length ? " Parecidas: " + esc(d.parecidas.join(", ")) + "." : ""}</p>`;
    return;
  }
  for (const m of chips.values()) m.remove();
  chips.clear();
  const con = d.variantes.filter((v) => v.buses_en_via > 0), sin = d.variantes.filter((v) => v.buses_en_via === 0);
  if (!d.variantes.some((v) => v.variante === vista.sel)) vista.sel = (con[0] || d.variantes[0])?.variante;
  const total = con.length
    ? `${fmt.format(d.total_en_via)} buses en vía${con.length > 1 ? `, en ${con.length} variantes` : ""}`
    : "Sin buses en vía ahora";
  el.innerHTML = `
    <div class="ruta-cab">${placa(d.ruta, d.variantes[0]?.sistema, "mediana")}<div><div class="encabezado" style="margin:0">Ruta ${esc(d.ruta)}</div><div class="sub">${esc(total)}</div></div></div>
    ${avisoHtml()}
    ${con.map(tarjeta).join("")}
    ${sin.length ? `<p class="resto">${sin.length === 1 ? "Otra variante sin buses ahora" : `Otras ${sin.length} variantes sin buses ahora`}: ${esc(sin.map(titulo).join("; "))}.</p>` : ""}
    ${!yo ? `<button class="enlace" id="pedir-ubic">Usar mi ubicación para saber cuándo pasa por mi paradero</button>` : ""}`;
  el.querySelectorAll(".variante").forEach((b) => b.addEventListener("click", () => { vista.sel = b.dataset.var; mostrar(d, true); }));
  $("pedir-ubic")?.addEventListener("click", () => ubicar(false));
  mostrar(d, !refresco);
  timerVista = setTimeout(() => id === vistaId && vistaRuta(el, true), 20000);
}

function titulo(v) {
  if (v.sentido === "Circular") return v.extremos?.length === 2 ? `${v.extremos[0]} y ${v.extremos[1]}` : `${v.origen} y ${v.pasa_por}`;
  return v.origen ? `${v.origen} a ${v.destino}` : v.destino;
}
function flecha(v) {
  const c = col(v.sistema);
  if (v.sentido === "Circular") {
    return `<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><path d="M17 7.5a7 7 0 1 0 1.3 5" fill="none" stroke="${c}" stroke-width="2.2" stroke-linecap="round"/><path d="M18.3 3v4.8h-4.8" fill="none" stroke="${c}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  }
  return `<svg width="22" height="22" viewBox="0 0 22 22" style="transform:rotate(${v.rumbo || 0}deg)" aria-hidden="true"><path d="M11 2 17 19 11 15 5 19Z" fill="${c}"/></svg>`;
}
function tarjeta(v) {
  const sentido = v.sentido === "Circular" ? `Circular, sale y vuelve a ${v.origen}` : v.sentido ? `Sentido ${v.sentido}` : (v.nota || "");
  const reparto = v.buses_por_sentido
    ? " (" + Object.entries(v.buses_por_sentido).map(([s, n]) => `${n} ${s.charAt(0).toLowerCase() + s.slice(1)}`).join(", ") + ")" : "";
  const h = !v.duracion_min ? "" : v.duracion_min >= 60 ? `${Math.floor(v.duracion_min / 60)} h ${v.duracion_min % 60} min` : `${v.duracion_min} min`;
  let paso = "";
  if (v.tu_parada) {
    const t = v.tu_parada, prox = t.proximos.map((x) => x.llega_en_min);
    const donde = `${esc(t.nombre)}, a ${metros(t.distancia_m)}`;
    paso = prox.length
      ? `<span class="paso">En tu paradero más cercano (${donde}): <strong class="num">${minutos(prox[0])}</strong>${prox.length > 1 ? `, luego ${prox.slice(1).map((m) => Math.round(m)).join(", ")} min` : ""}</span>`
      : `<span class="paso">Tu paradero más cercano es ${donde}. Ningún bus de esta variante va hacia allá ahora.</span>`;
  }
  return `<button class="variante" data-var="${esc(v.variante)}" aria-pressed="${v.variante === vista.sel}">
    ${flecha(v)}
    <span>
      <span class="v-titulo">${esc(titulo(v))}</span>
      <span class="v-linea">${esc(sentido)}</span>
      <span class="v-linea num">${esc(v.sistema)}, ${v.buses_en_via} buses en vía${esc(reparto)}</span>
      ${v.num_paradas ? `<span class="v-linea num">${v.num_paradas} paradas${h ? `, unos ${h} de recorrido` : ""}</span>` : ""}
    </span>
    ${paso}
  </button>`;
}
function mostrar(d, encuadrar) {
  const v = d.variantes.find((x) => x.variante === vista.sel);
  document.querySelectorAll(".variante").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.var === vista.sel)));
  if (!v) return;
  foco = { variantes: new Set([v.variante]) };
  capa.lineas = [{ coords: v.trazado || [], color: col(v.sistema) }]; capa.paradas = [];
  capa.marca = v.tu_parada ? [v.tu_parada.lon, v.tu_parada.lat] : null;
  pintarCapas();
  if (encuadrar && v.trazado?.length) {
    const b = new maplibregl.LngLatBounds();
    v.trazado.forEach(([la, lo]) => b.extend([lo, la]));
    if (yo) b.extend([yo.lon, yo.lat]);
    map.fitBounds(b, { padding: pad(50), maxZoom: 14.5, duration: quieto ? 0 : 800 });
  }
}

// utilidades
function pad(base = 40) {
  return innerWidth > 680 ? { top: base, bottom: base, right: base + 30, left: 380 + 12 + base }
    : { top: base, left: base, right: base, bottom: innerHeight * 0.56 + base };
}
function distancia(a, p) {
  const R = 6371000, r = Math.PI / 180, dLa = (p.lat - a.lat) * r, dLo = (p.lon - a.lon) * r;
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(p.lat * r) * Math.sin(dLo / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function ubicar(irACerca = true) {
  const txt = $("ubicar").querySelector("span");
  if (!navigator.geolocation) { $("vista").insertAdjacentHTML("afterbegin", `<p class="aviso">Este navegador no permite leer la ubicación. Busca tu estación por nombre.</p>`); return; }
  txt.textContent = "Buscando tu ubicación…";
  navigator.geolocation.getCurrentPosition((pos) => {
    yo = { lat: pos.coords.latitude, lon: pos.coords.longitude };
    txt.textContent = "Actualizar mi ubicación";
    pintarCapas();
    if (irACerca || vista.tipo === "inicio") {
      map.flyTo({ center: [yo.lon, yo.lat], zoom: 15.5, padding: pad(), speed: quieto ? 10 : 1.4 });
      ir({ tipo: "cerca" });
    } else pintarVista();
  }, () => {
    txt.textContent = "Usar mi ubicación";
    $("vista").insertAdjacentHTML("afterbegin", `<p class="aviso">No se pudo leer tu ubicación. Revisa el permiso de ubicación del navegador o busca tu estación por nombre.</p>`);
  }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 });
}

// eventos
$("tema").addEventListener("click", cambiarTema);
$("ubicar").addEventListener("click", () => ubicar(vista.tipo !== "ruta"));
$("buscar").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (!q) return ir({ tipo: "inicio" });
  if (pareceRuta(q)) ir({ tipo: "ruta", ruta: q.toUpperCase(), desdeBusqueda: true });
  else ir({ tipo: "parada", parada: q });
});
$("q").addEventListener("search", () => { if (!$("q").value) ir({ tipo: "inicio" }); });

const pop = new maplibregl.Popup({ closeButton: false, offset: 8 });
map.on("mouseenter", "estaciones", (e) => {
  map.getCanvas().style.cursor = "pointer";
  pop.setLngLat(e.features[0].geometry.coordinates).setHTML(`<strong>${esc(e.features[0].properties.nombre)}</strong><div class="pop-m">Ver qué buses vienen</div>`).addTo(map);
});
map.on("mouseleave", "estaciones", () => { map.getCanvas().style.cursor = ""; pop.remove(); });
map.on("click", "estaciones", (e) => { $("q").value = e.features[0].properties.nombre; ir({ tipo: "parada", parada: e.features[0].properties.id }); });

map.on("click", ["buses", "buses-icono"], (e) => {
  const b = buses.get(e.features[0].properties.k);
  if (b) abrirBus(b.bus, b.placa);
});
const popBus = new maplibregl.Popup({ closeButton: false, offset: 10 });
map.on("mousemove", "buses-icono", (e) => {
  const b = buses.get(e.features[0].properties.k);
  if (!b) return;
  popBus.setLngLat([b.cLon, b.cLat]).setHTML(`<div style="display:flex;gap:6px;align-items:center">${placa(b.ruta, b.sistema)}<span>${esc(b.destino)}</span></div><div class="pop-m">Clic para ver sus próximas paradas</div>`).addTo(map);
});
map.on("mouseleave", "buses-icono", () => popBus.remove());
map.on("mouseenter", ["buses", "buses-icono"], () => (map.getCanvas().style.cursor = "pointer"));
map.on("mouseleave", ["buses", "buses-icono"], () => (map.getCanvas().style.cursor = ""));

// Modo grabación: R alterna. Sin panel; la cámara se inclina y gira despacio.
let girando = false;
function girar() { if (!girando) return; map.rotateTo(map.getBearing() + 0.5, { duration: 1000, easing: (t) => t }); setTimeout(girar, 1000); }
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.key.toLowerCase() !== "r" || e.ctrlKey || e.metaKey || e.altKey) return;
  const on = document.body.classList.toggle("grabando");
  girando = on && !quieto;
  if (on) { map.easeTo({ pitch: 50, duration: quieto ? 0 : 1500 }); setTimeout(girar, 1600); }
  else map.easeTo({ pitch: 0, bearing: 0, duration: quieto ? 0 : 1000 });
});
