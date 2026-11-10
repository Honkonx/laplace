# Ningún cambio del motor de pronóstico entra sin evaluación walk-forward contra el mercado

> Creada 2026-09-29 tras la auditoría del bot: el Poisson en producción (promedios de la
> temporada en curso + ventaja de local fija) nunca se había medido contra nada, y la base real
> tenía 78 de 95 picks en "Empate" por un bug de datos genéricos. Recién al evaluar con 55.557
> partidos históricos reales (`backend/scripts/evaluar_modelo_historico.py`) se pudo ordenar
> con números qué modelo era mejor.

## Regla

Antes de cambiar pesos del consenso, agregar un módulo o tocar `pronostico.py`/`consenso.py`,
medir el cambio con el mismo arnés walk-forward y comparar contra tres referencias sobre los
MISMOS partidos: **tasa base de la liga**, **cuotas del mercado sin margen** y **el motor
vigente**. Métricas: RPS y log-loss (no solo accuracy).

1. **Sin fuga del futuro**: cada partido se predice solo con lo anterior a su fecha. Los
   hiperparámetros se eligen en el periodo de desarrollo; el número que se reporta es el del
   periodo de prueba que el tuning no vio.
2. **Se compara contra el mercado.** Un modelo que no mejora a las cuotas sin margen no aporta
   información nueva; puede entrar solo donde no hay cuotas, y debe decirlo.
3. **Modo sombra en vivo, y promoción solo con evidencia**: todo modelo nuevo corre además en
   `laboratorio_pronosticos` para medirse en partidos EN VIVO (50 exploratoria, 200 para
   promover). Puede entrar al consenso antes de eso únicamente si REEMPLAZA a un módulo que la
   evaluación histórica fuera de muestra demostró peor (caso 2026-09-29: `historico` reemplaza
   peso del Poisson) — nunca como módulo adicional sin medir.
4. **Datos contaminados no se mezclan**: lo generado por una versión anterior del motor se
   conserva pero se excluye de las métricas (`CORTE_MOTOR_CON_PUERTA_CALIDAD` en
   `models/predicciones.py`, hoy 2026-10-07). Al corregir un bug que cambia las salidas del motor, mover ese corte.
5. **Un LLM no produce probabilidades.** La IA explica y contrasta; las probabilidades salen de
   modelos medidos.

## Cómo aplicarla

Correr `python backend/scripts/evaluar_modelo_historico.py` (necesita numpy, scipy y
scikit-learn; ver `backend/requirements-ml.txt`) y citar en el `humanoN.md` de la ronda las cifras
reales del informe (`datos-historicos/resultados/evaluacion_modelo_historico.json`).

## Lecciones de la ronda 2026-10-07 (evidencia medida)

- **Un módulo "ya portado" puede estar roto.** El sesgo a Empate era un error de unidades en
  `pronostico.calcular_lambdas` (goles por equipo ÷ media de goles TOTALES, λ a la mitad) presente desde el
  origen; la evaluación del 2026-09-29 midió esa fórmula rota y concluyó "el Poisson es peor que la tasa
  base". Antes de decidir qué módulo sobra, verifica que mide lo que dice medir (reproduce un caso real a
  mano y comprueba que el λ de un equipo promedio sea el promedio).
- **Mide el consenso completo, no solo sus partes**: el consenso con pesos "razonables" a mano era peor que
  las cuotas solas. Un peso 0 equivale a módulo ausente (`consenso.calcular_pesos_efectivos`).
- **Las etiquetas de confianza deben calibrarse con frecuencias reales** (ALTA ≥ 0,60 de probabilidad
  ponderada, MEDIA 0,50–0,60, BAJA < 0,50): antes MEDIA acertaba 41%, menos que "siempre Local" (43%).
- `pytest --basetemp=<carpeta>` borra esa carpeta en cada corrida: no guardes resultados en ella. Los
  temporales de QA van en `.qa/` (gitignorada), nunca en la raíz.
