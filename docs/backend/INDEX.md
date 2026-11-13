# docs/backend/ — Bot deportivo (FastAPI)

| Archivo | Qué contiene |
|---|---|
| [`IA_PROVEEDORES.md`](IA_PROVEEDORES.md) | Cascada de proveedores de IA, Ollama local y cloud, enrutamiento por rol |
| [`LABORATORIO_PRONOSTICOS_OPERACION.md`](LABORATORIO_PRONOSTICOS_OPERACION.md) | Estado operativo del laboratorio de pronósticos |
| [`MODELO_LAPLACE.md`](MODELO_LAPLACE.md) | El modelo estadístico propio: pronóstico, simulaciones, entrenamiento, registro, servicio con degradación y contrato `/api/v1/ml/*` |
| [`referencia/API.md`](referencia/API.md) | Todas las rutas de la API y quién puede llamarlas (generado del código) |
| [`referencia/BASE_DE_DATOS.md`](referencia/BASE_DE_DATOS.md) | Tablas, columnas, claves e índices (generado de los modelos) |
| [`referencia/SCRIPTS.md`](referencia/SCRIPTS.md) | Qué hace cada script y cada lanzador (generado de sus docstrings) |
| [`referencia/TRABAJOS_PROGRAMADOS.md`](referencia/TRABAJOS_PROGRAMADOS.md) | Cron, función y propósito de cada trabajo del planificador (generado de `main.py`) |

Las cuatro referencias se regeneran con `python backend/scripts/generar_referencia_docs.py`; una prueba (`test_referencia_docs.py`) falla si quedan desactualizadas.

## Memoria mínima del bot y privacidad (2026-11-11)
- Tablas `bot_preferencias` (equipos favoritos hasta 5, idioma, personalizar), `bot_historial_consultas` (partido y fecha; 90 días y 200 filas por usuario) y `bot_consentimientos` (versión `bot-1`); migración `fa7b8c9d0e1f`. Código: `db/bot_memoria_repo.py`, `models/bot_memoria.py`.
- Sin consentimiento no se guarda nada. `/privacidad [aceptar|revocar]`, `/equipos [agregar|quitar]`, `/olvidame confirmo` (borra las tablas `bot_*`, las ligas favoritas y los votos de encuesta; una prueba falla si aparece una tabla `bot_*` sin cubrir).
- La personalización solo REORDENA ligas y partidos (favoritos primero); ninguna cifra ni pick depende de ella.
- `scripts/medir_discrepancia_ia.py` + `services/discrepancia_ia.py` (2026-11-11): tabla 2×2 de si «la IA diverge» predice que el consenso falla; solo lectura; el ajuste de −8 no cambia hasta tener 200 partidos por grupo.
- Consenso `consenso.v1` (2026-11-11): cada resultado lleva `contrato` y `procedencia` (módulos que respondieron, pesos, método, versión del modelo propio, pesos configurados, instante); `/health` expone el contrato y los pesos.
- Medición de la IA (2026-11-11): `scripts/medir_aporte_ia.py` (aporte de la IA frente al baseline estadístico, solo lectura) y `services/ai_critico.py` (crítico informativo, apagado por `AI_CRITICO`).
- Núcleo Monte Carlo en Go (2026-11-11): `modelo/go/lsim`, puente `ml/laplace/motor_go.py`, compilación `scripts/construir_go.py`; `LAPLACE_MOTOR_SIM=python` lo desactiva.
- Avisos de favoritos: `/avisos on|off` (o «activa los avisos» al agente), `services/avisos_favoritos.py`; trabajos de las 08:30 (aviso previo con pronóstico del modelo si lo hay) y de resultados (11:10, 15:10, 19:10, 21:10), un aviso por partido (`bot_avisos_enviados`), horario 08:00–22:00 de Chile; apagados por defecto (`AVISOS_FAVORITOS`).
- Simulador de liga (2026-11-12): [`SIMULADOR_PUBLICO.md`](SIMULADOR_PUBLICO.md): público (planes pro/max y administradores) frente a interno, datos viejos + actuales, acceso, ligas. el actualizador de la capa «actual» (no publicado) trae la temporada en curso cada día.
- Motores nativos (2026-11-12): [`MOTORES_NATIVOS.md`](MOTORES_NATIVOS.md): Rust (cálculo), Go (servicio local `simd` y respaldo) y Python (lógica), cadena, mediciones y compilación.
- Modelos, algoritmos y datos (2026-11-12): [`modelos/INDEX.md`](modelos/INDEX.md): lo que tenemos, lo que nos falta, diferencias entre enfoques, fuentes de datos, bots y productos, y algoritmos de otros deportes.
- Memoria del modelo (2026-11-12): [`MEMORIA_Y_FUENTES_DEL_MODELO.md`](MEMORIA_Y_FUENTES_DEL_MODELO.md): estado por equipo en la base, capa «actual» con ESPN, recién llegados y predicción conforme.
- Ligas y partidos (2026-11-12): [`LIGAS_Y_PARTIDOS.md`](LIGAS_Y_PARTIDOS.md): identidad nombre + país, `liga_pais`, menú, catálogo y reclasificador de filas viejas.
