"""Tráfico por tramo medido con la flota y su uso en las llegadas."""

from transmilenio_mcp import config
from transmilenio_mcp.dominio import estimacion
from transmilenio_mcp.dominio.modelos import Vehiculo
from transmilenio_mcp.dominio.trafico import Trafico
from transmilenio_mcp.servicios import Rastro


def _recorrido_largo(red):
    # Uno con tiempos que avanzan de verdad entre paradas, para que el horario dé algo que medir.
    return max(
        red.recorridos, key=lambda r: sum(1 for a, b in zip(r.tiempos, r.tiempos[1:], strict=False) if b - a >= 30)
    )


def _punto(red, rec, k):
    p = red.paradas[rec.paradas[k]]
    return p.lat, p.lon


def _k_con_tiempo(rec, desde=1):
    return next(k for k in range(desde, len(rec.paradas) - 4) if rec.tiempos[k + 3] - rec.tiempos[k] >= 120)


def test_un_bus_que_tarda_el_doble_marca_factor_dos(red):
    rec = _recorrido_largo(red)
    k = _k_con_tiempo(rec)
    horario = rec.tiempos[k + 3] - rec.tiempos[k]
    t = Trafico()
    for i in range(2):  # hacen falta dos muestras
        t0 = 1_000 + i * 50
        t.observar(red, rec, k, (t0, *_punto(red, rec, k)), k + 3, (t0 + 2 * horario, *_punto(red, rec, k + 3)))
    ahora = 1_050 + 2 * horario
    for i in range(k, k + 3):
        assert t.factor(rec.paradas[i], rec.paradas[i + 1], ahora) == 2.0
    assert t.factor(rec.paradas[k + 3], rec.paradas[k + 4], ahora) is None
    assert t.tramos_medidos(ahora) >= 3


def test_las_muestras_viejas_no_cuentan(red):
    rec = _recorrido_largo(red)
    k = _k_con_tiempo(rec)
    horario = rec.tiempos[k + 3] - rec.tiempos[k]
    t = Trafico()
    for i in range(2):
        t.observar(
            red, rec, k, (1_000 + i, *_punto(red, rec, k)), k + 3, (1_000 + i + horario, *_punto(red, rec, k + 3))
        )
    tarde = 1_000 + horario + config.TRAFICO_VENTANA_S + 60
    assert t.factor(rec.paradas[k], rec.paradas[k + 1], tarde) is None


def test_trechos_imposibles_se_ignoran(red):
    rec = _recorrido_largo(red)
    k = _k_con_tiempo(rec)
    t = Trafico()
    p = _punto(red, rec, k)
    t.observar(red, rec, k, (1_000, *p), k + 3, (1_005, *_punto(red, rec, k + 3)))  # 5 s: muy corto
    t.observar(red, rec, k + 3, (1_000, *p), k, (1_200, *p))  # hacia atrás
    assert t.tramos_medidos(1_200) == 0


def test_la_llegada_usa_el_trafico_medido(red):
    rec = _recorrido_largo(red)
    k = _k_con_tiempo(rec)
    horario = rec.tiempos[k + 3] - rec.tiempos[k]
    t = Trafico()
    for i in range(2):
        t.observar(
            red, rec, k, (1_000 + i, *_punto(red, rec, k)), k + 3, (1_000 + i + 2 * horario, *_punto(red, rec, k + 3))
        )
    v = Vehiculo("b", "X", "P", rec.ruta_id, "v", *_punto(red, rec, k), "", 0, 1_000 + 2 * horario)
    sin = estimacion.segundos_hasta(red, v, rec, k, k + 3)
    con = estimacion.segundos_hasta(red, v, rec, k, k + 3, t, v.ts)
    assert sin == horario
    assert con == 2 * horario


def test_el_rastro_mide_trafico_al_ubicar(red):
    rec = _recorrido_largo(red)
    k = _k_con_tiempo(rec, desde=2)
    r = Rastro()
    horario = rec.tiempos[k + 3] - rec.tiempos[k]

    def bus(kk, ts, n):
        a, b = red.paradas[rec.paradas[kk]], red.paradas[rec.paradas[kk + 1]]
        # un poco después de la parada, para que el tramo quede claro
        return Vehiculo(
            f"b{n}",
            "X",
            "P",
            rec.ruta_id,
            "v",
            a.lat + (b.lat - a.lat) * 0.1,
            a.lon + (b.lon - a.lon) * 0.1,
            a.id,
            rec.secuencias[kk],
            ts,
        )

    for n in range(2):
        for v in (bus(k - 1, 1_000, n), bus(k, 1_030, n), bus(k + 3, 1_030 + horario, n)):
            r.anotar([v])
            r.ubicar(red, v)
    assert r.trafico.tramos_medidos(1_030 + horario) >= 3


def test_ritmo_de_un_recorrido(red):
    rec = _recorrido_largo(red)
    t = Trafico()
    assert t.ritmo(rec, 10_000) is None  # sin medidas no se inventa
    # Buses que tardan 1,5 veces el horario en cada trecho de 3 paradas, a lo largo de todo el recorrido.
    for i in range(2):
        for k in range(0, len(rec.paradas) - 3, 3):
            horario = rec.tiempos[k + 3] - rec.tiempos[k]
            if horario < 30 or 1.5 * horario > 800:
                continue
            ts = 1_000 + i
            t.observar(
                red, rec, k, (ts, *_punto(red, rec, k)), k + 3, (ts + round(1.5 * horario), *_punto(red, rec, k + 3))
            )
    r = t.ritmo(rec, 2_000)
    assert r is not None
    assert r["texto"] == "50 % más lento que el horario"
