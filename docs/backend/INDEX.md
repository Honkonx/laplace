# docs/backend/ — Bot deportivo (FastAPI)

| Archivo | Qué contiene |
|---|---|
| [`IA_PROVEEDORES.md`](IA_PROVEEDORES.md) | Cascada de proveedores de IA, Ollama local y cloud, enrutamiento por rol |
| [`LABORATORIO_PRONOSTICOS_OPERACION.md`](LABORATORIO_PRONOSTICOS_OPERACION.md) | Estado operativo del laboratorio de pronósticos |
| [`referencia/API.md`](referencia/API.md) | Todas las rutas de la API y quién puede llamarlas (generado del código) |
| [`referencia/BASE_DE_DATOS.md`](referencia/BASE_DE_DATOS.md) | Tablas, columnas, claves e índices (generado de los modelos) |
| [`referencia/SCRIPTS.md`](referencia/SCRIPTS.md) | Qué hace cada script y cada lanzador (generado de sus docstrings) |
| [`referencia/TRABAJOS_PROGRAMADOS.md`](referencia/TRABAJOS_PROGRAMADOS.md) | Cron, función y propósito de cada trabajo del planificador (generado de `main.py`) |

Las cuatro referencias se regeneran con `python backend/scripts/generar_referencia_docs.py`; una prueba (`test_referencia_docs.py`) falla si quedan desactualizadas.
