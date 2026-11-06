"""Mapa local en el navegador, sin Claude.

transmilenio-web                  abre http://127.0.0.1:8765
transmilenio-web --port 9000 --no-abrir
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlparse

from . import FUENTE
from .config import log
from .recolector import en_segundo_plano
from .servicios import PreparandoIndice, Servicio

# Solo estos archivos se sirven; nada de rutas arbitrarias del disco.
ESTATICOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/estilos.css": ("estilos.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def _entero(valor: str | None, defecto: int) -> int:
    try:
        return int(valor) if valor else defecto
    except ValueError:
        return defecto


def _real(valor: str | None) -> float | None:
    try:
        return float(valor) if valor else None
    except ValueError:
        return None


def crear_handler(s: Servicio):
    def api(ruta: str, q: dict):
        if ruta == "/api/flota":
            return s.flota()
        if ruta == "/api/estaciones":
            return {"estaciones": s.estaciones(), "fuente": FUENTE}
        if ruta == "/api/llegadas":
            return s.llegadas(
                q.get("parada", ""), _entero(q.get("minutos"), 20), _entero(q.get("limite"), 15), q.get("ruta") or None
            )
        if ruta == "/api/ruta":
            return s.ruta_detalle(q.get("ruta", ""), _real(q.get("lat")), _real(q.get("lon")), trazado=True, limite=200)
        if ruta == "/api/bus":
            return s.bus_detalle(q.get("bus", ""), q.get("placa") or None)
        if ruta == "/api/cerca":
            lat, lon = _real(q.get("lat")), _real(q.get("lon"))
            if lat is None or lon is None:
                return {"error": "Faltan lat y lon."}
            return s.paraderos_cerca(lat, lon, _entero(q.get("radio"), 800), 6)
        if ruta == "/api/alertas":
            return s.alertas(q.get("buscar"), q.get("ruta"), _entero(q.get("limite"), 30))
        if ruta == "/api/estado":
            return s.estado()
        return None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _enviar(self, cuerpo: bytes, tipo: str, codigo: int = 200) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json(self, obj, codigo: int = 200) -> None:
            self._enviar(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", codigo)

        def do_GET(self) -> None:
            u = urlparse(self.path)
            try:
                if u.path in ESTATICOS:
                    nombre, tipo = ESTATICOS[u.path]
                    # Se lee en cada visita: un cambio en el HTML se ve al recargar.
                    self._enviar((files("transmilenio_mcp") / "web" / nombre).read_bytes(), tipo)
                    return
                respuesta = api(u.path, {k: v[0] for k, v in parse_qs(u.query).items()})
                if respuesta is None:
                    self._json({"error": "No existe"}, 404)
                else:
                    self._json(respuesta)
            except PreparandoIndice as e:
                self._json({"preparando": True, "mensaje": str(e)}, 503)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description="Mapa local de TransMilenio en vivo")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    ap.add_argument("--veedor", action="store_true", help="guardar la flota cada minuto para el historial")
    a = ap.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    servicio = Servicio()
    if a.veedor:
        en_segundo_plano(servicio.feeds)
    srv = ThreadingHTTPServer((a.host, a.port), crear_handler(servicio))
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}"
    log(f"Mapa en {url} (Ctrl+C para salir)")
    if not a.no_abrir:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
