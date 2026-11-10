"""La red estática: rutas, paradas y recorridos, con las búsquedas que necesitan las consultas."""

from __future__ import annotations

import datetime as dt
import math
import re
from collections import defaultdict

from .modelos import Parada, Recorrido, Resumen, Ruta, Vehiculo
from .texto import codigo_ruta, distancia_m, normalizar, rumbo, sentido

SISTEMAS = {
    "1": "Troncal",
    "2": "Alimentador",
    "6": "Dual",
    "3": "Zonal",
    "4": "Zonal complementario",
    "5": "Zonal especial",
    "7": "TransMiCable",
}

# Origen y destino a menos de esto: la ruta sale y vuelve al mismo punto.
_RADIO_CIRCULAR_M = 800

# Si el bus está más lejos que esto del tramo que empieza en la parada que reporta, esa
# parada no es la suya. Desde el 10-nov-2026 el feed manda stop_id y current_stop_sequence
# que no corresponden a la posición (mediana de 6 km de diferencia).
_TOLERANCIA_PARADA_M = 400
# Un tramo (la recta entre dos paradas seguidas) cuenta como candidato si el bus está a
# menos de esto. Holgado porque la vía se curva entre paradas y la recta no.
_TOLERANCIA_TRAMO_M = 250
# Tramos a casi la misma distancia que el mejor se consideran empatados.
_HOLGURA_EMPATE_M = 60
# Diferencia máxima entre el rumbo del bus y el del tramo para decir que va en ese sentido.
_ANGULO_MAX = 75

# Proyección plana local: a la escala de Bogotá el error es de centímetros.
_M_LAT = 110_574.0
_M_LON = 111_320.0 * math.cos(math.radians(4.65))


def _xy(lat: float, lon: float) -> tuple[float, float]:
    return lon * _M_LON, lat * _M_LAT


def _a_segmento(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    largo2 = dx * dx + dy * dy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / largo2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def diferencia_angulo(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


class Red:
    def __init__(self, indice: dict) -> None:
        self.info_gtfs: dict = indice.get("gtfs", {})
        agencias = indice["agencias"]

        self.rutas: dict[str, Ruta] = {}
        self._nombre_comercial: dict[str, str] = {}
        for rid, (codigo, nombre, ag, _color) in indice["rutas"].items():
            self.rutas[rid] = Ruta(rid, codigo, nombre, SISTEMAS.get(ag, agencias.get(ag, ag)))
            self._nombre_comercial[rid] = nombre

        self.paradas: dict[str, Parada] = {
            sid: Parada(sid, nombre, lat, lon, padre or None, tipo == 1)
            for sid, (nombre, lat, lon, padre, tipo) in indice["paradas"].items()
        }

        self.recorridos: list[Recorrido] = [
            Recorrido(i, p["r"], tuple(p["p"]), tuple(p["q"]), tuple(p["t"])) for i, p in enumerate(indice["patrones"])
        ]
        self._por_ruta: dict[str, list[Recorrido]] = defaultdict(list)
        self._rutas_parada: dict[str, set[str]] = defaultdict(set)
        for rec in self.recorridos:
            self._por_ruta[rec.ruta_id].append(rec)
            for s in rec.paradas:
                self._rutas_parada[s].add(rec.ruta_id)

        self.hijos: dict[str, list[str]] = defaultdict(list)
        for p in self.paradas.values():
            if p.estacion_id:
                self.hijos[p.estacion_id].append(p.id)

        self._codigos: dict[str, list[str]] = defaultdict(list)
        for r in self.rutas.values():
            self._codigos[codigo_ruta(r.codigo)].append(r.id)

        # service_id -> calendario; ruta -> service_id -> [salidas por hora, en vía a cada HH:30]
        self.servicios: dict[str, dict] = indice.get("servicios", {})
        self._programacion: dict[str, dict[str, list[list[int]]]] = indice.get("programacion", {})
        self._activos: dict[str, set[str]] = {}

        self._nombres_norm = {sid: normalizar(p.nombre) for sid, p in self.paradas.items()}
        self._ubicacion: dict[tuple, tuple[Recorrido, int] | None] = {}
        self._resumenes: dict[int, Resumen] = {}
        # Por recorrido: cada tramo (k, inicio, fin, rumbo) en coordenadas planas.
        self._tramos: dict[int, list[tuple[int, tuple[float, float], tuple[float, float], float]]] = {}

    # ------------------------------------------------------------ paradas

    def nombre(self, parada_id: str) -> str | None:
        p = self.paradas.get(parada_id)
        return p.nombre if p else None

    def lugar(self, parada_id: str) -> str:
        """La estación si la parada es un vagón; si no, el paradero."""
        p = self.paradas.get(parada_id)
        if not p:
            return parada_id
        if p.estacion_id and (est := self.paradas.get(p.estacion_id)):
            return est.nombre
        return p.nombre

    def con_vagones(self, parada_id: str) -> set[str]:
        return {parada_id, *self.hijos.get(parada_id, ())}

    def rutas_de(self, parada_id: str) -> set[str]:
        return {r for s in self.con_vagones(parada_id) for r in self._rutas_parada.get(s, ())}

    def estaciones_con_servicio(self) -> list[Parada]:
        return [p for p in self.paradas.values() if p.es_estacion and self.rutas_de(p.id)]

    def buscar(self, texto: str, limite: int = 8) -> list[str]:
        q = normalizar(texto)
        if not q:
            return []
        palabras = set(q.split())
        puntaje = {}
        for sid, n in self._nombres_norm.items():
            if n == q:
                s = 100
            elif n.startswith(q):
                s = 80
            elif palabras <= set(n.split()):
                s = 60
            elif q in n:
                s = 40
            else:
                continue
            if self.paradas[sid].es_estacion:
                s += 25  # "Calle 72" es la estación troncal antes que el paradero zonal homónimo
            if not self.rutas_de(sid):
                s -= 50  # está en el GTFS pero sin rutas: fuera de servicio
            puntaje[sid] = s
        # Si la estación ya coincide, sus vagones sobran.
        for sid in list(puntaje):
            padre = self.paradas[sid].estacion_id
            if padre and padre in puntaje:
                del puntaje[sid]
        return sorted(puntaje, key=lambda s: (-puntaje[s], self.paradas[s].nombre))[: max(1, min(limite, 30))]

    def resolver_parada(self, texto: str) -> tuple[str | None, list[str]]:
        if texto in self.paradas:
            return texto, []
        encontradas = self.buscar(texto, limite=5)
        return (encontradas[0], encontradas[1:]) if encontradas else (None, [])

    # ------------------------------------------------------------ rutas

    def resolver_ruta(self, texto: str | None) -> list[str]:
        if not texto:
            return []
        if texto in self.rutas:
            return [texto]
        return list(self._codigos.get(codigo_ruta(texto), []))

    def parecidas(self, texto: str, limite: int = 15) -> list[str]:
        q = codigo_ruta(texto)
        if not q:
            return []
        return sorted({self.rutas[r].codigo for c, rs in self._codigos.items() if c.startswith(q[:2]) for r in rs})[
            :limite
        ]

    def recorridos_de(self, ruta_id: str) -> list[Recorrido]:
        return self._por_ruta.get(ruta_id, [])

    def ubicar(
        self,
        v: Vehiculo,
        rumbo_bus: float | None = None,
        previa: tuple[str, int] | None = None,
    ) -> tuple[Recorrido, int] | None:
        """Recorrido del bus y posición de su última parada en él.

        Primero con la parada que reporta el feed, si cuadra con la posición. Si no, por
        geometría: el tramo del recorrido más cercano al bus. `rumbo_bus` (hacia dónde se
        ha movido, en grados) separa la ida de la vuelta, que van por la misma vía; `previa`
        (variante, k) es donde se ubicó el bus la vez anterior y desempata.
        """
        ubic = self._ubicar_por_parada(v)
        if ubic and self.cuadra(v, *ubic):
            return ubic
        return self._ubicar_por_posicion(v, rumbo_bus, previa)

    def parada_del_feed_cuadra(self, v: Vehiculo) -> bool:
        ubic = self._ubicar_por_parada(v)
        return bool(ubic and self.cuadra(v, *ubic))

    def cuadra(self, v: Vehiculo, rec: Recorrido, k: int) -> bool:
        """¿El bus está cerca del tramo que empieza en la parada k?"""
        a = self._punto(rec.paradas[k])
        if a is None:
            return False
        b = self._punto(rec.paradas[k + 1]) if k + 1 < len(rec.paradas) else None
        return _a_segmento(*_xy(v.lat, v.lon), a, b or a) <= _TOLERANCIA_PARADA_M

    def _punto(self, parada_id: str) -> tuple[float, float] | None:
        p = self.paradas.get(parada_id)
        return _xy(p.lat, p.lon) if p else None

    def _tramos_de(self, rec: Recorrido):
        if rec.indice not in self._tramos:
            tramos = []
            for k in range(len(rec.paradas) - 1):
                a, b = self.paradas.get(rec.paradas[k]), self.paradas.get(rec.paradas[k + 1])
                if a and b and (a.lat, a.lon) != (b.lat, b.lon):
                    tramos.append((k, _xy(a.lat, a.lon), _xy(b.lat, b.lon), rumbo(a.lat, a.lon, b.lat, b.lon)))
            self._tramos[rec.indice] = tramos
        return self._tramos[rec.indice]

    def _ubicar_por_posicion(
        self, v: Vehiculo, rumbo_bus: float | None, previa: tuple[str, int] | None
    ) -> tuple[Recorrido, int] | None:
        px, py = _xy(v.lat, v.lon)
        candidatos = []  # (distancia, recorrido, k, rumbo del tramo)
        for rec in self.recorridos_de(v.ruta_id):
            for k, a, b, g in self._tramos_de(rec):
                d = _a_segmento(px, py, a, b)
                if d <= _TOLERANCIA_TRAMO_M:
                    candidatos.append((d, rec, k, g))
        if rumbo_bus is not None:
            candidatos = [c for c in candidatos if diferencia_angulo(c[3], rumbo_bus) <= _ANGULO_MAX]
        if not candidatos:
            return None
        minimo = min(c[0] for c in candidatos)
        cerca = [c for c in candidatos if c[0] <= minimo + _HOLGURA_EMPATE_M]

        # Seguir en la variante de la vez anterior, un poco más adelante, si está entre los empatados.
        if previa:
            clave, k_previo = previa
            siguen = [c for c in cerca if c[1].clave == clave and k_previo - 1 <= c[2]]
            if siguen:
                d, rec, k, _ = min(siguen, key=lambda c: (c[2], c[0]))
                return rec, k

        if rumbo_bus is None:
            # Sin saber hacia dónde va, solo vale si todos los empatados van en el mismo sentido;
            # si no, es la ida contra la vuelta por la misma vía y adivinar daría llegadas falsas.
            g0 = min(cerca, key=lambda c: c[0])[3]
            if any(diferencia_angulo(c[3], g0) > _ANGULO_MAX for c in cerca):
                return None
        d, rec, k, _ = min(cerca, key=lambda c: (c[0], c[1].indice))
        return rec, k

    def _ubicar_por_parada(self, v: Vehiculo) -> tuple[Recorrido, int] | None:
        """Con la parada y la secuencia que reporta el feed.

        Una misma parada puede aparecer en varios recorridos de la ruta (ida y vuelta pasan
        por el mismo paradero), así que se prefiere el que además coincide en número de
        secuencia con lo que reporta el bus.
        """
        clave = (v.ruta_id, v.parada_id, v.secuencia)
        if clave in self._ubicacion:
            return self._ubicacion[clave]
        candidato = None
        for rec in self.recorridos_de(v.ruta_id):
            for k, s in enumerate(rec.paradas):
                if s != v.parada_id:
                    continue
                if rec.secuencias[k] == v.secuencia:
                    self._ubicacion[clave] = (rec, k)
                    return rec, k
                candidato = candidato or (rec, k)
        self._ubicacion[clave] = candidato
        return candidato

    def resumen(self, rec: Recorrido) -> Resumen:
        if rec.indice in self._resumenes:
            return self._resumenes[rec.indice]
        a, b = self.paradas.get(rec.paradas[0]), self.paradas.get(rec.paradas[-1])
        base = {
            "origen": self.lugar(rec.paradas[0]),
            "destino": self.lugar(rec.paradas[-1]),
            "num_paradas": len(rec.paradas),
            "duracion_min": round(rec.tiempos[-1] / 60) if rec.tiempos else None,
        }
        comercial = self._nombre_comercial.get(rec.ruta_id, "")
        if "||" in comercial:
            # "A567 Porciúncula || G567 Parques de Bogotá" -> ("Porciúncula", "Parques de Bogotá")
            base["extremos"] = tuple(re.sub(r"^[A-Z]{1,3}\d+[A-Z]?\s+", "", x.strip()) for x in comercial.split("||"))

        if not (a and b):
            res = Resumen(sentido=None, rumbo=None, **base)
        elif distancia_m(a.lat, a.lon, b.lat, b.lon) < _RADIO_CIRCULAR_M:
            k_lejos = max(
                (k for k, s in enumerate(rec.paradas) if s in self.paradas),
                key=lambda k: distancia_m(
                    a.lat, a.lon, self.paradas[rec.paradas[k]].lat, self.paradas[rec.paradas[k]].lon
                ),
            )
            res = Resumen(
                sentido="Circular", rumbo=None, pasa_por=self.lugar(rec.paradas[k_lejos]), k_lejos=k_lejos, **base
            )
        else:
            g = rumbo(a.lat, a.lon, b.lat, b.lon)
            res = Resumen(sentido=sentido(g), rumbo=round(g), **base)
        self._resumenes[rec.indice] = res
        return res

    # ------------------------------------------------------------ programación

    def servicios_activos(self, fecha: dt.date) -> set[str]:
        """Los service_id que operan ese día, con festivos (calendar_dates) incluidos."""
        f = fecha.strftime("%Y%m%d")
        if f in self._activos:
            return self._activos[f]
        activos = set()
        for sid, s in self.servicios.items():
            if f in s["menos"]:
                continue
            en_vigencia = (not s["desde"] or s["desde"] <= f) and (not s["hasta"] or f <= s["hasta"])
            if f in s["mas"] or (en_vigencia and s["dias"][fecha.weekday()] == "1"):
                activos.add(sid)
        self._activos[f] = activos
        return activos

    def programado(self, ruta_id: str, fecha: dt.date) -> tuple[list[int], list[int]]:
        """Salidas por hora y buses que deberían estar en vía a cada HH:30, ese día."""
        salidas, en_via = [0] * 24, [0] * 24
        por_servicio = self._programacion.get(ruta_id, {})
        for sid in self.servicios_activos(fecha):
            if sid in por_servicio:
                s, e = por_servicio[sid]
                salidas = [a + b for a, b in zip(salidas, s, strict=True)]
                en_via = [a + b for a, b in zip(en_via, e, strict=True)]
        return salidas, en_via

    def rutas_programadas(self) -> list[str]:
        return list(self._programacion)

    def sentido_bus(self, rec: Recorrido, k: int) -> str | None:
        """En una circular depende de en qué mitad del recorrido va el bus."""
        res = self.resumen(rec)
        if not res.circular or res.k_lejos is None:
            return res.sentido
        if res.extremos and len(res.extremos) == 2:
            ida, vuelta = res.extremos[1], res.extremos[0]
        else:
            ida, vuelta = res.pasa_por, res.origen
        return f"Hacia {ida}" if k < res.k_lejos else f"Regresa a {vuelta}"
