"""Viajes cancelados y añadidos: el feed de viajes trae el día completo con su estado."""

import datetime as dt

import httpx
import pytest
from google.transit import gtfs_realtime_pb2 as gtfs

from transmilenio_mcp.datos.gtfs_rt import FeedsRT
from transmilenio_mcp.datos.historial import BOGOTA, Historial, contar_estados
from transmilenio_mcp.recolector import recolectar
from transmilenio_mcp.servicios import CargadorRed, Servicio
from transmilenio_mcp.veedor import Veedor

from .conftest import FIXTURES

R = gtfs.TripDescriptor.ScheduleRelationship


def _feed_viajes(red, fecha: str) -> tuple[bytes, dict[str, str]]:
    """Un tripupdates con el formato del 10-nov-2026 para la troncal y la zonal del C25."""
    ids = red.resolver_ruta("C25")
    troncal = next(r for r in ids if red.rutas[r].sistema == "Troncal")
    zonal = next(r for r in ids if red.rutas[r].sistema == "Zonal")
    msg = gtfs.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    viajes = [
        # zonal: 12 del horario a las 6 (4 cancelados), 1 añadido
        *[(zonal, f"06:{i * 5:02d}:00", R.CANCELED if i < 4 else R.SCHEDULED) for i in range(12)],
        (zonal, "06:30:00", R.ADDED),
        # zonal a las 7: 3 sin novedad
        *[(zonal, f"07:{i * 10:02d}:00", R.SCHEDULED) for i in range(3)],
        # troncal: 20 sin novedad
        *[(troncal, f"08:{i:02d}:00", R.SCHEDULED) for i in range(20)],
    ]
    for n, (rid, salida, estado) in enumerate(viajes):
        e = msg.entity.add(id=str(n))
        t = e.trip_update.trip
        t.trip_id, t.route_id, t.start_time, t.start_date, t.schedule_relationship = (
            f"V{n}.1.{rid}",
            rid,
            salida,
            fecha,
            estado,
        )
    return msg.SerializeToString(), {"troncal": troncal, "zonal": zonal}


@pytest.fixture
def escenario(red, indice, tmp_path):
    ahora = dt.datetime(2026, 11, 10, 13, 0, tzinfo=BOGOTA).timestamp()
    contenido, rutas = _feed_viajes(red, "20261110")

    def responder(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("tripupdates.pb"):
            return httpx.Response(200, content=contenido)
        return httpx.Response(200, content=(FIXTURES / req.url.path.rsplit("/", 1)[-1]).read_bytes())

    reloj = lambda: ahora  # noqa: E731
    feeds = FeedsRT(cliente=httpx.Client(transport=httpx.MockTransport(responder)), base="https://f.test/", reloj=reloj)
    s = Servicio(feeds=feeds, cargador=CargadorRed(obtener=lambda: indice, reloj=reloj), reloj=reloj, rastrear=False)
    h = Historial(tmp_path / "h.sqlite")
    return Veedor(s, h, reloj=reloj), h, rutas


def test_contar_estados_por_ruta_y_hora(red):
    contenido, rutas = _feed_viajes(red, "20261110")
    msg = gtfs.FeedMessage()
    msg.ParseFromString(contenido)
    feeds = FeedsRT(
        cliente=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=contenido)))
    )
    conteos = contar_estados(feeds.estados_viajes())
    assert conteos[("2026-11-10", rutas["zonal"], 6)] == [8, 4, 1]
    assert conteos[("2026-11-10", rutas["zonal"], 7)] == [3, 0, 0]
    assert conteos[("2026-11-10", rutas["troncal"], 8)] == [20, 0, 0]


def test_cancelados_de_hoy_sin_historial(escenario):
    veedor, _, rutas = escenario
    r = veedor.cancelaciones()
    assert r["fuente"] == "feed de viajes en vivo"
    # los cancelados son parte del horario: programados = 8 + 4 + 3 + 20
    assert r["total"] == {"programados": 35, "cancelados": 4, "pct_cancelado": 11.4, "anadidos": 1}
    assert r["rutas"][0]["ruta_id"] == rutas["zonal"]
    assert r["rutas"][0]["pct_cancelado"] == 26.7


def test_cancelados_de_una_ruta_trae_horas_y_salidas(escenario):
    veedor, _, rutas = escenario
    r = veedor.cancelaciones(ruta="C25")
    zonal = next(x for x in r["rutas"] if x["ruta_id"] == rutas["zonal"])
    assert zonal["salidas_canceladas"] == ["06:00", "06:05", "06:10", "06:15"]
    assert [h["hora"] for h in zonal["por_hora"]] == ["06:00", "07:00"]
    assert zonal["por_hora"][0]["cancelados"] == 4


def test_cancelados_en_una_franja(escenario):
    veedor, _, rutas = escenario
    r = veedor.cancelaciones(desde_hora=8, hasta_hora=9)
    assert r["franja"] == "08:00-09:00"
    assert r["total"]["cancelados"] == 0
    assert [x["ruta_id"] for x in r["rutas"]] == [rutas["troncal"]]


def test_la_consulta_de_hoy_queda_guardada_para_despues(escenario):
    veedor, historial, _ = escenario
    veedor.cancelaciones()
    assert len(historial.estados(["2026-11-10"])) == 3
    otro_dia = Veedor(veedor.servicio, historial, reloj=lambda: veedor._reloj() + 86400)
    r = otro_dia.cancelaciones(fecha="ayer")
    assert r["fuente"] == "historial local"
    assert r["total"]["cancelados"] == 4


def test_cancelados_sin_datos_de_ese_dia(escenario):
    veedor, _, _ = escenario
    r = veedor.cancelaciones(fecha="2026-11-01")
    assert r["sin_datos"]


def test_cancelados_fecha_o_ruta_invalidas(escenario):
    veedor, _, _ = escenario
    assert "error" in veedor.cancelaciones(fecha="mañana pasado")
    assert "error" in veedor.cancelaciones(ruta="ZZ99")


def test_recolector_guarda_los_estados(escenario):
    veedor, historial, _ = escenario
    recolectar(veedor.servicio.feeds, historial, intervalo=60, dormir=lambda s: None, vueltas=1)
    assert len(historial.estados(["2026-11-10"])) == 3
