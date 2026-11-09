"""Buses de TransMilenio en tiempo real vía MCP, sobre los datos abiertos oficiales."""

from importlib.metadata import PackageNotFoundError, version

# La versión vive solo en pyproject.toml.
try:
    __version__ = version("transmilenio-mcp")
except PackageNotFoundError:  # corriendo desde el código sin instalar
    __version__ = "0.0.0"

FUENTE = (
    "Datos: TransMilenio S.A., datos abiertos (GTFS y GTFS Realtime), licencia CC BY-SA 4.0. "
    "Proyecto independiente, no afiliado a TransMilenio S.A."
)
