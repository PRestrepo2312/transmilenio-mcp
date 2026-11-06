"""Regenera las capturas del README desde el mapa local.

    transmilenio-web --no-abrir          # en otra consola
    pip install playwright
    python docs/capturas.py              # deja los PNG en docs/img/

Usa el Chrome instalado (no descarga navegadores). Conviene correrlo con el feed en vivo y
en hora pico; si el feed está detenido, las capturas muestran el aviso.
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765"
SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "img"


def listo(p, ms: int = 2500) -> None:
    """Espera a que los datos lleguen y a que MapLibre termine de pintar el cuadro."""
    p.wait_for_timeout(ms)
    p.evaluate("() => new Promise((r) => { map.once('idle', r); map.triggerRepaint(); setTimeout(r, 8000); })")
    p.wait_for_timeout(300)


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
        nav = pw.chromium.launch(channel="chrome", args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        escritorio = {"viewport": {"width": 1280, "height": 800}, "device_scale_factor": 2, "locale": "es-CO"}

        p = nav.new_context(**escritorio, color_scheme="light").new_page()
        p.goto(URL)
        p.evaluate("() => localStorage.setItem('tema', 'dia')")
        p.reload()
        listo(p, 5000)
        p.screenshot(path=SALIDA / "mapa.png")
        buscar(p, "B10")
        p.screenshot(path=SALIDA / "ruta.png")
        if bus := un_bus("B10"):
            p.evaluate("([n, pl]) => abrirBus(n, pl)", [bus["bus"], bus["placa"]])
            listo(p)
            p.screenshot(path=SALIDA / "bus.png")
        buscar(p, "Calle 72")
        p.screenshot(path=SALIDA / "estacion.png")

        n = nav.new_context(**escritorio).new_page()
        n.goto(URL)
        n.evaluate("() => localStorage.setItem('tema', 'noche')")
        n.reload()
        listo(n, 5000)
        buscar(n, "Calle 72")
        n.screenshot(path=SALIDA / "estacion-noche.png")

        m = nav.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, locale="es-CO").new_page()
        m.goto(URL)
        listo(m, 5000)
        buscar(m, "C25")
        m.screenshot(path=SALIDA / "movil.png")
        nav.close()
    print(f"Capturas en {SALIDA}")


if __name__ == "__main__":
    main()
