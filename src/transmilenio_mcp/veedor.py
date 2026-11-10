"""Preguntas de veedor: lo programado en el horario oficial contra lo que de verdad salió a la calle.

Dos fuentes:
- La programación viene del GTFS estático (siempre disponible): viajes que salen por hora y
  buses que deberían estar en vía.
- Lo observado viene del historial que arma `transmilenio-veedor` (ver datos/historial.py).
  Sin historial, las comparaciones caen a la foto en vivo del momento.

Solo se comparan horas "observadas", las que tienen suficientes fotos guardadas; comparar
una hora en la que el recolector estuvo apagado haría ver que no salió ningún bus.
"""

from __future__ import annotations

import datetime as dt
import time
from collections import Counter, defaultdict
from collections.abc import Callable

from . import config
from .datos.historial import BOGOTA, Historial, contar_estados
from .dominio import estimacion as est
from .dominio.red import Red
from .dominio.texto import normalizar
from .servicios import Servicio, _acotar, _iso

CRITERIOS = ("buses", "cumplimiento", "retraso", "programados")
DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
# Por debajo de esto un porcentaje de cumplimiento o un promedio de retraso dice poco.
MIN_VIAJES = 5
# En el ranking de cancelados: con menos viajes, 3 de 5 cancelados sale primero y dice poco.
MIN_VIAJES_CANCELADOS = 10
# Las cabinas del cable están en el horario (por frecuencia) pero no reportan en el feed en
# vivo: compararlas daría 0 % siempre.
SIN_FEED = {"TransMiCable"}
NOTA_SIN_FEED = "TransMiCable queda por fuera: sus cabinas no reportan en el feed en vivo."

SIN_HISTORIAL = (
    "Todavía no hay historial guardado para esas horas. Para medir lo que de verdad sale a la "
    "calle hay que dejar corriendo `transmilenio-veedor`, que toma una foto del feed cada minuto."
)


def _fotos_minimas_por_hora() -> int:
    return max(1, int(3600 / config.VEEDOR_INTERVALO_S * config.VEEDOR_COBERTURA_MIN))


def _h(hora: int) -> str:
    return f"{hora:02d}:00"


class Veedor:
    def __init__(self, servicio: Servicio, historial: Historial, reloj: Callable[[], float] = time.time) -> None:
        self.servicio = servicio
        self.historial = historial
        self._reloj = reloj

    # ------------------------------------------------------------ utilidades

    def _hoy(self) -> dt.date:
        return dt.datetime.fromtimestamp(self._reloj(), BOGOTA).date()

    def _dia(self, fecha: str | None) -> dt.date:
        if not fecha or fecha.strip().lower() == "hoy":
            return self._hoy()
        if fecha.strip().lower() == "ayer":
            return self._hoy() - dt.timedelta(days=1)
        return dt.date.fromisoformat(fecha.strip())

    @staticmethod
    def _horas(desde: int | None, hasta: int | None) -> list[int]:
        a = _acotar(desde if desde is not None else 0, 0, 23)
        b = _acotar(hasta if hasta is not None else 24, a + 1, 24)
        return list(range(a, b))

    @staticmethod
    def _tipo_dia(red: Red, d: dt.date) -> str:
        f = d.strftime("%Y%m%d")
        if any(f in red.servicios[s]["mas"] for s in red.servicios_activos(d)) and d.weekday() < 6:
            return f"festivo ({DIAS_SEMANA[d.weekday()]})"
        return DIAS_SEMANA[d.weekday()]

    def _observadas(self, fecha: str, horas: list[int]) -> tuple[list[int], dict[int, int]]:
        cob = self.historial.cobertura([fecha])
        fotos = {h: cob.get((fecha, h), 0) for h in horas}
        return [h for h in horas if fotos[h] >= _fotos_minimas_por_hora()], fotos

    @staticmethod
    def _ficha(red: Red, rid: str) -> dict:
        r = red.rutas.get(rid)
        return {"codigo": r.codigo if r else rid, "nombre": r.nombre if r else "", "sistema": r.sistema if r else ""}

    def _rutas(self, red: Red, sistema: str | None) -> list[str]:
        q = normalizar(sistema) if sistema else None
        return [rid for rid, r in red.rutas.items() if not q or q in normalizar(r.sistema)]

    # ------------------------------------------------------------ programación (sin historial)

    def programacion(self, ruta: str, fecha: str | None = None) -> dict:
        red = self.servicio.cargador.red()
        ids = red.resolver_ruta(ruta)
        if not ids:
            return self.servicio._error_ruta(red, ruta)
        d = self._dia(fecha)
        out = []
        for rid in ids:
            salidas, en_via = red.programado(rid, d)
            total = sum(salidas)
            item = {**self._ficha(red, rid), "ruta_id": rid, "viajes_programados": total}
            if total:
                horas_con = [h for h in range(24) if salidas[h] or en_via[h]]
                pico = max(range(24), key=lambda h: en_via[h])
                item.update(
                    primera_hora=_h(horas_con[0]),
                    ultima_hora=_h(horas_con[-1]),
                    hora_pico=_h(pico),
                    buses_en_pico=en_via[pico],
                    por_hora=[{"hora": _h(h), "salidas": salidas[h], "buses_en_via": en_via[h]} for h in horas_con],
                )
            else:
                item["nota"] = "No tiene viajes programados ese día."
            out.append(item)
        return {
            "fecha": d.isoformat(),
            "tipo_dia": self._tipo_dia(red, d),
            "rutas": out,
            "nota": "Según el horario oficial (GTFS) de TransMilenio. `buses_en_via` es cuántos viajes deberían "
            "estar andando a la media hora.",
        }

    # ------------------------------------------------------------ ranking

    def ranking_rutas(
        self,
        criterio: str = "buses",
        orden: str = "mas",
        fecha: str | None = None,
        desde_hora: int | None = None,
        hasta_hora: int | None = None,
        sistema: str | None = None,
        limite: int = 10,
    ) -> dict:
        criterio = (criterio or "buses").strip().lower()
        if criterio not in CRITERIOS:
            return {"error": f"Criterio «{criterio}» no existe.", "criterios": list(CRITERIOS)}
        mas = (orden or "mas").strip().lower().replace("á", "a") != "menos"
        red = self.servicio.cargador.red()
        d = self._dia(fecha)
        horas = self._horas(desde_hora, hasta_hora)
        candidatas = self._rutas(red, sistema)
        base = {
            "criterio": criterio,
            "orden": "más" if mas else "menos",
            "fecha": d.isoformat(),
            "tipo_dia": self._tipo_dia(red, d),
            "horas": f"{_h(horas[0])}-{_h(horas[-1] + 1)}",
        }
        if sistema:
            base["sistema"] = sistema

        if criterio == "programados":
            filas = []
            for rid in candidatas:
                salidas, en_via = red.programado(rid, d)
                n = sum(salidas[h] for h in horas)
                if n:
                    filas.append(
                        {
                            **self._ficha(red, rid),
                            "viajes_programados": n,
                            "buses_en_via_max": max(en_via[h] for h in horas),
                        }
                    )
            filas.sort(key=lambda x: x["viajes_programados"], reverse=mas)
            return {**base, "total_rutas": len(filas), "rutas": filas[: _acotar(limite, 1, 50)]}

        candidatas = [rid for rid in candidatas if red.rutas[rid].sistema not in SIN_FEED]
        if not candidatas:
            return {**base, "rutas": [], "mensaje": NOTA_SIN_FEED}
        cubiertas, _ = self._observadas(d.isoformat(), horas)
        if not cubiertas:
            if criterio == "buses" and d == self._hoy():
                return {**base, **self._ranking_en_vivo(red, candidatas, mas, limite)}
            return {**base, "sin_historial": True, "mensaje": SIN_HISTORIAL}
        base["horas_observadas"] = len(cubiertas)
        if len(cubiertas) < len(horas):
            base["horas_sin_datos"] = [_h(h) for h in horas if h not in cubiertas]

        if criterio == "buses":
            filas = self._ranking_buses(red, d, candidatas, cubiertas)
            base["toda_la_red"] = self._total(filas, "buses_promedio", "buses_programados_promedio")
            filas.sort(key=lambda x: (x["buses_promedio"], x["buses_programados_promedio"]), reverse=mas)
            nota = (
                "buses_promedio: buses en vía en promedio en las horas observadas. porcentaje: frente a los que "
                "el horario dice que deberían estar andando."
            )
        elif criterio == "cumplimiento":
            filas = [
                x for x in self._ranking_viajes(red, d, candidatas, cubiertas) if x["viajes_programados"] >= MIN_VIAJES
            ]
            filas.sort(key=lambda x: x["cumplimiento_pct"], reverse=mas)
            nota = (
                "cumplimiento_pct: viajes vistos en el feed sobre viajes programados que salían en esas horas. "
                "Un viaje cuenta si su bus reportó al menos una vez."
            )
        else:
            filas = [
                x
                for x in self._ranking_viajes(red, d, candidatas, cubiertas)
                if x["viajes_vistos"] >= MIN_VIAJES and x.get("retraso_promedio_min") is not None
            ]
            filas.sort(key=lambda x: x["retraso_promedio_min"], reverse=mas)
            nota = (
                "retraso_promedio_min: último retraso reportado por cada viaje frente a su horario (positivo = tarde)."
            )
        return {**base, "total_rutas": len(filas), "rutas": filas[: _acotar(limite, 1, 50)], "nota": nota}

    def _ranking_buses(self, red: Red, d: dt.date, candidatas: list[str], horas: list[int]) -> list[dict]:
        fecha = d.isoformat()
        cob = self.historial.cobertura([fecha])
        fotos = sum(cob.get((fecha, h), 0) for h in horas)
        suma, maximo = Counter(), Counter()
        for _f, h, rid, s, m in self.historial.conteos([fecha]):
            if h in horas:
                suma[rid] += s
                maximo[rid] = max(maximo[rid], m)
        filas = []
        for rid in candidatas:
            _, en_via = red.programado(rid, d)
            prog = sum(en_via[h] for h in horas) / len(horas)
            if not prog and not suma[rid]:
                continue
            obs = suma[rid] / fotos
            item = {
                **self._ficha(red, rid),
                "buses_promedio": round(obs, 1),
                "buses_maximo": maximo[rid],
                "buses_programados_promedio": round(prog, 1),
            }
            if prog:
                item["porcentaje"] = round(100 * obs / prog)
            filas.append(item)
        return filas

    @staticmethod
    def _total(filas: list[dict], observado: str, programado: str) -> dict:
        obs = sum(x[observado] for x in filas)
        prog = sum(x[programado] for x in filas)
        return {
            "buses": round(obs),
            "programados": round(prog),
            "porcentaje": round(100 * obs / prog) if prog else None,
            "nota": NOTA_SIN_FEED,
        }

    def _ranking_viajes(self, red: Red, d: dt.date, candidatas: list[str], horas: list[int]) -> list[dict]:
        fecha = d.isoformat()
        vistos, retraso_pond = Counter(), defaultdict(float)
        con_retraso = Counter()
        for _f, rid, h, n, ret in self.historial.viajes([fecha]):
            if h in horas:
                vistos[rid] += n
                if ret is not None:
                    retraso_pond[rid] += ret * n
                    con_retraso[rid] += n
        filas = []
        for rid in candidatas:
            salidas, _ = red.programado(rid, d)
            prog = sum(salidas[h] for h in horas)
            if not prog and not vistos[rid]:
                continue
            item = {**self._ficha(red, rid), "viajes_programados": prog, "viajes_vistos": vistos[rid]}
            item["cumplimiento_pct"] = round(100 * vistos[rid] / prog) if prog else None
            if con_retraso[rid]:
                item["retraso_promedio_min"] = round(retraso_pond[rid] / con_retraso[rid] / 60, 1)
            filas.append(item)
        return [x for x in filas if x["cumplimiento_pct"] is not None or x["viajes_vistos"]]

    def _ranking_en_vivo(self, red: Red, candidatas: list[str], mas: bool, limite: int) -> dict:
        f = self.servicio._foto()
        if f.publico.get("aviso"):
            return {"sin_historial": True, "mensaje": SIN_HISTORIAL, **f.publico}
        hora = dt.datetime.fromtimestamp(f.ref, BOGOTA).hour
        vivos = Counter(v.ruta_id for v in f.vehiculos if est.reporte_vigente(v, f.ref))
        filas = []
        for rid in candidatas:
            prog = red.programado(rid, self._hoy())[1][hora]
            if not prog and not vivos[rid]:
                continue
            item = {**self._ficha(red, rid), "buses_ahora": vivos[rid], "buses_programados": prog}
            if prog:
                item["porcentaje"] = round(100 * vivos[rid] / prog)
            filas.append(item)
        total = self._total(filas, "buses_ahora", "buses_programados")
        filas.sort(key=lambda x: (x["buses_ahora"], x["buses_programados"]), reverse=mas)
        return {
            "fuente": "foto en vivo (no hay historial de hoy)",
            "toda_la_red": total,
            "total_rutas": len(filas),
            "rutas": filas[: _acotar(limite, 1, 50)],
            "nota": f"Buses reportando ahora frente a los que el horario pone en vía a las {hora:02d}:30.",
            **f.publico,
        }

    # ------------------------------------------------------------ una ruta en el tiempo

    def historial_ruta(self, ruta: str, dias: int = 7, fecha: str | None = None) -> dict:
        red = self.servicio.cargador.red()
        ids = red.resolver_ruta(ruta)
        if not ids:
            return self.servicio._error_ruta(red, ruta)
        fin = self._dia(fecha)
        fechas = [(fin - dt.timedelta(days=i)) for i in range(_acotar(dias, 1, 60) - 1, -1, -1)]
        isos = [d.isoformat() for d in fechas]
        cob = self.historial.cobertura(isos)
        minimo = _fotos_minimas_por_hora()
        if not any(n >= minimo for n in cob.values()):
            return {"ruta": red.rutas[ids[0]].codigo, "sin_historial": True, "mensaje": SIN_HISTORIAL}

        conteos = defaultdict(lambda: [0, 0])  # (rid, fecha, hora) -> [suma, máximo]
        for f, h, rid, s, m in self.historial.conteos(isos, ids):
            conteos[(rid, f, h)] = [s, m]
        viajes = {}
        for f, rid, h, n, ret in self.historial.viajes(isos, ids):
            viajes[(rid, f, h)] = (n, ret)

        rutas = []
        for rid in ids:
            por_dia, perfil = [], defaultdict(lambda: [0.0, 0.0, 0])  # hora -> [obs, prog, días]
            for d in fechas:
                f = d.isoformat()
                horas = [h for h in range(24) if cob.get((f, h), 0) >= minimo]
                if not horas:
                    continue
                salidas, en_via = red.programado(rid, d)
                fotos = sum(cob[(f, h)] for h in horas)
                suma = sum(conteos[(rid, f, h)][0] for h in horas if (rid, f, h) in conteos)
                vistos = sum(viajes[(rid, f, h)][0] for h in horas if (rid, f, h) in viajes)
                retrasos = [
                    (viajes[(rid, f, h)]) for h in horas if (rid, f, h) in viajes and viajes[(rid, f, h)][1] is not None
                ]
                prog_viajes = sum(salidas[h] for h in horas)
                dia = {
                    "fecha": f,
                    "dia": self._tipo_dia(red, d),
                    "horas_observadas": len(horas),
                    "buses_promedio": round(suma / fotos, 1),
                    "buses_maximo": max((conteos[(rid, f, h)][1] for h in horas if (rid, f, h) in conteos), default=0),
                    "buses_programados_promedio": round(sum(en_via[h] for h in horas) / len(horas), 1),
                    "viajes_vistos": vistos,
                    "viajes_programados": prog_viajes,
                }
                if prog_viajes:
                    dia["cumplimiento_pct"] = round(100 * vistos / prog_viajes)
                if retrasos:
                    n_ret = sum(n for n, _ in retrasos)
                    dia["retraso_promedio_min"] = round(sum(n * r for n, r in retrasos) / n_ret / 60, 1)
                por_dia.append(dia)
                for h in horas:
                    p = perfil[h]
                    p[0] += conteos[(rid, f, h)][0] / cob[(f, h)] if (rid, f, h) in conteos else 0
                    p[1] += en_via[h]
                    p[2] += 1
            if not por_dia:
                continue
            rutas.append(
                {
                    **self._ficha(red, rid),
                    "ruta_id": rid,
                    "dias": por_dia,
                    "por_hora": [
                        {
                            "hora": _h(h),
                            "buses_promedio": round(p[0] / p[2], 1),
                            "buses_programados": round(p[1] / p[2], 1),
                        }
                        for h, p in sorted(perfil.items())
                        if p[0] or p[1]
                    ],
                }
            )
        return {
            "ruta": red.rutas[ids[0]].codigo,
            "desde": isos[0],
            "hasta": isos[-1],
            "rutas": rutas,
            "nota": "Solo cuentan las horas en que el recolector estuvo prendido. Los programados salen del "
            "horario oficial de hoy aplicado a cada fecha.",
        }

    # ------------------------------------------------------------ viajes cancelados

    def cancelaciones(
        self,
        ruta: str | None = None,
        fecha: str | None = None,
        desde_hora: int | None = None,
        hasta_hora: int | None = None,
        sistema: str | None = None,
        orden: str = "mas",
        limite: int = 10,
    ) -> dict:
        """Viajes que TransMilenio marca como cancelados (y los añadidos) frente a los programados.

        Hoy sale del feed de viajes en vivo, que trae el día completo; otros días, de lo que
        guardó el recolector. Sin ruta: totales, por sistema y ranking de rutas por porcentaje
        cancelado. Con ruta: el detalle por hora y, si es hoy, las salidas canceladas.
        """
        red = self.servicio.cargador.red()
        try:
            d = self._dia(fecha)
        except ValueError:
            return {"error": f"Fecha no válida: «{fecha}». Usa hoy, ayer o AAAA-MM-DD."}
        iso, hoy = d.isoformat(), d == self._hoy()
        horas = set(self._horas(desde_hora, hasta_hora))
        ids = None
        if ruta:
            ids = red.resolver_ruta(ruta)
            if not ids:
                return {"error": f"No existe la ruta «{ruta}».", "parecidas": red.parecidas(ruta)}

        salidas_canceladas: dict[str, list[str]] = defaultdict(list)
        if hoy:
            estados = [e for e in self.servicio.feeds.estados_viajes() if e.fecha == d.strftime("%Y%m%d")]
            conteos = contar_estados(estados)
            if conteos:
                self.historial.registrar_estados(self._reloj(), conteos)
            if ids:
                for e in estados:
                    cancelado = e.ruta_id in ids and e.estado == "cancelado" and e.salida[:2].isdigit()
                    if cancelado and int(e.salida[:2]) % 24 in horas:
                        salidas_canceladas[e.ruta_id].append(e.salida[:5])
            filas = [(f, r, h, *v) for (f, r, h), v in conteos.items()]
        else:
            filas = self.historial.estados([iso])
        if not filas:
            return {
                "fecha": iso,
                "sin_datos": True,
                "mensaje": (
                    "El feed de viajes no trae viajes de hoy."
                    if hoy
                    else "No hay viajes guardados de ese día. El feed solo trae el día en curso; para "
                    "días anteriores hay que haber tenido prendido `transmilenio-veedor` (o haber "
                    "consultado ese día)."
                ),
            }

        permitidas = set(ids) if ids else set(self._rutas(red, sistema)) if sistema else None
        por_ruta: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        por_ruta_hora: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
        for _f, rid, h, p, c, a in filas:
            if h not in horas or (permitidas is not None and rid not in permitidas):
                continue
            for acum in (por_ruta[rid], por_ruta_hora[rid][h]):
                acum[0] += p
                acum[1] += c
                acum[2] += a

        def cifras(p: int, c: int, a: int) -> dict:
            prog = p + c  # los cancelados eran parte del horario
            return {
                "programados": prog,
                "cancelados": c,
                "pct_cancelado": round(100 * c / prog, 1) if prog else None,
                "anadidos": a,
            }

        base = {
            "fecha": iso,
            "tipo_dia": self._tipo_dia(red, d),
            "fuente": "feed de viajes en vivo" if hoy else "historial local",
            "nota": "Es lo que el mismo TransMilenio marca en su feed de viajes (tripupdates): cancelado "
            "o añadido frente al horario. No verifica si el bus salió o no.",
        }
        if desde_hora is not None or hasta_hora is not None:
            base["franja"] = f"{_h(min(horas))}-{_h(max(horas) + 1)}"

        if ids:
            rutas = []
            for rid in ids:
                if rid not in por_ruta:
                    continue
                item = {**self._ficha(red, rid), "ruta_id": rid, **cifras(*por_ruta[rid])}
                salidas, _ = red.programado(rid, d)
                item["programados_gtfs"] = sum(salidas[h] for h in horas)
                item["por_hora"] = [
                    {"hora": _h(h), **cifras(*v)} for h, v in sorted(por_ruta_hora[rid].items()) if any(v)
                ]
                if salidas_canceladas.get(rid):
                    item["salidas_canceladas"] = sorted(salidas_canceladas[rid])[:60]
                rutas.append(item)
            if not rutas:
                return {**base, "ruta": red.rutas[ids[0]].codigo, "rutas": [], "mensaje": "Sin viajes de esa ruta."}
            return {**base, "ruta": red.rutas[ids[0]].codigo, "rutas": rutas}

        total = [sum(v[i] for v in por_ruta.values()) for i in range(3)]
        sistemas: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for rid, v in por_ruta.items():
            s = self._ficha(red, rid)["sistema"] or "Sin ruta en el GTFS"
            for i in range(3):
                sistemas[s][i] += v[i]
        ranking = [
            {**self._ficha(red, rid), "ruta_id": rid, **cifras(*v)}
            for rid, v in por_ruta.items()
            if v[0] + v[1] >= MIN_VIAJES_CANCELADOS
        ]
        mas = orden.strip().lower() != "menos"
        ranking.sort(key=lambda x: (x["pct_cancelado"], x["cancelados"]), reverse=mas)
        return {
            **base,
            "total": cifras(*total),
            "rutas_con_cancelados": sum(1 for v in por_ruta.values() if v[1]),
            "por_sistema": {s: cifras(*v) for s, v in sorted(sistemas.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))},
            "orden": "más canceladas primero" if mas else "menos canceladas primero",
            "rutas": ranking[: _acotar(limite, 1, 50)],
        }

    # ------------------------------------------------------------ el feed mismo

    def salud_feed(self, dias: int = 3) -> dict:
        """Cuándo estuvo caído el feed de TransMilenio (sin reportes nuevos por más de 5 minutos)."""
        ahora = self._reloj()
        out: dict = {}
        try:
            out["ahora"] = self.servicio._foto().publico
        except Exception as e:
            out["ahora"] = {"error": f"No se pudo leer el feed: {e}"}
        lect = self.historial.lecturas(ahora - _acotar(dias, 1, 60) * 86400)
        if not lect:
            out.update(
                sin_historial=True,
                mensaje="Sin historial de lecturas. `transmilenio-veedor` lo registra mientras está prendido.",
            )
            return out

        caidas, actual = [], None
        sin_registro_s = 0
        hueco = max(5 * config.VEEDOR_INTERVALO_S, 300)
        frescas = 0
        previo = None
        for leido, ultimo, _buses in lect:
            if previo is not None and leido - previo > hueco:
                sin_registro_s += leido - previo
            previo = leido
            caido = not ultimo or leido - ultimo > config.FEED_VIEJO_S
            if not caido:
                frescas += 1
                if actual:
                    actual["hasta"] = _iso(leido)
                    actual["duracion_min"] = round((leido - actual["_ini"]) / 60)
                    caidas.append(actual)
                    actual = None
            elif actual is None:
                ini = ultimo or leido
                actual = {"_ini": ini, "desde": _iso(ini)}
        if actual:
            actual["hasta"] = None
            actual["duracion_min"] = round((ahora - actual["_ini"]) / 60)
            actual["sigue"] = True
            caidas.append(actual)
        for c in caidas:
            c.pop("_ini")
        out.update(
            desde=_iso(lect[0][0]),
            lecturas=len(lect),
            disponibilidad_pct=round(100 * frescas / len(lect), 1),
            caidas=caidas[-30:],
            minutos_caido=sum(c["duracion_min"] for c in caidas),
        )
        if sin_registro_s:
            out["horas_sin_registro"] = round(sin_registro_s / 3600, 1)
            out["nota"] = "Hubo ratos con el recolector apagado; ahí no se sabe si el feed andaba."
        return out
