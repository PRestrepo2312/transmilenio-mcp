"""Cuánto le falta a un bus para llegar a una parada.

TransMilenio reporta la posición y la última parada alcanzada, no la hora prevista en
las siguientes. La estimación: qué parte del tramo actual ya recorrió el bus (por
distancia en línea recta) más los tiempos de horario de los tramos que le quedan.
"""

from __future__ import annotations

from .. import config
from .modelos import Recorrido, Vehiculo
from .red import Red
from .texto import distancia_m


def segundos_hasta(red: Red, v: Vehiculo, rec: Recorrido, k: int, j: int) -> float:
    """Desde el momento del reporte del bus hasta la parada j (j > k)."""
    a, b = red.paradas.get(rec.paradas[k]), red.paradas.get(rec.paradas[k + 1])
    tramo = rec.tiempos[k + 1] - rec.tiempos[k]
    avance = 0.0
    if a and b:
        largo = distancia_m(a.lat, a.lon, b.lat, b.lon)
        if largo > 1:
            avance = min(1.0, distancia_m(a.lat, a.lon, v.lat, v.lon) / largo)
    return (1 - avance) * tramo + (rec.tiempos[j] - rec.tiempos[k + 1])


def segundos_desde_ref(red: Red, v: Vehiculo, rec: Recorrido, k: int, j: int, ref: float) -> int:
    """Positivo: falta eso. Negativo: según el horario ya debió haber llegado."""
    return int(v.ts + segundos_hasta(red, v, rec, k, j) - ref)


def llegada_creible(en_s: int) -> bool:
    return en_s >= -config.ETA_PASADA_TOLERANCIA_S


def reporte_vigente(v: Vehiculo, ref: float) -> bool:
    return ref - v.ts <= config.BUS_VIEJO_S
