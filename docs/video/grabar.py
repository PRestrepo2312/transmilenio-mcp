"""Graba el video de transmilenio-mcp cuadro por cuadro desde el mapa local (127.0.0.1:8765).

Toma los datos del feed en vivo en el momento de grabar: cuántos buses hay, lo programado
contra lo real por sistema, los viajes cancelados del día, un bus que esté llegando a la
Calle 72 y las respuestas a las dos preguntas. El mapa se congela al empezar (se apaga la
recarga), así que todo el video es la misma foto.

Correr con el Python de transmilenio-mcp/.venv (necesita el paquete y Playwright):
    transmilenio-web --no-abrir        # en otra consola, 3-4 minutos antes (para el rastro)
    GPU=1 python grabar.py <carpeta_cuadros> [escena_desde] [escena_hasta] [muestra]
    PORTADA=docs/img/portada.webp ...  # además guarda la portada del README (1600x900)
"""

import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765"
FPS = 30
W, H = 1920, 1080
SALIDA = Path(sys.argv[1])
DESDE = int(sys.argv[2]) if len(sys.argv) > 2 else 0
HASTA = int(sys.argv[3]) if len(sys.argv) > 3 else 99
MUESTRA = [float(x) for x in sys.argv[4].split(",")] if len(sys.argv) > 4 else None

CALLE72 = [-74.0622, 4.6584]
BOGOTA = [-74.105, 4.648]

CSS = """
.estado i { background: #6cb0ff !important; }
.cuerpo .aviso, .hud, .maplibregl-ctrl-top-right { display: none !important; }
#cine { position: fixed; inset: 0; pointer-events: none; z-index: 50; font-family: system-ui, "Segoe UI", sans-serif; color: var(--texto); }
#cine .velo { position: absolute; inset: 0; background: #0b0d10; opacity: 0; }
#cine .rotulo { position: absolute; left: 56px; bottom: 56px; max-width: 760px; background: var(--panel);
  border-radius: 14px; box-shadow: var(--sombra); padding: 22px 28px; opacity: 0; }
#cine .rotulo.der { left: auto; right: 56px; }
#cine .rotulo b { display: block; font-size: 34px; line-height: 1.15; font-weight: 700; letter-spacing: -.01em; }
#cine .rotulo span { display: block; margin-top: 8px; font-size: 21px; color: var(--texto-2); }
#cine .portada { position: absolute; left: 80px; top: 50%; transform: translateY(-50%); opacity: 0; }
#cine .portada .n { font-size: 150px; font-weight: 800; line-height: .9; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }
#cine .portada .s { font-size: 34px; margin-top: 14px; color: var(--texto-2); }
#cine .portada .f { font-size: 22px; margin-top: 18px; color: var(--texto-3); }
#cine .tarjeta { position: absolute; left: 50%; top: 50%; width: 1040px; transform: translate(-50%, -50%);
  background: var(--panel); border-radius: 18px; box-shadow: var(--sombra); padding: 40px 48px; opacity: 0; }
#cine .tarjeta h2 { margin: 0; font-size: 40px; letter-spacing: -.01em; }
#cine .tarjeta .sub { margin: 8px 0 26px; font-size: 21px; color: var(--texto-2); }
#cine .fila { display: grid; grid-template-columns: 170px 1fr 150px 80px; align-items: center; gap: 18px; margin: 14px 0; font-size: 22px; }
#cine .fila .pista { position: relative; height: 26px; background: var(--suave); border-radius: 6px; overflow: hidden; }
#cine .fila .real { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 6px; }
#cine .fila .prog { position: absolute; top: -4px; bottom: -4px; width: 3px; background: var(--texto); border-radius: 2px; }
#cine .fila .cifra { text-align: right; color: var(--texto-2); font-variant-numeric: tabular-nums; }
#cine .fila .pct { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
#cine .fila.total { border-top: 1px solid var(--linea); padding-top: 14px; }
#cine .nota { margin-top: 22px; font-size: 18px; color: var(--texto-3); }
#cine .chat { position: absolute; left: 50%; top: 50%; width: 1000px; transform: translate(-50%, -50%); opacity: 0; }
#cine .chat .cab { font-size: 22px; color: #c9d1d9; margin-bottom: 18px; }
#cine .msg { border-radius: 16px; padding: 18px 24px; font-size: 25px; line-height: 1.4; margin: 14px 0; box-shadow: var(--sombra); }
#cine .msg.yo { background: #0b62c4; color: #fff; margin-left: 180px; }
#cine .msg.el { background: var(--panel); margin-right: 120px; }
#cine .msg .tool { display: inline-block; font: 600 16px ui-monospace, Consolas, monospace; color: var(--texto-2);
  background: var(--suave); border-radius: 6px; padding: 3px 9px; margin-bottom: 10px; }
#cine .cierre { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: center; align-items: center; opacity: 0; color: #e8eaed; text-align: center; }
#cine .cierre .t { font: 800 96px ui-monospace, Consolas, monospace; letter-spacing: -.02em; }
#cine .cierre .s { font-size: 32px; margin-top: 18px; color: #c9d1d9; }
#cine .cierre .f { font-size: 22px; margin-top: 34px; color: #8b949e; }
"""

COLORES = {"Zonal": "#2f6fd6", "Troncal": "#d7141a", "Alimentador": "#2e9e4f", "Dual": "#e8a317"}
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
BOG = dt.timezone(dt.timedelta(hours=-5))
D: dict = {}  # los datos en vivo; los llena datos()


def miles(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def coma(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def hora_txt(d: dt.datetime) -> str:
    h = d.hour % 12 or 12
    return f"{h}:{d.minute:02d} {'a. m.' if d.hour < 12 else 'p. m.'}"


def api(ruta: str, **q) -> dict:
    url = f"{URL}{ruta}" + ("?" + urllib.parse.urlencode(q) if q else "")
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read())


def datos() -> None:
    """Saca del feed en vivo todo lo que el video muestra."""
    from transmilenio_mcp.datos.historial import Historial
    from transmilenio_mcp.servicios import Servicio
    from transmilenio_mcp.veedor import Veedor

    ahora = dt.datetime.now(BOG)
    D["cuando"] = f"{DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]}, {hora_txt(ahora)}"
    D["cuando_corto"] = f"{DIAS[ahora.weekday()]} {ahora.day} nov, {hora_txt(ahora)}"

    # Lo programado en vía a las HH:30 de esta hora contra los buses del feed, por sistema.
    s = Servicio(rastrear=False)
    red = s.cargador.red()
    estado = api("/api/estado")
    en_via = estado["por_sistema"]
    prog: dict[str, int] = {}
    for rid, r in red.rutas.items():
        if r.sistema in COLORES:
            prog[r.sistema] = prog.get(r.sistema, 0) + red.programado(rid, ahora.date())[1][ahora.hour]
    D["sistemas"] = [(n, en_via.get(n, 0), prog.get(n, 0), c) for n, c in COLORES.items() if prog.get(n)]
    D["real_total"] = sum(x[1] for x in D["sistemas"])
    D["prog_total"] = sum(x[2] for x in D["sistemas"])
    D["hora_prog"] = hora_txt(ahora.replace(minute=30))

    canc = Veedor(s, Historial()).cancelaciones()
    D["cancelados"] = canc

    # Un troncal que esté llegando a la Calle 72: la pregunta del chat y el bus de la escena.
    lleg = api("/api/llegadas", parada="Calle 72", minutos=10, limite=40)["llegadas"]
    elegido = next((x for x in lleg if x["sistema"] == "Troncal" and x["llega_en_min"] >= 1), None)
    elegido = elegido or next(x for x in lleg if x["sistema"] == "Troncal")
    D["bus"] = elegido
    print(json.dumps({k: v for k, v in D.items() if k != "cancelados"}, ensure_ascii=False, default=str)[:900])
    print(
        "cancelados:",
        json.dumps(canc["total"]),
        json.dumps({k: v["pct_cancelado"] for k, v in canc["por_sistema"].items()}),
    )


JS_CINE = """
window.__cine = (s) => {
  let c = document.getElementById('cine');
  if (!c) { c = document.createElement('div'); c.id = 'cine'; document.body.appendChild(c); }
  c.innerHTML = s.html;
};
"""


def suave(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def aparece(t: float, ini: float, fin: float, entra: float = 0.08, sale: float = 0.08) -> float:
    """Opacidad de un elemento visible entre ini y fin (fracciones de la escena)."""
    if t < ini or t > fin:
        return 0.0
    a = min(1.0, (t - ini) / entra) if entra else 1.0
    b = min(1.0, (fin - t) / sale) if sale else 1.0
    return suave(min(a, b))


def lerp(a, b, t):
    if isinstance(a, list):
        return [lerp(x, y, t) for x, y in zip(a, b, strict=True)]
    return a + (b - a) * t


def rotulo(titulo: str, sub: str, op: float, der: bool = False) -> str:
    dy = (1 - op) * 18
    return (
        f'<div class="rotulo{" der" if der else ""}" style="opacity:{op:.3f};transform:translateY({dy:.1f}px)">'
        f"<b>{titulo}</b><span>{sub}</span></div>"
    )


def escribir(texto: str, t: float) -> str:
    n = int(len(texto) * suave(t)) if t < 1 else len(texto)
    return texto[:n]


# ----------------------------------------------------------------- escenas


def e_portada(t):
    """Ciudad completa; el número cuenta hasta los buses del feed."""
    cam = dict(
        center=lerp([-74.13, 4.64], BOGOTA, suave(t)),
        zoom=lerp(10.75, 11.25, suave(t)),
        pitch=lerp(0, 38, suave(t)),
        bearing=lerp(0, -12, suave(t)),
    )
    n = round(D["n"] * suave(min(1, t / 0.45)))
    op = aparece(t, 0.02, 0.93, 0.1, 0.1)
    html = (
        f'<div class="portada" style="opacity:{op:.3f}"><div class="n">{miles(n)}</div>'
        + '<div class="s">buses de TransMilenio reportando a la vez</div>'
        + f'<div class="f">Feed GTFS-Realtime en vivo, {D["cuando"]}</div></div>'
    )
    return cam, html


def e_vuelo(t):
    """Vuelo hasta la Caracas con Calle 72, girando."""
    k = suave(min(1, t / 0.6))
    z = lerp(11.25, 15.6, k)
    cam = dict(
        center=lerp(BOGOTA, CALLE72, suave(min(1, t / 0.5))), zoom=z, pitch=lerp(38, 58, k), bearing=lerp(-12, 28, t)
    )
    html = rotulo(
        "Cada ícono es un bus real",
        "Con su ruta, su placa y hacia dónde va. Troncales en rojo, zonales en azul.",
        aparece(t, 0.45, 0.97),
    )
    return cam, html


def e_estacion(t, base):
    cam = dict(center=base["center"], zoom=base["zoom"] + 0.35 * suave(t), pitch=0, bearing=0)
    html = rotulo(
        "¿Qué viene a mi estación?",
        "Buscas Calle 72 y ves cada bus que se acerca, con su placa y en cuántos minutos llega.",
        aparece(t, 0.08, 0.95),
        der=True,
    )
    return cam, html


def e_bus(t, base):
    cam = dict(center=base["center"], zoom=base["zoom"] + 0.3 * suave(t), pitch=0, bearing=0)
    html = rotulo(
        "Un clic en el bus",
        "Por dónde ya pasó, dónde va y a qué hora llega a cada parada que le queda.",
        aparece(t, 0.08, 0.95),
        der=True,
    )
    return cam, html


def e_veedor(t):
    cam = dict(center=BOGOTA, zoom=lerp(11.2, 11.5, t), pitch=30, bearing=lerp(-20, -8, t))
    op = aparece(t, 0.03, 0.96, 0.07, 0.05)
    crece = suave((t - 0.12) / 0.35)
    # Escala: el sistema más lleno frente a su programado no se sale de la pista.
    tope = max(1.0, max(real / prog for _, real, prog, _ in D["sistemas"])) * 1.08
    filas = ""
    for nombre, real, prog, color in D["sistemas"]:
        w = 100 * (real / prog) / tope * crece
        x = 100 / tope
        pct = round(100 * real / prog * crece)
        filas += (
            f'<div class="fila"><span>{nombre}</span><div class="pista"><div class="real" style="width:{w:.1f}%;background:{color}"></div>'
            f'<div class="prog" style="left:{x:.1f}%"></div></div>'
            f'<span class="cifra">{miles(real * crece)} / {miles(prog)}</span><span class="pct">{pct} %</span></div>'
        )
    total_pct = round(100 * D["real_total"] / D["prog_total"] * crece)
    filas += (
        f'<div class="fila total"><b>Total</b><span></span><span class="cifra">{miles(D["real_total"] * crece)} / {miles(D["prog_total"])}</span>'
        f'<span class="pct">{total_pct} %</span></div>'
    )
    html = (
        f'<div class="velo" style="opacity:{0.55 * op:.3f}"></div>'
        f'<div class="tarjeta" style="opacity:{op:.3f};transform:translate(-50%,calc(-50% + {(1 - op) * 20:.1f}px))">'
        "<h2>Lo programado contra lo que salió a la calle</h2>"
        f'<div class="sub">Buses en vía según el feed frente a los que pone el horario oficial a las {D["hora_prog"]}</div>'
        f"{filas}"
        '<div class="nota">La raya negra es lo programado. Una foto es una pista, no una conclusión: el veedor guarda el feed cada minuto para medir días enteros.</div>'
        "</div>"
    )
    return cam, html


def e_cancelados(t):
    cam = dict(center=BOGOTA, zoom=lerp(11.5, 11.75, t), pitch=34, bearing=lerp(-8, 4, t))
    op = aparece(t, 0.03, 0.96, 0.07, 0.05)
    crece = suave((t - 0.12) / 0.35)
    c = D["cancelados"]
    filas_sis = [(n, c["por_sistema"][n], col) for n, col in COLORES.items() if n in c["por_sistema"]]
    tope = max(v["pct_cancelado"] or 0 for _, v, _ in filas_sis) * 1.15 or 1
    filas = ""
    for nombre, v, color in filas_sis:
        pct = v["pct_cancelado"] or 0
        filas += (
            f'<div class="fila"><span>{nombre}</span><div class="pista"><div class="real" style="width:{100 * pct / tope * crece:.1f}%;background:{color}"></div></div>'
            f'<span class="cifra">{miles(v["cancelados"] * crece)} / {miles(v["programados"])}</span>'
            f'<span class="pct">{coma(pct * crece)} %</span></div>'
        )
    tot = c["total"]
    filas += (
        f'<div class="fila total"><b>Total</b><span></span><span class="cifra">{miles(tot["cancelados"] * crece)} / {miles(tot["programados"])}</span>'
        f'<span class="pct">{coma(tot["pct_cancelado"] * crece)} %</span></div>'
    )
    html = (
        f'<div class="velo" style="opacity:{0.55 * op:.3f}"></div>'
        f'<div class="tarjeta" style="opacity:{op:.3f};transform:translate(-50%,calc(-50% + {(1 - op) * 20:.1f}px))">'
        "<h2>Viajes del día que TransMilenio marca como cancelados</h2>"
        f'<div class="sub">Del horario de hoy, según su propio feed de viajes ({D["cuando"]})</div>'
        f"{filas}"
        '<div class="nota">Es lo que declara el operador en el feed, no una verificación en la calle. El veedor lo guarda día a día para comparar.</div>'
        "</div>"
    )
    return cam, html


def e_chat(t, conv):
    cam = dict(center=CALLE72, zoom=lerp(13.2, 13.6, t), pitch=45, bearing=lerp(10, 30, t))
    op = aparece(t, 0.02, 0.97, 0.05, 0.04)
    (q1, tool1, a1), (q2, tool2, a2) = conv
    partes = []
    if t > 0.04:
        partes.append(f'<div class="msg yo">{escribir(q1, (t - 0.04) / 0.10)}</div>')
    if t > 0.17:
        partes.append(
            f'<div class="msg el"><span class="tool">{tool1}</span><br>{escribir(a1, (t - 0.19) / 0.17)}</div>'
        )
    if t > 0.50:
        partes.append(f'<div class="msg yo">{escribir(q2, (t - 0.50) / 0.10)}</div>')
    if t > 0.63:
        partes.append(
            f'<div class="msg el"><span class="tool">{tool2}</span><br>{escribir(a2, (t - 0.65) / 0.17)}</div>'
        )
    html = (
        f'<div class="velo" style="opacity:{0.62 * op:.3f}"></div>'
        f'<div class="chat" style="opacity:{op:.3f}"><div class="cab">Y todo esto se lo puedes preguntar a Claude, con el servidor MCP</div>'
        + "".join(partes)
        + "</div>"
    )
    return cam, html


def e_cierre(t):
    cam = dict(center=BOGOTA, zoom=lerp(11.0, 11.35, t), pitch=lerp(40, 48, t), bearing=lerp(-30, -5, t))
    op = aparece(t, 0.05, 1.0, 0.18, 0)
    html = (
        f'<div class="velo" style="opacity:{0.7 * op:.3f}"></div>'
        f'<div class="cierre" style="opacity:{op:.3f}"><div class="t">transmilenio-mcp</div>'
        '<div class="s">Mapa local, servidor MCP y veedor ciudadano. En Python, de código abierto.</div>'
        '<div class="f">Datos abiertos de TransMilenio S.A. (CC BY-SA 4.0). Proyecto independiente.</div></div>'
    )
    return cam, html


# ----------------------------------------------------------------- motor


def listo(p, tope_ms: int = 15000) -> None:
    """Espera a que el mapa base y los buses estén pintados de verdad en el lienzo.

    'idle' llega cuando ya cargaron los mosaicos y terminó el acomodo de los íconos; después
    se dejan pasar dos cuadros más para que el lienzo tenga el resultado.
    """
    p.evaluate(
        "(tope) => new Promise((r) => { let hecho = false;"
        " const fin = () => { if (hecho) return; hecho = true; requestAnimationFrame(() => requestAnimationFrame(() => r())); };"
        " map.once('idle', fin); map.triggerRepaint(); setTimeout(fin, tope); })",
        tope_ms,
    )


def cuadro(p, cam: dict, html: str, n: int) -> None:
    p.evaluate("([c, h]) => { map.jumpTo(c); __cine({html: h}); }", [cam, html])
    listo(p)
    if MUESTRA:
        print(
            n,
            cam,
            p.evaluate(
                "() => [buses.size, map.getSource('buses')._data.features?.length, map.queryRenderedFeatures({layers: ['buses', 'buses-icono']}).length, map.getZoom().toFixed(2)]"
            ),
        )
    p.screenshot(path=SALIDA / f"{n:05d}.jpg", type="jpeg", quality=92)


def camara(p) -> dict:
    return p.evaluate("() => { const c = map.getCenter(); return {center: [c.lng, c.lat], zoom: map.getZoom()}; }")


def conversacion() -> list:
    # Respuestas armadas con la salida real de las herramientas en el momento de grabar.
    b = D["bus"]
    m = b["llega_en_min"]
    if m < 1:
        cuando = "en menos de un minuto"
    elif round(m) == 1:
        cuando = "en un minuto"
    else:
        cuando = f"en unos {round(m)} minutos"
    hh, mm = (int(x) for x in b["hora_estimada"].split(":"))
    a_las = hora_txt(dt.datetime(2000, 1, 1, hh % 24, mm))
    a1 = (
        f"El próximo {b['ruta']} hacia {b['destino']} (bus {b['bus']}, placa {b['placa']}) llega a Calle 72 "
        f"{cuando} (a las {a_las}). Viene de {(b['ultima_parada'] or '').split(' - ')[0]}."
    )
    c = D["cancelados"]
    ps = c["por_sistema"]
    a2 = (
        f"Del horario de hoy, TransMilenio marcó {miles(c['total']['cancelados'])} de {miles(c['total']['programados'])} "
        f"viajes como cancelados: {coma(c['total']['pct_cancelado'])} %. En el zonal, {coma(ps['Zonal']['pct_cancelado'])} %; "
        f"en la troncal, {coma(ps['Troncal']['pct_cancelado'])} %."
    )
    return [
        (f"¿Cuándo pasa el próximo {b['ruta']} por la Calle 72?", "llegadas", a1),
        ("¿Cuántos viajes se cancelaron hoy?", "viajes_cancelados", a2),
    ]


def capturar_portada(nav, destino: str) -> None:
    """La imagen de arriba del README: la Caracas con Calle 72 de noche, con el contador."""
    from io import BytesIO

    from PIL import Image

    ctx = nav.new_context(
        viewport={"width": 1600, "height": 900}, device_scale_factor=1, locale="es-CO", color_scheme="dark"
    )
    p = ctx.new_page()
    p.goto(URL)
    p.evaluate("() => localStorage.setItem('tema', 'noche')")
    p.reload()
    p.wait_for_function("() => typeof buses !== 'undefined' && buses.size > 1000", timeout=120000)
    p.evaluate("() => { for (let i = 1; i < 10000; i++) clearInterval(i); map._fadeDuration = 0; }")
    p.evaluate("() => { document.body.classList.add('grabando'); ir({tipo: 'inicio'}); }")
    p.evaluate("() => map.jumpTo({center: [-74.0640, 4.6600], zoom: 14.35, pitch: 52, bearing: 8})")
    listo(p, 15000)
    Image.open(BytesIO(p.screenshot(type="png"))).save(destino, "WEBP", quality=82, method=6)
    print("Portada:", destino, Path(destino).stat().st_size // 1024, "KB")
    ctx.close()


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    datos()
    conv = conversacion()
    for q, tool, a in conv:
        print(f"[{tool}] {q}\n    {a}")
    plan = [  # (segundos, nombre)
        (6.5, "portada"),
        (8.0, "vuelo"),
        (7.5, "estacion"),
        (7.5, "bus"),
        (7.0, "veedor"),
        (7.0, "cancelados"),
        (11.0, "chat"),
        (5.5, "cierre"),
    ]
    n = 0
    t0 = time.time()
    with sync_playwright() as pw:
        args = (
            ["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist", "--hide-scrollbars"]
            if os.environ.get("GPU")
            else ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars"]
        )
        nav = pw.chromium.launch(channel="chrome", args=args)
        if os.environ.get("PORTADA"):
            capturar_portada(nav, os.environ["PORTADA"])
        ctx = nav.new_context(
            viewport={"width": W, "height": H}, device_scale_factor=1, locale="es-CO", color_scheme="dark"
        )
        p = ctx.new_page()
        p.goto(URL)
        p.evaluate("() => localStorage.setItem('tema', 'noche')")
        p.reload()
        p.wait_for_function("() => typeof buses !== 'undefined' && buses.size > 1000", timeout=120000)
        # La flota queda congelada desde aquí: una recarga a mitad de captura movería el lienzo.
        p.evaluate("() => { for (let i = 1; i < 10000; i++) clearInterval(i); }")
        D["n"] = p.evaluate("() => buses.size")
        # Lo que audio.py necesita para la voz en off, con las mismas cifras de la imagen.
        (SALIDA.parent / "datos_video.json").write_text(
            json.dumps(
                {
                    "n": D["n"],
                    "pct_zonal": D["cancelados"]["por_sistema"]["Zonal"]["pct_cancelado"],
                    "cuando": D["cuando"],
                    "plan": plan,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        p.add_style_tag(content=CSS)
        # Sin fundidos: cada cuadro debe salir completo, no a medio aparecer.
        p.evaluate("() => { map._fadeDuration = 0; }")
        p.evaluate("() => {" + JS_CINE + "}")
        texto_estado = f"En vivo · {D['cuando_corto']}"
        p.evaluate(
            "(txt) => { window.estado = () => { $('estado').className = 'estado'; $('estado-txt').textContent = txt; }; estado(); }",
            texto_estado,
        )
        listo(p, 8000)

        for i, (seg, nombre) in enumerate(plan):
            total = round(seg * FPS)
            base = None
            if nombre in ("portada", "vuelo", "veedor", "cancelados", "chat", "cierre"):
                p.evaluate("() => { document.body.classList.add('grabando'); ir({tipo: 'inicio'}); }")
            elif nombre == "estacion":
                p.evaluate("() => { document.body.classList.remove('grabando'); map.jumpTo({pitch: 0, bearing: 0}); }")
                p.fill("#q", "Calle 72")
                p.press("#q", "Enter")
                p.wait_for_timeout(2500)
                listo(p, 8000)
                base = camara(p)
            elif nombre == "bus":
                p.evaluate("() => { document.body.classList.remove('grabando'); map.jumpTo({pitch: 0, bearing: 0}); }")
                p.fill("#q", D["bus"]["ruta"])
                p.evaluate("([b, pl]) => abrirBus(b, pl)", [D["bus"]["bus"], D["bus"]["placa"]])
                p.wait_for_timeout(2500)
                listo(p, 8000)
                base = camara(p)
            if not (DESDE <= i <= HASTA):
                n += total
                continue
            pasos = range(total)
            if MUESTRA:  # un cuadro por escena para revisar el diseño
                pasos = [round(f * (total - 1)) for f in MUESTRA]
            for k in pasos:
                t = k / max(1, total - 1)
                if nombre == "portada":
                    cam, html = e_portada(t)
                elif nombre == "vuelo":
                    cam, html = e_vuelo(t)
                elif nombre == "estacion":
                    cam, html = e_estacion(t, base)
                elif nombre == "bus":
                    cam, html = e_bus(t, base)
                elif nombre == "veedor":
                    cam, html = e_veedor(t)
                elif nombre == "cancelados":
                    cam, html = e_cancelados(t)
                elif nombre == "chat":
                    cam, html = e_chat(t, conv)
                else:
                    cam, html = e_cierre(t)
                tc = time.time()
                cuadro(p, cam, html, n)
                if MUESTRA:
                    print(f"  {time.time() - tc:.2f} s")
                n += 1
                if n % 60 == 0:
                    print(f"{nombre}: cuadro {n} ({time.time() - t0:.0f} s)", flush=True)
        nav.close()
    print(f"Listo: {n} cuadros en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
