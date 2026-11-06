from pathlib import Path

import httpx
import pytest
from google.transit import gtfs_realtime_pb2 as gtfs

from transmilenio_mcp.datos.gtfs_estatico import leer
from transmilenio_mcp.datos.gtfs_rt import FeedsRT
from transmilenio_mcp.dominio.red import Red
from transmilenio_mcp.servicios import CargadorRed, Servicio

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def indice() -> dict:
    return leer(FIXTURES / "indice.json.gz")


@pytest.fixture(scope="session")
def red(indice) -> Red:
    return Red(indice)


@pytest.fixture(scope="session")
def ultimo_reporte() -> int:
    msg = gtfs.FeedMessage()
    msg.ParseFromString((FIXTURES / "positions.pb").read_bytes())
    return max(e.vehicle.timestamp for e in msg.entity)


def transporte_fixtures() -> httpx.MockTransport:
    def responder(req: httpx.Request) -> httpx.Response:
        archivo = FIXTURES / req.url.path.rsplit("/", 1)[-1]
        if not archivo.exists():
            return httpx.Response(404)
        return httpx.Response(200, content=archivo.read_bytes())

    return httpx.MockTransport(responder)


@pytest.fixture
def servicio(indice, ultimo_reporte) -> Servicio:
    # El reloj se fija 30 s después del último reporte: el feed se ve "en vivo".
    reloj = lambda: ultimo_reporte + 30  # noqa: E731
    feeds = FeedsRT(cliente=httpx.Client(transport=transporte_fixtures()), base="https://feed.test/", reloj=reloj)
    return Servicio(feeds=feeds, cargador=CargadorRed(obtener=lambda: indice, reloj=reloj), reloj=reloj)
