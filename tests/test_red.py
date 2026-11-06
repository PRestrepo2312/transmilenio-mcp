from transmilenio_mcp.dominio import estimacion
from transmilenio_mcp.dominio.modelos import Vehiculo


def test_buscar_prefiere_la_estacion_troncal(red):
    primera = red.paradas[red.buscar("calle 72")[0]]
    assert primera.es_estacion
    assert primera.nombre.startswith("Calle 72")


def test_resolver_ruta_y_parecidas(red):
    assert len(red.resolver_ruta("c25")) >= 2  # troncal y zonal comparten código
    assert red.resolver_ruta("ZZ9") == []
    assert red.resolver_ruta(None) == []
    assert "C25" in red.parecidas("C2")


def test_resumen_b10_va_al_nororiente(red):
    (rid,) = red.resolver_ruta("B10")
    rec = red.recorridos_de(rid)[0]
    r = red.resumen(rec)
    assert r.origen == "Portal 80"
    assert r.sentido == "Suroccidente-Nororiente"


def test_c25_zonal_es_circular_con_extremos(red):
    circulares = [
        red.resumen(rec)
        for rid in red.resolver_ruta("C25")
        for rec in red.recorridos_de(rid)
        if red.resumen(rec).circular
    ]
    assert circulares
    assert circulares[0].extremos and len(circulares[0].extremos) == 2


def _bus_en(red, rec, k, lat=None, lon=None, ts=1_000):
    p = red.paradas[rec.paradas[k]]
    return Vehiculo("x", "X1", "AAA000", rec.ruta_id, "v", lat or p.lat, lon or p.lon, p.id, rec.secuencias[k], ts)


def test_ubicar_usa_la_secuencia(red):
    rec = red.recorridos[0]
    v = _bus_en(red, rec, 3)
    assert red.ubicar(v) == (rec, 3)


def test_estimacion_crece_con_las_paradas(red):
    rec = max(red.recorridos, key=lambda r: len(r.paradas))
    v = _bus_en(red, rec, 2)
    tiempos = [estimacion.segundos_hasta(red, v, rec, 2, j) for j in range(3, 10)]
    assert tiempos == sorted(tiempos)
    # Parado en la parada k, le falta el tramo completo según el horario.
    assert tiempos[0] == rec.tiempos[3] - rec.tiempos[2]


def test_estimacion_bus_ya_en_la_siguiente_parada(red):
    rec = max(red.recorridos, key=lambda r: len(r.paradas))
    sig = red.paradas[rec.paradas[3]]
    v = _bus_en(red, rec, 2, lat=sig.lat, lon=sig.lon)
    assert estimacion.segundos_hasta(red, v, rec, 2, 3) == 0
    assert estimacion.segundos_hasta(red, v, rec, 2, 5) == rec.tiempos[5] - rec.tiempos[3]


def test_llegada_creible_y_reporte_vigente():
    assert estimacion.llegada_creible(-60)
    assert not estimacion.llegada_creible(-600)
    v = Vehiculo("x", "X", "P", "r", "v", 0, 0, "s", 1, ts=1_000)
    assert estimacion.reporte_vigente(v, ref=1_100)
    assert not estimacion.reporte_vigente(v, ref=1_000 + 3_600)
