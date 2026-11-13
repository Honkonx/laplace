# Memoria del modelo en la base, capa «actual» y recién llegados

## Memoria del modelo (`ml/laplace/estado_vivo.py`, tabla `ml_estado_vivo`)
El estado por equipo (Elo, tasas de gol con memoria, forma, tiros) de cada liga vive ahora también en la base. Cada día (06:40 y 13:40, Chile; `ESTADO_VIVO_AUTOMATICO`) se **reconstruye** repitiendo TODO el historial (maestro + capa en vivo + capa actual) con los
hiperparámetros del modelo activo y se guarda; el servicio lo usa por encima del estado del artefacto. Los pesos siguen siendo los del artefacto (solo el reentreno los cambia). Se reconstruye en vez de actualizar de forma incremental porque es la misma recurrencia
del entrenamiento: no diverge, recoge correcciones de resultados y trae la historia completa de los recién llegados.
- Verificado con datos reales: con los mismos datos que el artefacto, el estado reconstruido es **idéntico** (ΔElo = 0,0 y los mismos partidos en 7 ligas). Con la capa «actual» hay más partidos (E0: 4.280 frente a 4.251) y por eso el Elo difiere hasta ~20 puntos: más historia, no divergencia.
- 49 ligas y 156.526 partidos se reconstruyen en unos 6 s.
- Un equipo que el histórico no conoce entra con su nombre sin acentos; el servicio lo resuelve si la memoria ya lo conoce (≥ 5 partidos) y el otro equipo confirma la liga. Es accesorio: sin la tabla o con un error, se usa el estado del artefacto.

## Capa «actual» y fuentes
el actualizador de la capa «actual» (no publicado) trae la temporada en curso: football-data.co.uk (34 ligas) y, para las que esa fuente no cubre, **ESPN** (API pública de marcadores, solo para uso local; los datos no se publican). Hoy `BRA2` (Serie B de Brasil): una llamada con
`dates=<año>` trae la temporada completa (371 partidos, 20 equipos). Los nombres se resuelven contra el modelo (Athletic → Athletic MG, Operário PR → Operario-PR) y solo «Sao Bernardo» entró como equipo nuevo; un nombre ambiguo se descarta. Con `--ligas` solo se refrescan esas ligas y las demás se conservan.
`football-data.co.uk/new/BRA2.csv` devuelve el archivo de la Serie A (no existe la Serie B allí).

## Recién llegados en la capa en vivo
`backend/scripts/exportar_resultados_vivos.py`: antes descartaba todo partido con un equipo desconocido (`equipo_desconocido`) y un ascendido nunca juntaba historia. Ahora entra si la liga es una sola, el OTRO equipo la confirma y el nombre no se parece a ninguno conocido.

## Predicción conforme (experimento)
`ml/laplace/conformal.py` y `backend/scripts/evaluar_conformal.py`: conjuntos de resultados plausibles del 1X2. Fuera de muestra (11.194 partidos): cobertura 79,5 % para 80 % y 89,9 % para 90 %, no uniforme por liga. Aún no está en el producto. Detalle en `un documento archivado del autor (no publicado)`.

## Auditoría del modelo (`ml/laplace/auditoria.py`)
No cambia ningún pronóstico: lo hace auditable y compartido.
- **Cadena de sellos** (`ml_predicciones.hash_previo` y `hash_fila`): cada pronóstico guardado lleva el SHA-256 de su contenido encadenado con el de la fila anterior. `verificar_cadena` (y `GET /api/v1/ml/cadena`, solo administradores) detecta una fila alterada, una intermedia borrada o una sin sello dentro de la cadena; el trabajo diario la verifica y avisa si se rompe. Las filas anteriores a la cadena no cuentan. Límite: borrar la última fila no se detecta.
- **Memoria de errores** (`ml_errores`): por cada partido ya jugado y pronosticado antes (mismos equipos), el pronóstico, el resultado, el RPS, el log loss, el tramo de probabilidad del favorito y si acertó. La llena el trabajo diario de evaluación (`cerrar_bucle`, idempotente). `GET /api/v1/ml/errores` (administradores) informa por liga, tramo y mes con n por segmento; un segmento con menos de 30 casos sale como `suficiente: false` y no se interpreta.
- **Puerta del reentreno**: cada reentreno guarda en su evaluación histórica y en su salida la comparación con el modelo vigente (Δ log loss, RPS y ECE) con la regla común (mejora ≥ 0,001 y calibración que no empeore más de 0,005). No es pareada (sin IC95), y `comparable` es falso si el n de la prueba cambió: entonces es solo indicativa. La promoción sigue exigiendo las guardas del reentreno o un aprobador.
- **Memoria por equipo** (`GET /api/v1/ml/equipo/{liga}/{equipo}`, pública, `liga` = código del modelo, p. ej. `E0`): rating, goles a favor y en contra, forma, partidos, fiabilidad (`baja` con menos de 20 partidos), origen (`estado_vivo` o `artefacto`) y fecha de actualización.
- **Deriva** (`ml/laplace/deriva.py`, `GET /api/v1/ml/deriva`, administradores): PSI de las probabilidades de los últimos 30 días frente a los 120 anteriores del mismo modelo; con menos de 60 pronósticos en una ventana no dice nada. La anota y alerta el trabajo diario. Es una alarma, no cambia ningún pronóstico.
- **Memoria por equipo en el agente**: `agent_modelo_equipo.py` cita esta memoria al dar el perfil de un equipo (sin probabilidades).
- **Reproducibilidad**: el artefacto lleva `semilla` 0, `hash_datos` y `version_variables`; dos entrenamientos con los mismos datos dan el mismo artefacto byte a byte (`test_ml_v11.py`).
