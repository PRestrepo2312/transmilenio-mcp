import os
import sys
from pathlib import Path

from . import __version__

RT_BASE = os.environ.get("TRANSMI_RT_BASE", "https://gtfs.transmilenio.gov.co/")
FEEDS = {
    "posiciones": "positions.pb",
    "viajes": "tripupdates.pb",
    "alertas": "alerts.pb",
}
# Cada bus reporta cada 10-80 s. Con 15 s de caché nadie le pega a TransMilenio
# más de 4 veces por minuto, sin importar cuántas preguntas lleguen.
FEED_TTL_S = 15
FEED_TIMEOUT_S = 20

# Si el reporte más nuevo del feed tiene más de esto, el feed está detenido.
FEED_VIEJO_S = 300
# Un bus cuyo último reporte es más viejo que esto (frente al resto del feed) no se usa
# para estimar llegadas: puede estar varado, fuera de servicio o sin GPS.
BUS_VIEJO_S = 300
# Si la llegada estimada quedó más de esto en el pasado, el bus probablemente ya pasó.
ETA_PASADA_TOLERANCIA_S = 120

# Rastro: para saber hacia dónde va un bus se compara su posición con una anterior que
# esté al menos a RASTRO_MIN_M y no tenga más de RASTRO_VENTANA_S.
RASTRO_MIN_M = 40
RASTRO_VENTANA_S = 420
RASTRO_MAX_PUNTOS = 12
# Después de cada consulta se sigue leyendo el feed en segundo plano por este tiempo, para
# que el rastro esté al día en la siguiente. TransMilenio regenera el feed cada ~60-75 s.
RASTREO_ACTIVO_S = 900
RASTREO_PASO_S = 20

# Tráfico por tramo, medido con la flota: cuánto tardan de verdad los buses frente al horario.
TRAFICO_VENTANA_S = 1200  # solo cuenta lo de los últimos 20 minutos
TRAFICO_MIN_MUESTRAS = 2
TRAFICO_MUESTRAS = 30  # por tramo, las más recientes
TRAFICO_MIN_S = 20  # trechos más cortos dicen poco (el reloj del GPS tiene su ruido)
TRAFICO_MAX_S = 900
# Se mide sobre al menos esto: así entran las esperas en semáforos y paradas.
TRAFICO_VENTANA_MIN_S = 240
TRAFICO_FACTOR_MIN = 0.3
TRAFICO_FACTOR_MAX = 4.0

GTFS_BUCKET = "gtfs-estaticos"
INDICE_URL = os.environ.get("TRANSMI_INDICE_URL")
INDICE_MAX_EDAD_H = 72
INDICE_REINTENTO_S = 60

# Veedor: el recolector toma una foto del feed cada tanto y la guarda en SQLite.
VEEDOR_INTERVALO_S = 60
VEEDOR_DB = os.environ.get("TRANSMI_HISTORIAL")
# Una hora cuenta como observada si tiene al menos esta fracción de las fotos esperadas.
VEEDOR_COBERTURA_MIN = 0.5
# Cada cuánto guarda el recolector los viajes programados/cancelados/añadidos del día. El feed
# de viajes trae el día entero (~80 mil viajes); no cambia tanto como las posiciones.
VEEDOR_ESTADOS_CADA_S = 600

USER_AGENT = f"transmilenio-mcp/{__version__}"


def carpeta_cache() -> Path:
    if base := os.environ.get("TRANSMI_CACHE"):
        p = Path(base)
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "transmilenio-mcp"
    else:
        p = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "transmilenio-mcp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log(msg: str) -> None:
    # stdout es del protocolo MCP; cualquier mensaje va a stderr.
    print(f"[transmilenio-mcp] {msg}", file=sys.stderr, flush=True)
