---
name: python-backend
description: "Reglas de Python para el backend de Laplace (FastAPI, SQLAlchemy, SQLite/PostgreSQL). Activar al escribir o modificar código en backend/api/ o backend/scripts/: servicios, repositorios, modelos, migraciones, llamadas a fuentes externas, tests."
allowed-tools: [Read, Write, Bash]
---

# Python — backend de Laplace

## Entorno
Python 3.13 con el entorno de `runtime/venv` (instalador portable) o `.venv_backend` (trabajo). Dependencias en `backend/requirements*.txt`; las de ML (`numpy`, `scipy`, `scikit-learn`) son opcionales (`requirements-ml.txt`). Comando de pruebas: `python -m pytest backend/tests backend/agents/tests -q`.

## Reglas
1. **Configuración:** todo valor de entorno entra por `Settings` (`backend/api/core/config.py`); nada de `os.environ` suelto ni de rutas fijas de una máquina. Una clave externa nueva se declara también en `core/conexiones.py`.
2. **HTTP:** `httpx` (async en los servicios), con timeout explícito y reintentos acotados (`services/_http_retry.py`). Un cuerpo `200` con `errors` dentro (API-Football) es un fallo, no una lista vacía.
3. **Base de datos:** SQLAlchemy con repositorios en `db/`. Las fechas se escriben desde Python (nada de `DEFAULT (datetime('now'))`); SQLite con `timeout`; las escrituras concurrentes sobre el mismo registro se piensan para PostgreSQL (bloqueo por fila). Una migración Alembic se **aplica y se prueba contra el endpoint real**, no solo contra los tests.
4. **Errores:** excepciones tipadas (`LaplaceError` y derivadas) que el router traduce a `HTTPException`; nunca un `except` vacío. Un `SystemExit` no puede escapar de un trabajo programado o de código que importa el backend.
5. **Logs y secretos:** logging estructurado (`core/logging_config.py`); ningún secreto ni dato personal en un log, una respuesta ni un mensaje de error.
6. **Salida de scripts:** `backend/scripts/*.py` con `argparse`, ayuda clara y, si borran o modifican filas en masa, confirmación y mensaje de cuántas afectan y si son idempotentes.
7. **Tamaño:** funciones cortas y de una sola responsabilidad; un archivo de más de ~400 líneas es señal de dividirlo (excepción: coordinación de E/S externa con reintentos).

## Tests
Un cambio de comportamiento lleva su test en el mismo cambio. Los tests no leen el `.env` real ni llaman a la red (`conftest.py` los aísla). Las referencias de `docs/backend/referencia/` se regeneran con `python backend/scripts/generar_referencia_docs.py`.
