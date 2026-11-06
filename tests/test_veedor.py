import datetime as dt

import pytest

from transmilenio_mcp import config
from transmilenio_mcp.datos.gtfs_estatico import _programar
from transmilenio_mcp.datos.historial import Historial, fecha_hora
from transmilenio_mcp.recolector import recolectar
from transmilenio_mcp.veedor import Veedor


@pytest.fixture
def historial(tmp_path) -> Historial:
    return Historial(tmp_path / "historial.sqlite")


@pytest.fixture
def veedor(servicio, historial, ultimo_reporte) -> Veedor:
    return Veedor(servicio, historial, reloj=lambda: ultimo_reporte + 30)


@pytest.fixture
def una_foto_basta(monkeypatch):
    # Con una lectura por hora, una sola foto ya cuenta como hora observada.
    monkeypatch.setattr(config, "VEEDOR_INTERVALO_S", 3600)


def _grabar(servicio, historial, ultimo_reporte) -> list:
    vehs, _ = servicio.feeds.vehiculos()
    assert historial.registrar(ultimo_reporte + 30, vehs, servicio.feeds.retrasos())
    return vehs


# ---------------------------------------------------------------- programación


def test_programar_cuenta_salida_y_buses_en_via():
    prog = {"R": {}}
    _programar(prog, "R", "1", 6 * 3600 + 600, 6 * 3600 + 3000)  # 6:10 a 6:50
    _programar(
        prog, "R", "1", 6 * 3600 + 2400, 7 * 3600 + 1200
    )  # 6:40 a 7:20: no está andando a las 6:30 ni a las 7:30
    _programar(prog, "R", "1", 23 * 3600 + 3000, 24 * 3600 + 2400)  # 23:50 a 0:40 del día siguiente
    salidas, en_via = prog["R"]["1"]
    assert salidas[6] == 2 and salidas[23] == 1
    assert en_via[6] == 1 and en_via[7] == 0
    assert en_via[0] == 1  # las 24:30 del día de servicio


def test_servicios_activos_respetan_festivos(red):
    viernes = red.servicios_activos(dt.date(2026, 11, 6))
    assert "1" in viernes and "4" not in viernes
    assert red.servicios_activos(dt.date(2026, 11, 16)) == {"4"}  # lunes festivo: solo horario de domingo
    assert "4" in red.servicios_activos(dt.date(2026, 11, 8))


def test_programacion_c25_distingue_troncal_y_zonal(veedor):
    r = veedor.programacion("C25", "2026-11-06")
    assert r["tipo_dia"] == "viernes"
    troncal = next(x for x in r["rutas"] if x["sistema"] == "Troncal")
    assert troncal["viajes_programados"] == 214
    assert troncal["buses_en_pico"] > 0 and troncal["por_hora"]
    assert veedor.programacion("C25", "2026-11-16")["tipo_dia"] == "festivo (lunes)"


def test_programacion_ruta_inexistente(veedor):
    r = veedor.programacion("ZZ999")
    assert "error" in r


# ---------------------------------------------------------------- historial


def test_registrar_ignora_feed_detenido(servicio, historial, ultimo_reporte):
    vehs = _grabar(servicio, historial, ultimo_reporte)
    assert not historial.registrar(ultimo_reporte + 90, vehs)  # mismo último reporte: feed detenido
    fecha, hora = fecha_hora(ultimo_reporte)
    assert historial.cobertura([fecha]) == {(fecha, hora): 1}
    assert len(historial.lecturas(0)) == 2
    assert sum(n for *_, n, _r in historial.viajes([fecha])) > 0


def test_ranking_sin_historial_en_otro_dia(veedor):
    r = veedor.ranking_rutas("buses", fecha="2026-11-01")
    assert r["sin_historial"]


def test_ranking_cae_a_la_foto_en_vivo(veedor):
    r = veedor.ranking_rutas("buses", "mas")
    assert r["fuente"].startswith("foto en vivo")
    assert r["rutas"][0]["buses_ahora"] >= r["rutas"][-1]["buses_ahora"]


def test_ranking_programados_no_necesita_historial(veedor):
    r = veedor.ranking_rutas("programados", "mas", fecha="2026-11-06", sistema="troncal")
    assert r["rutas"] and all(x["sistema"] == "Troncal" for x in r["rutas"])
    vals = [x["viajes_programados"] for x in r["rutas"]]
    assert vals == sorted(vals, reverse=True)


def test_ranking_criterio_invalido(veedor):
    assert "error" in veedor.ranking_rutas("velocidad")


def test_ranking_con_historial(veedor, servicio, historial, ultimo_reporte, una_foto_basta):
    _grabar(servicio, historial, ultimo_reporte)
    fecha, hora = fecha_hora(ultimo_reporte)
    r = veedor.ranking_rutas("buses", "mas", fecha=fecha, desde_hora=hora, hasta_hora=hora + 1)
    assert r["horas_observadas"] == 1
    assert r["rutas"][0]["buses_promedio"] > 0
    menos = veedor.ranking_rutas("buses", "menos", fecha=fecha, desde_hora=hora, hasta_hora=hora + 1)
    assert menos["rutas"][0]["buses_promedio"] <= r["rutas"][0]["buses_promedio"]
    c = veedor.ranking_rutas("cumplimiento", "menos", fecha=fecha, desde_hora=hora, hasta_hora=hora + 1)
    assert all(x["viajes_programados"] >= 5 for x in c["rutas"])


def test_historial_ruta(veedor, servicio, historial, ultimo_reporte, una_foto_basta):
    assert veedor.historial_ruta("C25")["sin_historial"]
    _grabar(servicio, historial, ultimo_reporte)
    r = veedor.historial_ruta("C25", dias=3)
    dia = r["rutas"][0]["dias"][-1]
    assert dia["fecha"] == fecha_hora(ultimo_reporte)[0]
    assert dia["buses_promedio"] > 0 and dia["buses_programados_promedio"] > 0
    assert r["rutas"][0]["por_hora"]


# ---------------------------------------------------------------- caídas del feed


def test_salud_feed_marca_la_caida(veedor, servicio, historial, ultimo_reporte):
    vehs = _grabar(servicio, historial, ultimo_reporte)
    for minutos in (10, 20, 30):  # el feed sigue con el mismo último reporte
        historial.registrar(ultimo_reporte + minutos * 60, vehs)
    veedor._reloj = lambda: ultimo_reporte + 30 * 60
    r = veedor.salud_feed()
    assert r["caidas"][-1]["sigue"]
    assert r["caidas"][-1]["duracion_min"] == 30
    assert r["disponibilidad_pct"] == 25.0


def test_recolector_anota_y_no_duplica(servicio, historial):
    pausas = []
    recolectar(servicio.feeds, historial, intervalo=60, dormir=pausas.append, vueltas=3)
    lect = historial.lecturas(0)
    assert len(pausas) == 2
    assert len({u for _, u, _ in lect}) == 1  # los fixtures no cambian: una sola foto contada
