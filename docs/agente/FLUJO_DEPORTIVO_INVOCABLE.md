# Flujo deportivo invocable por el agente

El agente reconoce consultas como `predice equipo local vs equipo visitante` y `cuotas de equipo local vs equipo visitante`. Primero consulta los partidos, normaliza la estructura `Stages/Events` del gateway y selecciona el partido; después invoca `sports.predict` o `sports.get_odds`. Si no encuentra el partido, responde sin inventar datos.

`sports.predict` llama a `POST /api/v1/prediccion-web`, que usa el mismo servicio (`analizar_y_persistir`) que el resto del backend. El resultado queda en `analisis_comparativo` y `analisis_modulos`, de modo que el track record, la verificación de resultados y la calibración pueden evaluarlo. `sports.results` sigue siendo una acción de administrador con confirmación.
