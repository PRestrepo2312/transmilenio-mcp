import gzip
import json

import httpx
import pytest

from transmilenio_mcp import config
from transmilenio_mcp.datos import gtfs_estatico
from transmilenio_mcp.datos.gtfs_rt import FeedsRT

from .conftest import FIXTURES


class Reloj:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _feeds(respuestas: list, reloj) -> tuple[FeedsRT, list]:
    llamadas = []

    def responder(req):
        llamadas.append(req.url.path)
        r = respuestas.pop(0)
        return r if isinstance(r, httpx.Response) else httpx.Response(200, content=r)

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    return FeedsRT(cliente=cliente, base="https://feed.test/", reloj=reloj), llamadas


def test_cache_evita_pedir_dos_veces():
    pb = (FIXTURES / "positions.pb").read_bytes()
    reloj = Reloj()
    feeds, llamadas = _feeds([pb, pb], reloj)
    feeds.leer("posiciones")
    reloj.t += config.FEED_TTL_S - 1
    feeds.leer("posiciones")
    assert len(llamadas) == 1


def test_si_falla_devuelve_la_copia_anterior():
    pb = (FIXTURES / "positions.pb").read_bytes()
    reloj = Reloj()
    feeds, _ = _feeds([pb, httpx.Response(503)], reloj)
    primera = feeds.leer("posiciones")
    reloj.t += config.FEED_TTL_S + 1
    segunda = feeds.leer("posiciones")
    assert segunda.de_respaldo
    assert len(segunda.mensaje.entity) == len(primera.mensaje.entity)


def test_sin_copia_anterior_el_error_se_propaga():
    feeds, _ = _feeds([httpx.Response(503)], Reloj())
    with pytest.raises(httpx.HTTPStatusError):
        feeds.leer("posiciones")


def test_elegir_mas_reciente_por_fecha_del_nombre():
    items = [
        {"name": "GTFS_20261105.zip", "updated": "2026-11-05T09:00:00Z"},
        {"name": "GTFS-2026-04-29.zip", "updated": "2026-11-06T00:00:00Z"},  # resubido: updated engaña
        {"name": "2026-03-20 04:00:29_Static.zip", "updated": "2026-03-20T04:00:00Z"},
        {"name": "leeme.txt", "updated": "2027-01-01T00:00:00Z"},
    ]
    assert gtfs_estatico.elegir_mas_reciente(items)["name"] == "GTFS_20261105.zip"


def test_listar_bucket_sigue_las_paginas():
    paginas = [
        {"items": [{"name": "a.zip"}], "nextPageToken": "t2"},
        {"items": [{"name": "b.zip"}]},
    ]
    tokens = []

    def responder(req):
        tokens.append(req.url.params.get("pageToken"))
        return httpx.Response(200, json=paginas.pop(0))

    with httpx.Client(transport=httpx.MockTransport(responder)) as c:
        items = gtfs_estatico.listar_bucket(c)
    assert [i["name"] for i in items] == ["a.zip", "b.zip"]
    assert tokens == [None, "t2"]


def test_cache_de_otra_version_no_se_usa_como_respaldo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "carpeta_cache", lambda: tmp_path)
    monkeypatch.setattr(config, "INDICE_URL", None)
    with gzip.open(tmp_path / "indice.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"version": gtfs_estatico.VERSION - 1}, f)

    def sin_red(_destino):
        raise ConnectionError("sin internet")

    monkeypatch.setattr(gtfs_estatico, "descargar", sin_red)
    with pytest.raises(ConnectionError):
        gtfs_estatico.obtener_indice()
