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

GTFS_BUCKET = "gtfs-estaticos"
INDICE_URL = os.environ.get("TRANSMI_INDICE_URL")
INDICE_MAX_EDAD_H = 72
INDICE_REINTENTO_S = 60

# Veedor: el recolector toma una foto del feed cada tanto y la guarda en SQLite.
VEEDOR_INTERVALO_S = 60
VEEDOR_DB = os.environ.get("TRANSMI_HISTORIAL")
# Una hora cuenta como observada si tiene al menos esta fracción de las fotos esperadas.
VEEDOR_COBERTURA_MIN = 0.5

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
