"""El feed desde el 10-nov-2026: stop_id, secuencia y start_time no corresponden al bus.

Solo la posición, la ruta y el bus son confiables, así que el recorrido y el sentido salen
de la geometría y del movimiento entre lecturas.
"""

import pytest

from transmilenio_mcp.datos.gtfs_rt import _salida_programada
from transmilenio_mcp.dominio.modelos import Vehiculo
from transmilenio_mcp.dominio.red import diferencia_angulo
from transmilenio_mcp.dominio.texto import distancia_m, rumbo
from transmilenio_mcp.servicios import Rastro, Servicio


def _punto(red, rec, k, t):
    a, b = red.paradas[rec.paradas[k]], red.paradas[rec.paradas[k + 1]]
    return a.lat + (b.lat - a.lat) * t, a.lon + (b.lon - a.lon) * t


def _bus(rec, lat, lon, ts, parada="no-existe", secuencia=999):
    return Vehiculo("b1", "X1", "AAA000", rec.ruta_id, "viaje", lat, lon, parada, secuencia, ts)


@pytest.fixture(scope="module")
def tramo_ambiguo(red):
    """Un tramo largo por donde la misma ruta pasa en los dos sentidos (ida y vuelta)."""
    for rec in sorted(red.recorridos, key=lambda r: r.indice):
        for k in range(len(rec.paradas) - 1):
            a, b = red.paradas.get(rec.paradas[k]), red.paradas.get(rec.paradas[k + 1])
            if not (a and b):
                continue
            lat, lon = _punto(red, rec, k, 0.5)
            v = _bus(rec, lat, lon, 1_000)
            if red.ubicar(v) is None and red.ubicar(v, rumbo(a.lat, a.lon, b.lat, b.lon)) == (rec, k):
                return rec, k
    pytest.skip("los fixtures no traen una ida y vuelta por la misma vía")


def test_parada_del_feed_que_no_cuadra_se_ignora(red):
    # Un recorrido que no sea circular: su última parada queda lejos del comienzo.
    rec = next(r for r in red.recorridos if not red.resumen(r).circular and len(r.paradas) > 10)
    lejos = red.paradas[rec.paradas[-1]]
    # El bus dice estar en la última parada, pero está a mitad del tramo 2.
    lat, lon = _punto(red, rec, 2, 0.5)
    assert distancia_m(lat, lon, lejos.lat, lejos.lon) > 2_000
    v = _bus(rec, lat, lon, 1_000, parada=lejos.id, secuencia=rec.secuencias[-1])
    a, b = red.paradas[rec.paradas[2]], red.paradas[rec.paradas[3]]
    ubic = red.ubicar(v, rumbo(a.lat, a.lon, b.lat, b.lon))
    assert ubic is not None
    # Puede caer en otra variante de la ruta que comparte ese tramo; lo que importa es que
    # quede donde está el bus y no en la parada que dijo el feed.
    assert ubic[0].ruta_id == rec.ruta_id
    assert red.cuadra(v, *ubic)
    assert ubic[0].paradas[ubic[1]] != lejos.id


def test_ida_y_vuelta_por_la_misma_via_necesitan_el_rumbo(red, tramo_ambiguo):
    rec, k = tramo_ambiguo
    a, b = red.paradas[rec.paradas[k]], red.paradas[rec.paradas[k + 1]]
    lat, lon = _punto(red, rec, k, 0.5)
    v = _bus(rec, lat, lon, 1_000)
    assert red.ubicar(v) is None  # sin rumbo no se adivina
    ida = rumbo(a.lat, a.lon, b.lat, b.lon)
    assert red.ubicar(v, ida) == (rec, k)
    # En sentido contrario es la vuelta: otro recorrido, u otro tramo del mismo si es circular.
    otro = red.ubicar(v, (ida + 180) % 360)
    assert otro is not None and otro != (rec, k)


def test_bus_lejos_de_su_ruta_no_se_ubica(red):
    rec = red.recorridos[0]
    assert red.ubicar(_bus(rec, 4.0, -74.5, 1_000), 0.0) is None


def test_rastro_da_el_rumbo_del_movimiento(red, tramo_ambiguo):
    rec, k = tramo_ambiguo
    r = Rastro()
    v1 = _bus(rec, *_punto(red, rec, k, 0.2), ts=1_000)
    r.anotar([v1])
    assert r.rumbo(v1) is None
    assert r.ubicar(red, v1) is None
    v2 = _bus(rec, *_punto(red, rec, k, 0.7), ts=1_060)
    r.anotar([v2])
    a, b = red.paradas[rec.paradas[k]], red.paradas[rec.paradas[k + 1]]
    assert diferencia_angulo(r.rumbo(v2), rumbo(a.lat, a.lon, b.lat, b.lon)) < 5
    assert r.ubicar(red, v2) == (rec, k)


def test_rastro_ignora_movimientos_minimos(red):
    rec = red.recorridos[0]
    p = red.paradas[rec.paradas[0]]
    r = Rastro()
    r.anotar([_bus(rec, p.lat, p.lon, 1_000)])
    quieto = _bus(rec, p.lat + 0.00005, p.lon, 1_030)  # ~5 m: ruido del GPS
    r.anotar([quieto])
    assert r.rumbo(quieto) is None


class FeedsFalsos:
    """Devuelve una lectura distinta en cada llamada, como el feed en vivo."""

    def __init__(self, lecturas):
        self.lecturas, self.i = lecturas, 0

    def vehiculos(self):
        vs = self.lecturas[min(self.i, len(self.lecturas) - 1)]
        self.i += 1

        class L:
            de_respaldo = False

        return vs, L()

    def retrasos(self):
        return {}


def test_llegadas_avisa_los_buses_sin_sentido_y_luego_los_incluye(red, indice, tramo_ambiguo):
    from transmilenio_mcp.servicios import CargadorRed

    rec, k = tramo_ambiguo
    destino = next(i for i in range(k + 2, len(rec.paradas)) if rec.paradas[i] in red.paradas)
    v1 = _bus(rec, *_punto(red, rec, k, 0.2), ts=1_000)
    v2 = _bus(rec, *_punto(red, rec, k, 0.7), ts=1_060)
    reloj = lambda: 1_070  # noqa: E731
    s = Servicio(
        feeds=FeedsFalsos([[v1], [v2]]),
        cargador=CargadorRed(obtener=lambda: indice, reloj=reloj),
        reloj=reloj,
        rastrear=False,
    )
    antes = s.llegadas(rec.paradas[destino], minutos=90)
    assert antes["total"] == 0
    assert antes["sin_sentido"] == 1
    assert "nota_sentido" in antes
    despues = s.llegadas(rec.paradas[destino], minutos=90)
    assert "sin_sentido" not in despues
    assert [x["bus"] for x in despues["llegadas"]] == ["X1"]
    assert despues["llegadas"][0]["ultima_parada"] == red.nombre(rec.paradas[k])


@pytest.mark.parametrize(
    "start_time,ts,esperado",
    [
        ("12:11:19", 1794330679, ""),  # 10-nov-2026 12:11:19 en Bogotá: es la hora del reporte
        ("09:49:00", 1794330679, "09:49:00"),
        ("", 1794330679, ""),
        ("24:05:00", 1794330679, "24:05:00"),
    ],
)
def test_salida_programada(start_time, ts, esperado):
    assert _salida_programada(start_time, ts) == esperado
