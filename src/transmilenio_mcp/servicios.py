"""Lo que se le puede preguntar al sistema. El MCP y el mapa web llaman a esto mismo."""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from google.transit import gtfs_realtime_pb2 as gtfs

from . import FUENTE, config
from .config import log
from .datos.gtfs_estatico import obtener_indice
from .datos.gtfs_rt import FeedsRT
from .dominio import estimacion as est
from .dominio.modelos import Recorrido, Vehiculo
from .dominio.red import Red
from .dominio.texto import distancia_m, normalizar

BOGOTA = dt.timezone(dt.timedelta(hours=-5), "America/Bogota")

EFECTOS = {
    "NO_SERVICE": "sin servicio",
    "REDUCED_SERVICE": "servicio reducido",
    "SIGNIFICANT_DELAYS": "retrasos",
    "DETOUR": "desvío",
    "ADDITIONAL_SERVICE": "servicio adicional",
    "MODIFIED_SERVICE": "servicio modificado",
    "STOP_MOVED": "parada trasladada",
    "NO_EFFECT": "sin efecto",
    "ACCESSIBILITY_ISSUE": "problema de accesibilidad",
    "OTHER_EFFECT": "otro",
    "UNKNOWN_EFFECT": "desconocido",
}

NOTA_ESTIMACION = "Estimado con la posición del bus en su tramo y los tiempos del horario oficial."


class PreparandoIndice(Exception):
    pass


def _hora(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, BOGOTA).strftime("%H:%M")


def _iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, BOGOTA).isoformat(timespec="seconds")


def _acotar(n: int, minimo: int, maximo: int) -> int:
    return max(minimo, min(n, maximo))


# ---------------------------------------------------------------- red estática


class CargadorRed:
    """Carga la red en segundo plano, la reintenta si falló y la refresca cuando envejece.

    Mientras se refresca se sigue respondiendo con la red anterior; el cambio es una sola
    asignación, así que ninguna consulta ve una red a medias.
    """

    def __init__(self, obtener: Callable[[], dict] = obtener_indice, reloj: Callable[[], float] = time.time) -> None:
        self._obtener = obtener
        self._reloj = reloj
        self._red: Red | None = None
        self._cargada_en = 0.0
        self._error: Exception | None = None
        self._ultimo_intento = 0.0
        self._listo = threading.Event()
        self._candado = threading.Lock()
        # Bandera propia y no hilo.is_alive(): el hilo sigue "vivo" un instante después de
        # avisar que terminó, y en ese instante se perdía el siguiente refresco.
        self._cargando = False
        self._hilo: threading.Thread | None = None
        self._lanzar()

    def _lanzar(self) -> None:
        with self._candado:
            if self._cargando:
                return
            self._cargando = True
            self._ultimo_intento = self._reloj()
            if self._red is None:
                self._listo.clear()
            self._hilo = threading.Thread(target=self._cargar, daemon=True)
            self._hilo.start()

    def _cargar(self) -> None:
        red, error = None, None
        try:
            red = Red(self._obtener())
        except Exception as e:
            error = e
        # La red nueva y el fin de la carga se publican juntos: si alguien veía la red nueva
        # con _cargando todavía en True, el siguiente refresco se perdía.
        with self._candado:
            if red is not None:
                self._red, self._cargada_en, self._error = red, self._reloj(), None
            else:
                self._error = error
            self._cargando = False
        self._listo.set()
        log("Red de rutas y paradas cargada." if red is not None else f"No se pudo cargar la red: {error!r}")

    def _puede_reintentar(self) -> bool:
        return self._reloj() - self._ultimo_intento > config.INDICE_REINTENTO_S

    def red(self, espera_s: float = 45) -> Red:
        red = self._red
        if red is not None:
            vieja = self._reloj() - self._cargada_en > config.INDICE_MAX_EDAD_H * 3600
            if vieja and self._puede_reintentar():
                self._lanzar()
            return red
        if self._error and self._puede_reintentar():
            self._lanzar()
        if not self._listo.wait(espera_s):
            raise PreparandoIndice(
                "Preparando las rutas y paradas de TransMilenio. La primera vez se descarga el GTFS "
                "oficial (~180 MB) y tarda 1-3 minutos; intenta de nuevo en un momento."
            )
        if self._red is None:
            raise RuntimeError(
                f"No se pudo cargar la red ({self._error}). Se reintenta sola en un minuto; revisa la conexión."
            )
        return self._red


# ---------------------------------------------------------------- foto de la flota


@dataclass
class Foto:
    red: Red
    vehiculos: list[Vehiculo]
    ref: float  # "ahora" para las estimaciones: la hora real o la del último dato si el feed está detenido
    publico: dict  # frescura y avisos, para incluir en cada respuesta


class Servicio:
    def __init__(
        self,
        feeds: FeedsRT | None = None,
        cargador: CargadorRed | None = None,
        reloj: Callable[[], float] = time.time,
    ) -> None:
        self.feeds = feeds or FeedsRT(reloj=reloj)
        self.cargador = cargador or CargadorRed(reloj=reloj)
        self._reloj = reloj

    def _foto(self) -> Foto:
        red = self.cargador.red()
        vehs, lectura = self.feeds.vehiculos()
        ahora = self._reloj()
        ultimo = max((v.ts for v in vehs), default=0)
        edad = int(ahora - ultimo) if ultimo else None
        publico: dict = {"ultimo_reporte": _iso(ultimo) if ultimo else None, "edad_s": edad}
        detenido = edad is None or edad > config.FEED_VIEJO_S
        if detenido:
            hace = f"{edad // 60} min" if edad else "un buen rato"
            publico["aviso"] = (
                f"El feed de TransMilenio no se actualiza hace {hace}; "
                "las posiciones son del último reporte y pueden estar desactualizadas."
            )
        elif lectura.de_respaldo:
            publico["aviso"] = "No se pudo leer el feed de TransMilenio ahora; se usa la lectura anterior."
        ref = (ultimo or ahora) if detenido else ahora
        return Foto(red, vehs, ref, publico)

    def _bus(self, f: Foto, v: Vehiculo, retrasos: dict[str, int] | None = None) -> dict:
        ruta = f.red.rutas.get(v.ruta_id)
        d = {
            "ruta": ruta.codigo if ruta else v.ruta_id,
            "destino": ruta.nombre if ruta else "",
            "sistema": ruta.sistema if ruta else "",
            "bus": v.numero,
            "placa": v.placa,
            "lat": round(v.lat, 6),
            "lon": round(v.lon, 6),
            "ultima_parada": f.red.nombre(v.parada_id),
            "hace_s": max(0, int(f.ref - v.ts)),
        }
        if ubic := f.red.ubicar(v):
            rec, k = ubic
            d["destino"] = f.red.resumen(rec).destino  # el del recorrido, no el nombre comercial
            d["sentido"] = f.red.sentido_bus(rec, k)
            d["variante"] = rec.clave
            if k + 1 < len(rec.paradas):
                d["siguiente_parada"] = f.red.nombre(rec.paradas[k + 1])
        if retrasos and v.viaje_id in retrasos:
            d["retraso_s"] = retrasos[v.viaje_id]
        return d

    def _ficha_parada(self, red: Red, sid: str) -> dict:
        p = red.paradas[sid]
        codigos = sorted({red.rutas[r].codigo for r in red.rutas_de(sid) if r in red.rutas})
        d = {
            "id": sid,
            "nombre": p.nombre,
            "tipo": "estación" if p.es_estacion else ("vagón/plataforma" if p.estacion_id else "paradero"),
            "lat": p.lat,
            "lon": p.lon,
            "rutas": codigos[:60],
        }
        if p.estacion_id:
            d["estacion"] = red.nombre(p.estacion_id)
        return d

    def _error_ruta(self, red: Red, ruta: str, publico: dict | None = None) -> dict:
        return {"error": f"No existe la ruta «{ruta}».", "parecidas": red.parecidas(ruta), **(publico or {})}

    # ------------------------------------------------------------ paradas

    def buscar_parada(self, texto: str, limite: int = 8) -> dict:
        red = self.cargador.red()
        return {"resultados": [self._ficha_parada(red, s) for s in red.buscar(texto, limite)]}

    def paraderos_cerca(self, lat: float, lon: float, radio_m: int = 800, limite: int = 6) -> dict:
        red = self.cargador.red()
        radio = _acotar(radio_m, 100, 3000)
        cercanas: dict[str, float] = {}
        for p in red.paradas.values():
            if not red.rutas_de(p.id):
                continue
            clave = p.estacion_id or p.id  # un vagón cuenta como su estación
            d = distancia_m(lat, lon, p.lat, p.lon)
            if d <= radio and d < cercanas.get(clave, float("inf")):
                cercanas[clave] = d
        orden = sorted(cercanas, key=cercanas.get)[: _acotar(limite, 1, 20)]
        return {
            "centro": [lat, lon],
            "radio_m": radio,
            "paradas": [{**self._ficha_parada(red, s), "distancia_m": int(cercanas[s])} for s in orden],
        }

    # ------------------------------------------------------------ llegadas

    def llegadas(self, parada: str, minutos: int = 20, limite: int = 20, ruta: str | None = None) -> dict:
        f = self._foto()
        red = f.red
        sid, otras = red.resolver_parada(parada)
        if not sid:
            return {"error": f"No encontré una estación o paradero llamado «{parada}».", **f.publico}
        solo = None
        if ruta:
            solo = set(red.resolver_ruta(ruta))
            if not solo:
                return self._error_ruta(red, ruta, f.publico)
        objetivo = red.con_vagones(sid)
        retrasos = self.feeds.retrasos()
        horizonte = _acotar(minutos, 1, 90) * 60
        out = []
        for v in f.vehiculos:
            if (solo is not None and v.ruta_id not in solo) or not est.reporte_vigente(v, f.ref):
                continue
            if not (ubic := red.ubicar(v)):
                continue
            rec, k = ubic
            j = next((i for i in range(k + 1, len(rec.paradas)) if rec.paradas[i] in objetivo), None)
            if j is None:
                continue
            en_s = est.segundos_desde_ref(red, v, rec, k, j, f.ref)
            if not est.llegada_creible(en_s) or en_s > horizonte:
                continue
            en_s = max(0, en_s)
            out.append(
                {
                    **self._bus(f, v, retrasos),
                    "llega_en_min": round(en_s / 60, 1),
                    "hora_estimada": _hora(f.ref + en_s),
                    "paradas_antes": j - k - 1,
                    "llega_a": red.nombre(rec.paradas[j]),
                    "termina_aqui": j == len(rec.paradas) - 1,
                }
            )
        out.sort(key=lambda d: d["llega_en_min"])
        res = {
            "parada": self._ficha_parada(red, sid),
            "ventana_min": horizonte // 60,
            "total": len(out),
            "llegadas": out[: _acotar(limite, 1, 100)],
            "nota": NOTA_ESTIMACION,
            **f.publico,
        }
        if otras:
            res["otras_coincidencias"] = [
                {"id": o, "nombre": red.paradas[o].nombre, "tipo": self._ficha_parada(red, o)["tipo"]} for o in otras
            ]
        return res

    # ------------------------------------------------------------ rutas

    def ruta_detalle(
        self,
        ruta: str,
        lat: float | None = None,
        lon: float | None = None,
        trazado: bool = False,
        limite: int = 80,
    ) -> dict:
        """Variantes de una ruta (cada trazado), su sentido y los buses que van en cada una.

        Con lat/lon, cada variante trae además el paradero suyo más cercano a ese punto y en
        cuánto pasan por ahí los próximos buses.
        """
        f = self._foto()
        red = f.red
        ids = red.resolver_ruta(ruta)
        if not ids:
            return self._error_ruta(red, ruta, f.publico)
        retrasos = self.feeds.retrasos()

        por_variante: dict[str, list[Vehiculo]] = defaultdict(list)
        sueltos: dict[str, list[Vehiculo]] = defaultdict(list)  # buses de rutas sin recorrido en el índice
        for v in f.vehiculos:
            if v.ruta_id not in ids:
                continue
            if ubic := red.ubicar(v):
                por_variante[ubic[0].clave].append(v)
            else:
                sueltos[v.ruta_id].append(v)

        variantes = []
        for rid in ids:
            r = red.rutas[rid]
            for rec in red.recorridos_de(rid):
                variantes.append(
                    self._variante(
                        f,
                        r.codigo,
                        r.sistema,
                        rec,
                        por_variante.get(rec.clave, []),
                        retrasos,
                        lat,
                        lon,
                        trazado,
                        limite,
                    )
                )
            if sueltos.get(rid):
                buses = [self._bus(f, v, retrasos) for v in sueltos[rid]]
                variantes.append(
                    {
                        "variante": f"{rid}:?",
                        "ruta_id": rid,
                        "codigo": r.codigo,
                        "sistema": r.sistema,
                        "origen": None,
                        "destino": r.nombre,
                        "sentido": None,
                        "nota": "Recorrido no publicado en el GTFS del día; solo hay posiciones.",
                        "buses_en_via": len(buses),
                        "buses": buses[:limite],
                    }
                )
        variantes.sort(key=lambda x: -x["buses_en_via"])
        return {
            "ruta": red.rutas[ids[0]].codigo,
            "total_en_via": sum(x["buses_en_via"] for x in variantes),
            "variantes": variantes,
            **f.publico,
        }

    def _variante(self, f, codigo, sistema, rec: Recorrido, suyos, retrasos, lat, lon, trazado, limite) -> dict:
        red = f.red
        buses, por_sentido = [], defaultdict(int)
        for v in suyos:
            b = self._bus(f, v, retrasos)
            for c in ("ruta", "destino", "sistema", "variante"):
                b.pop(c, None)
            if b.get("sentido"):
                por_sentido[b["sentido"]] += 1
            buses.append(b)
        item = {
            "variante": rec.clave,
            "ruta_id": rec.ruta_id,
            "codigo": codigo,
            "sistema": sistema,
            **red.resumen(rec).publico(),
            "buses_en_via": len(suyos),
            "buses": buses[:limite],
        }
        if len(por_sentido) > 1:
            item["buses_por_sentido"] = dict(por_sentido)
        if trazado:
            item["trazado"] = [[red.paradas[s].lat, red.paradas[s].lon] for s in rec.paradas if s in red.paradas]
        if lat is not None and lon is not None:
            item["tu_parada"] = self._paso_cerca(f, rec, suyos, lat, lon)
        return item

    def _paso_cerca(self, f: Foto, rec: Recorrido, suyos: list[Vehiculo], lat: float, lon: float) -> dict | None:
        red = f.red
        candidatas = [s for s in rec.paradas if s in red.paradas]
        if not candidatas:
            return None
        mejor = min(candidatas, key=lambda s: distancia_m(lat, lon, red.paradas[s].lat, red.paradas[s].lon))
        p = red.paradas[mejor]
        dist = distancia_m(lat, lon, p.lat, p.lon)
        if dist > 3000:
            return None
        proximos = []
        for v in suyos:
            if not est.reporte_vigente(v, f.ref) or not (ubic := red.ubicar(v)):
                continue
            r2, k = ubic
            j = next((x for x in range(k + 1, len(r2.paradas)) if r2.paradas[x] == mejor), None)
            if j is None:
                continue
            en_s = est.segundos_desde_ref(red, v, r2, k, j, f.ref)
            if est.llegada_creible(en_s):
                proximos.append(
                    {"bus": v.numero, "llega_en_min": round(max(0, en_s) / 60, 1), "paradas_antes": j - k - 1}
                )
        proximos.sort(key=lambda x: x["llega_en_min"])
        return {
            "id": mejor,
            "nombre": red.lugar(mejor),
            "vagon": p.nombre if p.estacion_id else None,
            "lat": p.lat,
            "lon": p.lon,
            "distancia_m": int(dist),
            "proximos": proximos[:4],
        }

    # ------------------------------------------------------------ un bus

    def bus_detalle(self, bus: str, placa: str | None = None, pasadas: int = 3) -> dict:
        """Un bus y su recorrido: las últimas paradas que pasó y las próximas con hora estimada.

        `bus` es el número pintado en el bus (p. ej. "E0001") o la placa.
        """
        f = self._foto()
        red = f.red
        b = bus.strip().upper()
        v = next(
            (x for x in f.vehiculos if b in (x.numero.upper(), x.placa.upper()) and (not placa or x.placa == placa)),
            None,
        )
        if not v:
            return {"error": f"No encontré en vía un bus con número o placa «{bus}».", **f.publico}
        res = {**self._bus(f, v, self.feeds.retrasos()), "ruta_id": v.ruta_id, **f.publico}
        if not est.reporte_vigente(v, f.ref):
            res["aviso_bus"] = f"Este bus no reporta hace {int(f.ref - v.ts) // 60} min; los tiempos no son confiables."
        ubic = red.ubicar(v)
        if not ubic:
            res["paradas"] = []
            return res
        rec, k = ubic
        paradas: list[dict] = []
        for j in range(max(0, k - pasadas * 4), len(rec.paradas)):
            p = red.paradas.get(rec.paradas[j])
            if not p:
                continue
            item = {
                "id": p.id,
                "nombre": red.lugar(p.id),
                "lat": p.lat,
                "lon": p.lon,
                "estado": "pasada" if j < k else ("ultima" if j == k else "proxima"),
            }
            if p.estacion_id:
                item["vagon"] = p.nombre
            if j > k:
                en_s = est.segundos_desde_ref(red, v, rec, k, j, f.ref)
                if est.llegada_creible(en_s):
                    en_s = max(0, en_s)
                    item["llega_en_min"] = round(en_s / 60, 1)
                    item["hora"] = _hora(f.ref + en_s)
                else:
                    item["llega_en_min"] = None  # según el horario ya debió pasar; el bus va muy atrasado
            # Paraderos seguidos con el mismo nombre (un lado y otro de la vía) se muestran como uno.
            prev = paradas[-1] if paradas else None
            if prev and prev["nombre"] == item["nombre"]:
                if prev["estado"] == "pasada" and item["estado"] in ("pasada", "ultima"):
                    paradas[-1] = item
                continue
            paradas.append(item)
        ya = [p for p in paradas if p["estado"] == "pasada"]
        res["paradas"] = ya[-pasadas:] + [p for p in paradas if p["estado"] != "pasada"]
        res["trazado"] = [[red.paradas[s].lat, red.paradas[s].lon] for s in rec.paradas if s in red.paradas]
        res["indice_ultima"] = sum(1 for s in rec.paradas[: k + 1] if s in red.paradas) - 1
        res["nota"] = NOTA_ESTIMACION
        return res

    def buses_cerca(self, lat: float, lon: float, radio_m: int = 500, limite: int = 30) -> dict:
        f = self._foto()
        radio = _acotar(radio_m, 50, 5000)
        retrasos = self.feeds.retrasos()
        cerca = sorted(
            ((d, v) for v in f.vehiculos if (d := distancia_m(lat, lon, v.lat, v.lon)) <= radio),
            key=lambda x: x[0],
        )
        buses = [{**self._bus(f, v, retrasos), "distancia_m": int(d)} for d, v in cerca[: _acotar(limite, 1, 200)]]
        return {"centro": [lat, lon], "radio_m": radio, "total": len(cerca), "buses": buses, **f.publico}

    # ------------------------------------------------------------ alertas

    @staticmethod
    def _texto(ts: gtfs.TranslatedString) -> str:
        if not ts.translation:
            return ""
        es = next((t for t in ts.translation if t.language.lower().startswith("es")), ts.translation[0])
        return es.text.strip()

    def alertas(self, buscar: str | None = None, ruta: str | None = None, limite: int = 25) -> dict:
        red = self.cargador.red()
        ahora = self._reloj()
        q = normalizar(buscar) if buscar else None
        filtro = None
        if ruta:
            filtro = set(red.resolver_ruta(ruta))
            if not filtro:
                return self._error_ruta(red, ruta)
        out = []
        for a in self.feeds.alertas():
            vigente = not a.active_period or any(
                (not p.start or p.start <= ahora) and (not p.end or ahora <= p.end) for p in a.active_period
            )
            if not vigente:
                continue
            rids = {ie.route_id for ie in a.informed_entity if ie.route_id}
            sids = {ie.stop_id for ie in a.informed_entity if ie.stop_id}
            # Muchas alertas solo nombran paraderos: cuentan para la ruta si ella pasa por ahí.
            if filtro is not None and not (rids & filtro or any(red.rutas_de(s) & filtro for s in sids)):
                continue
            titulo, detalle = self._texto(a.header_text), self._texto(a.description_text)
            nombres = sorted({n for s in sids if (n := red.nombre(s))})
            codigos = sorted({red.rutas[r].codigo for r in rids if r in red.rutas})
            if q and q not in normalizar(" ".join([titulo, detalle, *nombres, *codigos])):
                continue
            efecto = gtfs.Alert.Effect.Name(a.effect)
            item = {
                "titulo": titulo,
                "detalle": detalle,
                "efecto": EFECTOS.get(efecto, efecto),
                "rutas": codigos[:40],
                "paradas": nombres[:20],
            }
            if a.active_period:
                p = a.active_period[0]
                item["desde"] = _iso(p.start) if p.start else None
                item["hasta"] = _iso(p.end) if p.end else None
            out.append(item)
        return {"total": len(out), "alertas": out[: _acotar(limite, 1, 100)]}

    # ------------------------------------------------------------ para el mapa

    CAMPOS_FLOTA = ["lat", "lon", "ruta", "destino", "sistema", "bus", "placa", "ultima_parada", "hace_s", "variante"]

    def flota(self) -> dict:
        f = self._foto()
        red = f.red
        filas = []
        for v in f.vehiculos:
            ruta = red.rutas.get(v.ruta_id)
            ubic = red.ubicar(v)
            filas.append(
                [
                    round(v.lat, 5),
                    round(v.lon, 5),
                    ruta.codigo if ruta else v.ruta_id,
                    red.resumen(ubic[0]).destino if ubic else (ruta.nombre if ruta else ""),
                    ruta.sistema if ruta else "",
                    v.numero,
                    v.placa,
                    red.nombre(v.parada_id) or "",
                    max(0, int(f.ref - v.ts)),
                    ubic[0].clave if ubic else f"{v.ruta_id}:?",
                ]
            )
        return {"campos": self.CAMPOS_FLOTA, "buses": filas, **f.publico}

    def estaciones(self) -> list[list]:
        return [[p.id, p.nombre, p.lat, p.lon] for p in self.cargador.red().estaciones_con_servicio()]

    def estado(self) -> dict:
        f = self._foto()
        por_sistema: dict[str, int] = defaultdict(int)
        for v in f.vehiculos:
            r = f.red.rutas.get(v.ruta_id)
            por_sistema[r.sistema if r else "?"] += 1
        cab = self.feeds.leer("posiciones").mensaje.header
        return {
            "buses_en_via": len(f.vehiculos),
            "por_sistema": dict(sorted(por_sistema.items(), key=lambda kv: -kv[1])),
            "rutas_activas": len({v.ruta_id for v in f.vehiculos}),
            **f.publico,
            "cabecera_feed": _iso(cab.timestamp) if cab.timestamp else None,
            "gtfs_estatico": f.red.info_gtfs,
            "feeds": {k: config.RT_BASE + v for k, v in config.FEEDS.items()},
            "fuente": FUENTE,
        }
