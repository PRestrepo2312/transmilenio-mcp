# Contribuir

Se aceptan issues y PRs. Si es un cambio grande, abre primero un issue para hablarlo.

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
pytest -q
ruff check src tests && ruff format src tests
```

- Las pruebas no deben usar internet. Si necesitas datos nuevos, regenera los fixtures con
  `tests/crear_fixtures.py` y explica en el PR de qué fecha son.
- Los mensajes que ve el usuario van en español.
- Si cambias cómo se estiman las llegadas, cuenta en el PR cómo lo comprobaste con datos reales.
- No subas el GTFS completo ni el índice de la caché al repo.
