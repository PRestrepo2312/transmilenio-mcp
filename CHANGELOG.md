# Cambios

## 0.1.3 (10 de noviembre de 2026)

- Nueva herramienta `viajes_cancelados`: los viajes del día que TransMilenio marca como
  cancelados o añadidos en su feed de viajes, por ruta, sistema y hora de salida. El día en
  curso no necesita historial; el recolector guarda el resumen cada 10 minutos para comparar
  días. El primer día medido (martes 10-nov, 1 p. m.): 7,2 % cancelado, 11,1 % en el zonal y
  0,5 % en la troncal.
- Las llegadas tienen en cuenta el tráfico del momento, medido con los mismos buses: lo que
  tardaron en cada tramo en los últimos 20 minutos frente al horario. En un backtest de 35
  minutos el error medio bajó de 2,1 a 1,7 minutos.
- `buses_ruta` trae el `ritmo` de cada variante frente a su horario y `estado_sistema` cuántos
  tramos tienen tráfico medido.
- Mientras hay consultas, el hilo de fondo ubica toda la flota en cada lectura (para medir).

## 0.1.2 (10 de noviembre de 2026)

El feed volvió el 10 de noviembre tras cinco días detenido, pero ya no trae una parada que
corresponda a la posición del bus. Con 0.1.1 eso daba llegadas falsas (un bus en la Calle 80
salía "llegando" a la Calle 72).

- El bus se ubica por geometría: el tramo de su ruta más cercano. La parada del feed solo se
  usa si cuadra con la posición.
- La ida y la vuelta se separan por hacia dónde se ha movido el bus entre lecturas. Mientras no
  se sabe, el bus no entra en las llegadas y la respuesta dice cuántos faltan (`sin_sentido`,
  `nota_sentido`).
- Tras cada consulta se sigue leyendo el feed 15 minutos en segundo plano, para que la
  siguiente pregunta tenga el sentido de casi toda la flota.
- `ultima_parada` sale de la ubicación calculada, no del feed.
- El veedor ignora `start_time` cuando es la hora del reporte y cuenta el viaje en la hora en
  que se vio por primera vez.

## 0.1.1 (9 de noviembre de 2026)

- Publicado en PyPI: `uvx transmilenio-mcp`. Se sube desde GitHub Actions con Trusted Publishing.
- El paquete fuente ya no lleva las imágenes del README.

## 0.1.0 (9 de noviembre de 2026)

- Servidor MCP con 8 herramientas: llegadas, buses_ruta, proximas_paradas, paraderos_cerca,
  buses_cerca, alertas, buscar_parada, estado_sistema.
- Mapa local (`transmilenio-web`) con modo noche, íconos por sistema, recorrido de cada bus y
  "cuándo pasa por mi paradero".
- Índice del GTFS estático de 0,4 MB, armado en local o descargado ya listo.
- Pruebas sin internet con un recorte real de los feeds.
- Veedor: el índice guarda la programación oficial (viajes por hora y buses en vía, por ruta y
  tipo de día, con festivos). Herramientas `programacion_ruta`, `ranking_rutas`,
  `historial_ruta` y `salud_feed`.
- `transmilenio-veedor` guarda la flota cada minuto en SQLite (también `--veedor` en el mapa y
  en el MCP). Registra las caídas del feed sin contarlas como buses.
- Capturas del mapa y una demo animada (WebP, 270 KB) en el README; `docs/capturas.py` las regenera con GPU y sin fundidos.
- CI con acciones al día, Ubuntu 24.04 fijo y Python 3.10, 3.12 y 3.14.
- Los buses cuya ruta ya no está en el GTFS del día salen con ícono gris ("sin ruta").
- Arreglo: el refresco del índice a veces se perdía si una consulta llegaba justo al terminar
  la carga anterior.
