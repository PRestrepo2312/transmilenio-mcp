"""Recolector del veedor: lee el feed cada minuto y lo guarda en el historial local.

    transmilenio-veedor                 corre hasta que lo detengas (Ctrl+C)
    transmilenio-veedor --intervalo 30
    transmilenio-veedor --db otra.sqlite

También corre dentro del mapa o del MCP con `--veedor`, mientras estén prendidos.

Es una lectura por minuto a cada feed de TransMilenio, lo mismo que una persona con el mapa
abierto. Si el feed está detenido, lo anota (para medir la caída) pero no cuenta buses.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
from collections.abc import Callable

from . import config
from .config import log
from .datos.gtfs_rt import FeedsRT
from .datos.historial import Historial


def una_vuelta(feeds: FeedsRT, historial: Historial, ahora: float) -> tuple[bool, int, int]:
    """Lee y guarda. Devuelve (había datos nuevos, buses en el feed, segundos del último reporte)."""
    vehiculos, _ = feeds.vehiculos()
    try:
        retrasos = feeds.retrasos()
    except Exception:
        retrasos = {}  # sin retrasos igual vale la pena guardar las posiciones
    nueva = historial.registrar(ahora, vehiculos, retrasos)
    ultimo = max((v.ts for v in vehiculos), default=0)
    return nueva, len(vehiculos), int(ahora - ultimo) if ultimo else -1


def recolectar(
    feeds: FeedsRT,
    historial: Historial,
    intervalo: float = config.VEEDOR_INTERVALO_S,
    reloj: Callable[[], float] = time.time,
    dormir: Callable[[float], None] = time.sleep,
    vueltas: int | None = None,
) -> None:
    estado_previo = None
    hechas = 0
    while vueltas is None or hechas < vueltas:
        inicio = reloj()
        try:
            nueva, buses, edad = una_vuelta(feeds, historial, inicio)
            # La primera lectura de un feed detenido también es "nueva" para el historial (se
            # guarda con la hora de su último reporte), pero el feed no está vivo.
            vivo = nueva and 0 <= edad <= config.FEED_VIEJO_S
            estado = "vivo" if vivo else "detenido"
            if estado != estado_previo:
                if vivo:
                    log(f"Feed en vivo: {buses} buses. Guardando cada {intervalo:.0f} s en {historial.ruta}")
                else:
                    log(f"El feed no trae datos nuevos (último reporte hace {edad // 60} min). Se anota la caída.")
                estado_previo = estado
        except Exception as e:
            log(f"No se pudo leer el feed: {e!r}. Se reintenta en {intervalo:.0f} s.")
            estado_previo = "error"
        hechas += 1
        if vueltas is None or hechas < vueltas:
            dormir(max(1.0, intervalo - (reloj() - inicio)))


def en_segundo_plano(feeds: FeedsRT, historial: Historial | None = None) -> threading.Thread:
    """Recolecta en un hilo aparte, compartiendo la caché de feeds con quien lo lanza."""
    hilo = threading.Thread(target=recolectar, args=(feeds, historial or Historial()), name="veedor", daemon=True)
    hilo.start()
    return hilo


def main() -> None:
    ap = argparse.ArgumentParser(description="Guarda la flota de TransMilenio cada minuto para el veedor.")
    ap.add_argument("--intervalo", type=float, default=config.VEEDOR_INTERVALO_S, help="segundos entre lecturas")
    ap.add_argument("--db", help="archivo SQLite (por defecto, en la caché)")
    a = ap.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    intervalo = max(20.0, a.intervalo)  # el feed se refresca cada ~15 s; más seguido no aporta
    try:
        recolectar(FeedsRT(), Historial(a.db), intervalo)
    except KeyboardInterrupt:
        log("Recolector detenido.")


if __name__ == "__main__":
    main()
