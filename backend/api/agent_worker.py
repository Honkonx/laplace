"""Worker separado para tareas persistentes del agente.

El API puede desactivar `AGENT_LOCAL_EXECUTOR`; este proceso reclama las tareas queued y usa el
registry cerrado del mismo orquestador. La reclamación en `_ejecutar` filtra por estado queued,
por lo que API y worker no procesan dos veces la misma tarea.
"""
from __future__ import annotations

import time

from backend.api.services.task_orchestrator import reencolar_tareas_pendientes


def main() -> None:
    while True:
        reencolar_tareas_pendientes()
        time.sleep(2)


if __name__ == "__main__":
    main()
