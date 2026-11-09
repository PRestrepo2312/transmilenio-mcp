"""Regenera las capturas del README desde el mapa local.

    transmilenio-web --no-abrir          # en otra consola
    pip install playwright pillow
    python docs/capturas.py              # deja las capturas (WebP) en docs/img/

Usa el Chrome instalado (no descarga navegadores) con la GPU; si no hay GPU, `--sin-gpu`.
Conviene correrlo con el feed en vivo y en hora pico. Si el feed está detenido, el estado de
arriba dice de cuándo es la foto en vez del aviso.
"""

import json
import sys
import urllib.request
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SALIDA = Path(ARGS[0]) if ARGS else Path(__file__).parent / "img"
GPU = "--sin-gpu" not in sys.argv
NAVEGADOR = (
    ["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"]
    if GPU
    else ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
)

# Sin fundidos (los íconos aparecen de golpe) y, si el feed está quieto, el estado dice de
# cuándo es la foto. La recarga periódica se apaga para que no cambie el mapa a mitad de captura.
PREPARAR = """() => {
  map._fadeDuration = 0;
  for (let i = 1; i < 10000; i++) clearInterval(i);
  const viejo = estado;
  window.estado = (tipo, txt) => tipo === "detenido" && /no reporta desde/.test(txt)
    ? viejo("", document.body.dataset.foto) : viejo(tipo, txt);
  cargarFlota();
}"""


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def rotulo_foto(iso: str | None) -> str:
    if not iso:
        return "Foto del feed"
    t = datetime.fromisoformat(iso)
    hora = f"{t.hour % 12 or 12}:{t.minute:02d} {'p. m.' if t.hour >= 12 else 'a. m.'}"
    return f"Foto del feed: {DIAS[t.weekday()]} {t.day} {MESES[t.month - 1]}, {hora}"


def abrir(p) -> None:
    p.wait_for_function("() => typeof buses !== 'undefined' && buses.size > 0", timeout=180000)
    flota = json.load(urllib.request.urlopen(f"{URL}/api/flota"))
    p.evaluate("(t) => { document.body.dataset.foto = t; }", rotulo_foto(flota.get("ultimo_reporte")))
    p.evaluate(PREPARAR)
    p.add_style_tag(content=".cuerpo .aviso { display: none; }")
    listo(p, 1500)


def guardar(p, nombre: str, ancho: int = 1600) -> None:
    """WebP de máximo `ancho` px: se ve nítido en el README y pesa una fracción del PNG."""
    img = Image.open(BytesIO(p.screenshot()))
    if img.width > ancho:
        img = img.resize((ancho, round(img.height * ancho / img.width)), Image.LANCZOS)
    img.save(SALIDA / f"{nombre}.webp", quality=78, method=6)


def listo(p, ms: int = 2500) -> None:
    """Espera a que los datos lleguen y a que MapLibre termine de pintar el cuadro."""
    p.wait_for_timeout(ms)
    p.evaluate(
        "() => new Promise((r) => { let hecho = false;"
        " const fin = () => { if (!hecho) { hecho = true; requestAnimationFrame(() => requestAnimationFrame(r)); } };"
        " map.once('idle', fin); map.triggerRepaint(); setTimeout(fin, 15000); })"
    )


def buscar(p, texto: str) -> None:
    p.fill("#q", texto)
    p.press("#q", "Enter")
    listo(p)


def un_bus(ruta: str) -> dict | None:
    datos = json.load(urllib.request.urlopen(f"{URL}/api/ruta?ruta={ruta}"))
    for v in datos.get("variantes", []):
        for b in v.get("buses", []):
            if b.get("siguiente_parada"):
                return b
    return None


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        nav = pw.chromium.launch(channel="chrome", args=NAVEGADOR)
        escritorio = {"viewport": {"width": 1280, "height": 800}, "device_scale_factor": 2, "locale": "es-CO"}

        p = nav.new_context(**escritorio, color_scheme="light").new_page()
        p.goto(URL)
        p.evaluate("() => localStorage.setItem('tema', 'dia')")
        p.reload()
        abrir(p)
        buscar(p, "B10")
        guardar(p, "ruta")
        if bus := un_bus("B10"):
            p.evaluate("([n, pl]) => abrirBus(n, pl)", [bus["bus"], bus["placa"]])
            listo(p)
            guardar(p, "bus")
        buscar(p, "Calle 72")
        guardar(p, "estacion")

        n = nav.new_context(**escritorio).new_page()
        n.goto(URL)
        n.evaluate("() => localStorage.setItem('tema', 'noche')")
        n.reload()
        abrir(n)
        buscar(n, "Calle 72")
        guardar(n, "estacion-noche")

        m = nav.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, locale="es-CO").new_page()
        m.goto(URL)
        abrir(m)
        buscar(m, "C25")
        guardar(m, "movil", 780)
        nav.close()
    print(f"Capturas en {SALIDA}")


if __name__ == "__main__":
    main()
