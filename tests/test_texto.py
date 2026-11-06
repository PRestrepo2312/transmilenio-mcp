import pytest

from transmilenio_mcp.dominio.texto import codigo_ruta, distancia_m, normalizar, sentido


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Calle 72", "cl 72"),
        ("cll 72", "cl 72"),
        ("Estación Ricaurte", "ricaurte"),
        ("Portal de la 80", "portal 80"),
        ("Engativá", "engativa"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalizar(entrada, esperado):
    assert normalizar(entrada) == esperado


def test_codigo_ruta_sin_espacios_ni_mayusculas():
    assert codigo_ruta(" c 25 ") == "c25"
    assert codigo_ruta("16-8") == "168"


@pytest.mark.parametrize(
    ("grados", "esperado"),
    [
        (0, "Sur-Norte"),
        (180, "Norte-Sur"),
        (90, "Occidente-Oriente"),
        (56, "Suroccidente-Nororiente"),
        (359, "Sur-Norte"),
    ],
)
def test_sentido(grados, esperado):
    assert sentido(grados) == esperado


def test_distancia_un_centesimo_de_grado_de_latitud():
    assert distancia_m(4.60, -74.10, 4.61, -74.10) == pytest.approx(1112, abs=5)
