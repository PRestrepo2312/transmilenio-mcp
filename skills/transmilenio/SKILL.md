---
name: transmilenio
description: Responde preguntas sobre buses de TransMilenio y el SITP de Bogotá en tiempo real (cuándo llega un bus a una estación, por dónde va una ruta y en qué sentido, las próximas paradas de un bus, paraderos cercanos, desvíos y cierres) y de veeduría (viajes programados, rutas con más o menos buses de los programados, cumplimiento, caídas del feed) usando el servidor MCP transmilenio. Usar cuando pregunten por TransMilenio, SITP, alimentadores, TransMiCable, una estación o paradero de Bogotá, o un código de ruta como B10, C25, H75 o 16-8.
---

# TransMilenio en vivo

Los datos vienen de los feeds GTFS Realtime públicos de TransMilenio S.A., a través del
servidor MCP `transmilenio`.

## Qué herramienta usar

| Pregunta | Herramienta |
|---|---|
| ¿Cuándo pasa el B10 por Calle 72? | `llegadas` con `parada` y `ruta` |
| ¿Qué viene a Portal Norte? | `llegadas` |
| ¿Dónde van los C25? ¿Para dónde va? | `buses_ruta` |
| Estoy en tal punto, ¿cuándo pasa el C25 por mi paradero? | `buses_ruta` con `lat` y `lon` |
| ¿Por dónde va el bus Z70-4428? | `proximas_paradas` |
| ¿Qué paraderos tengo cerca? | `paraderos_cerca` |
| ¿Hay desvíos en la Caracas? | `alertas` |
| ¿Cuántos buses hay en la calle? | `estado_sistema` |
| No sabes el nombre exacto de la estación | `buscar_parada` primero |
| ¿Cuántos viajes tiene programados el C25 hoy? | `programacion_ruta` |
| ¿Qué ruta tiene más o menos buses frente a lo programado? | `ranking_rutas` con `criterio="buses"` |
| ¿Qué rutas cumplen menos su horario en la hora pico? | `ranking_rutas` con `criterio="cumplimiento"`, `orden="menos"`, `desde_hora=6`, `hasta_hora=9` |
| ¿Cómo le fue al H75 esta semana? | `historial_ruta` |
| ¿Qué rutas cancelaron más viajes hoy? ¿Qué salidas del C25 se cayeron? | `viajes_cancelados` (con `ruta` para el detalle) |
| ¿El feed está caído? ¿Cuánto tiempo? | `salud_feed` |

## Cómo leer los datos

- `ultima_parada` es la última que el bus ya pasó. La siguiente está en `siguiente_parada`.
- `llega_en_min` es una estimación (posición del bus en su tramo más el tiempo de cada tramo, corregido con el tráfico que midieron los buses en los últimos 20 minutos). Dilo como "unos 3 minutos".
- `ritmo` (en `buses_ruta`) dice si esa variante va más lenta o más rápida que su horario ahora mismo; úsalo si preguntan cómo está el tráfico de una ruta.
- `retraso_s` positivo: va tarde frente al horario. Negativo: adelantado.
- `sentido` viene como "Sur-Norte", "Nororiente-Suroccidente" o, en las circulares, "Hacia Unicentro" o "Regresa a Engativá".
- Un mismo código puede tener varias variantes (C25 troncal y C25 zonal). Si el usuario no dijo cuál, menciona las dos.
- En estaciones troncales, `llega_a` es el vagón (p. ej. "Calle 72 B - 2"): sirve para saber dónde esperar.
- Si llega `aviso`, el feed oficial está detenido o falló. Dilo antes de dar tiempos.
- Si llega `nota_sentido` (o `aviso_sentido` en un bus), hay buses que aún no se sabe hacia dónde van y no aparecen. Dilo y sugiere preguntar de nuevo en uno o dos minutos: para entonces salen casi todos.
- Si llega `preparando: true`, el índice se está armando (solo la primera vez). Espera unos segundos y vuelve a intentar.
- Si llega `error` con `parecidas`, ofrece esas rutas.

## Veeduría

- Lo programado sale del horario oficial y siempre está. Lo observado necesita el historial de
  `transmilenio-veedor`. Si llega `sin_historial`, dilo y explica cómo prenderlo; no lo inventes
  con la foto del momento salvo que la respuesta ya traiga `fuente: foto en vivo`.
- `porcentaje` es buses en vía sobre programados: 86 % es que faltaba 1 de cada 7.
- Menciona `horas_observadas` y `horas_sin_datos`: una hora sin datos no es una hora sin buses.
- Una foto o un día son una pista. Para afirmar que una ruta incumple, pide varios días.
- TransMiCable no entra en las comparaciones: sus cabinas no reportan en el feed.
- `viajes_cancelados` es lo que TransMilenio mismo marca en su feed de viajes; no verifica si el bus salió. Hoy siempre hay datos; otros días solo si se guardaron (`sin_datos`). `programados` incluye los cancelados, que eran del horario; `anadidos` son viajes fuera del horario.

## Cómo responder

- En español y corto. Primero lo que preguntaron: "El próximo B10 llega en unos 3 minutos".
- Máximo 5 o 6 buses en una lista; si hay más, resume ("y 8 más en los próximos 15 minutos").
- Nombra la ruta con su destino: "B10 hacia Portal Norte".
- En respuestas largas, termina con "Datos: TransMilenio S.A."
- No inventes rutas ni tiempos.
