"""Servidor MCP: buses de TransMilenio en vivo para Claude o cualquier cliente MCP."""

from __future__ import annotations

import argparse
import functools
import logging

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import FUENTE, __version__
from .datos.historial import Historial
from .recolector import en_segundo_plano
from .servicios import PreparandoIndice, Servicio
from .veedor import Veedor

INSTRUCCIONES = f"""\
Datos en vivo del transporte público de Bogotá (TransMilenio troncal, duales, alimentadores,
SITP zonal y TransMiCable), leídos de los feeds GTFS Realtime públicos de TransMilenio S.A.

- "¿Cuándo llega mi bus a X?": `llegadas` (acepta el nombre de la estación).
- Una ruta (B10, C25, H710, 16-8): `buses_ruta`. Con lat/lon del usuario dice cuándo pasa por su paradero.
- Un bus concreto y sus próximas paradas: `proximas_paradas` con el número del bus.
- Cerca del usuario: `paraderos_cerca` o `buses_cerca`.
- Desvíos y cierres: `alertas`.
- Veedor (lo programado contra lo real): `programacion_ruta`, `ranking_rutas`, `historial_ruta`,
  `salud_feed`. Lo observado sale del historial que guarda `transmilenio-veedor`; si viene
  `sin_historial`, dilo y explica que hay que dejar ese comando corriendo.
- `ultima_parada` es la última a la que el bus YA llegó, no la siguiente.
- Los tiempos de llegada son estimados; dilo así.
- Si la respuesta trae `aviso`, el feed oficial está detenido o falló: dilo antes de dar datos.
- Si trae `nota_sentido` o `aviso_sentido`, faltan buses cuyo sentido aún no se conoce: dilo
  y sugiere volver a preguntar en uno o dos minutos.
- Responde en español y menciona que los datos son de TransMilenio S.A.

{FUENTE}
"""

mcp = MCPServer("transmilenio", title="TransMilenio en vivo", instructions=INSTRUCCIONES, version=__version__)
SOLO_LECTURA = ToolAnnotations(read_only_hint=True, open_world_hint=True)
_servicio: Servicio | None = None
_veedor: Veedor | None = None


def servicio() -> Servicio:
    global _servicio
    if _servicio is None:
        _servicio = Servicio()
    return _servicio


def veedor() -> Veedor:
    global _veedor
    if _veedor is None:
        _veedor = Veedor(servicio(), Historial())
    return _veedor


def _sin_excepciones(fn):
    # Una excepción tumbaría la llamada sin explicación; Claude entiende mejor un dict con "error".
    @functools.wraps(fn)
    def envoltura(*a, **kw):
        try:
            return fn(*a, **kw)
        except PreparandoIndice as e:
            return {"preparando": True, "mensaje": str(e)}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    return envoltura


def herramienta(fn):
    return mcp.tool(annotations=SOLO_LECTURA)(_sin_excepciones(fn))


@herramienta
def buscar_parada(nombre: str, limite: int = 8) -> dict:
    """Estaciones de TransMilenio y paraderos del SITP por nombre, sin importar tildes.

    Devuelve id, nombre, tipo (estación, vagón o paradero), coordenadas y rutas que paran ahí.
    Ejemplos: "Calle 72", "Portal Norte", "Ricaurte", "cl 80 kr 30".
    """
    return servicio().buscar_parada(nombre, limite)


@herramienta
def llegadas(parada: str, minutos: int = 20, limite: int = 20, ruta: str | None = None) -> dict:
    """Próximos buses que llegan a una estación o paradero, del más cercano al más lejano.

    `parada`: nombre ("Calle 72") o id de `buscar_parada`. En una estación incluye sus vagones.
    `minutos`: ventana de búsqueda, máximo 90. `ruta`: deja solo esa ruta ("¿cuándo pasa el
    B10 por Calle 72?"). Cada llegada trae ruta, destino, sentido, minutos y hora estimados,
    paradas que le faltan, vagón, número del bus, placa y retraso en segundos (positivo = tarde).
    """
    return servicio().llegadas(parada, minutos, limite, ruta)


@herramienta
def buses_ruta(ruta: str, lat: float | None = None, lon: float | None = None, limite: int = 40) -> dict:
    """Variantes de una ruta y dónde van ahora sus buses.

    `ruta`: el código del bus o la estación ("B10", "C25", "H710", "16-8"). Un código puede tener
    varias variantes (C25 troncal y C25 zonal, ida y regreso): cada una trae origen, destino,
    sentido ("Sur-Norte", "Circular"), número de paradas, duración típica y sus buses.
    Con `lat`/`lon` del usuario, cada variante trae `tu_parada`: su paradero más cercano y en
    cuántos minutos pasan los próximos buses por ahí.
    """
    return servicio().ruta_detalle(ruta, lat, lon, trazado=False, limite=limite)


@herramienta
def proximas_paradas(bus: str) -> dict:
    """Por dónde va un bus y sus próximas paradas con hora estimada.

    `bus`: el número pintado en el bus ("E0001", "Z70-4428") o la placa. `llegadas` y
    `buses_ruta` devuelven ese número.
    """
    return servicio().bus_detalle(bus)


@herramienta
def paraderos_cerca(lat: float, lon: float, radio_m: int = 800, limite: int = 6) -> dict:
    """Estaciones y paraderos con servicio más cercanos a un punto, con distancia y rutas."""
    return servicio().paraderos_cerca(lat, lon, radio_m, limite)


@herramienta
def buses_cerca(lat: float, lon: float, radio_m: int = 500, limite: int = 30) -> dict:
    """Buses en vía alrededor de un punto (radio de 50 a 5000 m), del más cercano al más lejano."""
    return servicio().buses_cerca(lat, lon, radio_m, limite)


@herramienta
def alertas(buscar: str | None = None, ruta: str | None = None, limite: int = 25) -> dict:
    """Alertas vigentes: desvíos, cierres, planes de manejo de tránsito.

    Filtra por texto (`buscar`: "Caracas", "calle 26") o por código de ruta.
    """
    return servicio().alertas(buscar, ruta, limite)


@herramienta
def programacion_ruta(ruta: str, fecha: str | None = None) -> dict:
    """Lo que el horario oficial programa para una ruta un día: viajes por hora y buses en vía.

    `fecha`: "hoy" (por defecto), "ayer" o "2026-11-06". Distingue hábil, sábado y festivo.
    No necesita historial. Sirve para "¿cuántos viajes tiene el C25 hoy?" o "¿a qué hora
    hay más buses del B10?".
    """
    return veedor().programacion(ruta, fecha)


@herramienta
def ranking_rutas(
    criterio: str = "buses",
    orden: str = "mas",
    fecha: str | None = None,
    desde_hora: int | None = None,
    hasta_hora: int | None = None,
    sistema: str | None = None,
    limite: int = 10,
) -> dict:
    """Rutas ordenadas para comparar: cuál tiene más o menos buses, cuál cumple menos su horario.

    `criterio`: "buses" (promedio en vía frente a lo programado), "cumplimiento" (viajes vistos
    sobre programados), "retraso" (minutos promedio frente al horario) o "programados" (viajes
    del horario, sin historial). `orden`: "mas" o "menos". `desde_hora`/`hasta_hora`: franja,
    p. ej. 6 y 9 para la hora pico de la mañana. `sistema`: "troncal", "zonal", "alimentador",
    "dual" o "transmicable".
    """
    return veedor().ranking_rutas(criterio, orden, fecha, desde_hora, hasta_hora, sistema, limite)


@herramienta
def historial_ruta(ruta: str, dias: int = 7, fecha: str | None = None) -> dict:
    """Cómo le ha ido a una ruta en los últimos días: buses promedio y máximo, viajes vistos
    contra programados, retraso promedio y el perfil por hora. `fecha` es el último día.
    """
    return veedor().historial_ruta(ruta, dias, fecha)


@herramienta
def salud_feed(dias: int = 3) -> dict:
    """Si el feed de TransMilenio está al día y cuándo ha estado caído (disponibilidad y caídas)."""
    return veedor().salud_feed(dias)


@herramienta
def estado_sistema() -> dict:
    """Cuántos buses hay en vía, por sistema, y qué tan fresco está el feed."""
    return servicio().estado()


def main() -> None:
    ap = argparse.ArgumentParser(description="Servidor MCP de TransMilenio en vivo")
    ap.add_argument("--http", action="store_true", help="servir por HTTP (streamable) en vez de stdio")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--veedor", action="store_true", help="guardar la flota cada minuto mientras el MCP esté prendido")
    a = ap.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    servicio()  # la red empieza a cargar desde ya, antes de la primera pregunta
    if a.veedor:
        en_segundo_plano(servicio().feeds)
    if a.http:
        mcp.run(transport="streamable-http", port=a.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
