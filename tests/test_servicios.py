import pytest

from transmilenio_mcp import config
from transmilenio_mcp.servicios import CargadorRed, PreparandoIndice


def test_llegadas_ordenadas_y_sin_tiempos_negativos(servicio):
    r = servicio.llegadas("Calle 72", minutos=30)
    assert r["parada"]["nombre"].startswith("Calle 72")
    minutos = [x["llega_en_min"] for x in r["llegadas"]]
    assert minutos == sorted(minutos)
    assert all(m >= 0 for m in minutos)
    assert "aviso" not in r


def test_llegadas_con_ruta_que_no_existe(servicio):
    r = servicio.llegadas("Calle 72", ruta="B1O")
    assert "error" in r
    assert "B10" in r["parecidas"]


def test_llegadas_parada_que_no_existe(servicio):
    assert "error" in servicio.llegadas("Estación que no existe en Bogotá xyz")


def test_ruta_c25_cuenta_todos_sus_buses(servicio):
    r = servicio.ruta_detalle("C25")
    flota = servicio.flota()["buses"]
    en_feed = sum(1 for fila in flota if fila[2] == "C25")
    assert r["total_en_via"] == en_feed
    claves = [v["variante"] for v in r["variantes"]]
    assert len(claves) == len(set(claves))


def test_ruta_con_ubicacion_trae_paradero_cercano(servicio):
    r = servicio.ruta_detalle("C25", lat=4.6950, lon=-74.0850)
    cercanos = [v["tu_parada"] for v in r["variantes"] if v.get("tu_parada")]
    assert cercanos
    assert min(c["distancia_m"] for c in cercanos) < 500


def test_bus_detalle(servicio):
    numero = servicio.flota()["buses"][0][5]
    r = servicio.bus_detalle(numero)
    estados = [p["estado"] for p in r["paradas"]]
    assert estados.count("ultima") == 1
    assert estados.index("ultima") < len(estados)
    assert "trazado" in r


def test_bus_que_no_existe(servicio):
    assert "error" in servicio.bus_detalle("NO-EXISTE")


def test_alertas_ruta_que_no_existe(servicio):
    assert "error" in servicio.alertas(ruta="ZZ99")


def test_estado(servicio):
    e = servicio.estado()
    assert e["buses_en_via"] > 0
    assert sum(e["por_sistema"].values()) == e["buses_en_via"]


class Reloj:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t


def test_cargador_reintenta_despues_de_un_error(indice):
    reloj, intentos = Reloj(), []

    def obtener():
        intentos.append(1)
        if len(intentos) == 1:
            raise ConnectionError("sin red")
        return indice

    c = CargadorRed(obtener=obtener, reloj=reloj)
    with pytest.raises(RuntimeError):
        c.red(espera_s=5)
    reloj.t += config.INDICE_REINTENTO_S + 1
    assert c.red(espera_s=5) is not None
    assert len(intentos) == 2


def test_cargador_refresca_la_red_vieja_sin_dejar_de_responder(indice):
    reloj, intentos = Reloj(), []

    def obtener():
        intentos.append(1)
        return indice

    c = CargadorRed(obtener=obtener, reloj=reloj)
    primera = c.red(espera_s=5)
    reloj.t += config.INDICE_MAX_EDAD_H * 3600 + 1
    assert c.red(espera_s=5) is primera  # responde con la anterior mientras refresca
    c._hilo.join(5)
    assert len(intentos) == 2
    assert c.red(espera_s=5) is not primera


def test_cargador_avisa_mientras_prepara():
    import threading

    soltar = threading.Event()
    c = CargadorRed(obtener=lambda: soltar.wait(5) and {}, reloj=Reloj())
    with pytest.raises(PreparandoIndice):
        c.red(espera_s=0.05)
    soltar.set()
