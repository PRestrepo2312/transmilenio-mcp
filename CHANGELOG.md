# Cambios

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
