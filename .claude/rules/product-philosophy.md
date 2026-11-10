# Filosofía de producto — Laplace existe para ser honesto y verificable

> Creada 2026-09-04, destilada de `un documento archivado del autor (no publicado)` §2 ("Por qué existe"), que
> hasta ahora solo vivía como prosa en un doc de roadmap, no como regla persistente que guíe
> decisiones de diseño. Patrón (tener una regla de filosofía de producto por escrito) adaptado de
> otro proyecto del usuario — el contenido es 100% propio de Laplace, no copiado.

## La regla

**Laplace existe para ser distinto de la mayoría de bots de predicciones deportivas en Telegram,
que son opacos o charlatanes — sin respaldo estadístico real.** El objetivo es un sistema
honesto y técnico que mejora con el tiempo, con métricas verificables: RPS (ranked probability
score), winrate real por módulo, calibración de probabilidades — no promesas de "picks
seguros" sin evidencia.

**La monetización es secundaria a que el sistema funcione bien.** Primero construir algo que
funcione y se pueda verificar, después cobrar por acceso premium — no al revés.

## Cómo aplicar esto en la práctica

- Cualquier feature nueva que muestre una predicción/pick al usuario debería poder mostrar (o al
  menos registrar internamente para auditoría futura) de dónde sale el número — no un score
  opaco sin trazabilidad al consenso ponderado que lo generó.
- Al diseñar el futuro `laplace_auditor.py` (agente evaluador, Fase 13 del roadmap) o cualquier
  reporte de winrate: los números reales (aciertos/fallos verificados) tienen prioridad sobre
  cualquier narrativa de marketing — si el winrate real es malo, el sistema debe poder mostrarlo,
  no esconderlo.
- Al decidir entre una feature que mejora la percepción de "confianza" sin mejorar la precisión
  real vs. una que mejora la precisión real pero es menos vistosa — priorizar la segunda.
- Esta filosofía no bloquea monetizar (planes free/pro, límites de uso) — bloquea vender
  garantías que el sistema no puede respaldar con datos reales.

## Regla dura, no negociable: Laplace nunca es una casa de apuestas

> Agregada 2026-09-08, orden explícita del usuario: "esto es pronostico deportivo nunca se
> aceptara dinero para apostar o ser una casa de apuesta, solo poder hacer pronosticos y ver el
> resultado del analisis". Esto es una restricción de producto/legal, no solo de tono — tiene
> prioridad sobre cualquier feature que la contradiga, sin excepción.

**Laplace nunca acepta dinero para apostar, nunca opera como casa de apuestas, y nunca intermedia
apuestas de ningún tipo (propias, entre usuarios, o hacia terceros).** Lo único que el producto
vende/monetiza es acceso a **pronósticos y al resultado del análisis** (planes free/pro/max con
límites de uso, códigos de acceso) — nunca una apuesta, nunca un pago condicionado a un resultado
deportivo, nunca custodia de fondos de un usuario.

**Cómo aplicar esto en la práctica:**

- Ninguna feature nueva (web, app, bot) debe permitir "apostar" cantidades de dinero real ni
  virtual-con-valor-de-canje sobre un resultado — el consumo del producto es siempre "ver el
  pronóstico/análisis", nunca "poner algo en juego".
- Cualquier lenguaje de UI/copy que suene a casa de apuestas ("apuesta aquí", "gana dinero",
  cuotas presentadas como una oferta de apuesta en vez de un dato informativo del análisis) debe
  evitarse — las odds que Laplace ya consume (The Odds API) son **insumo del análisis estadístico
  interno** (value bet, consenso), no una oferta de apuesta al usuario.
- Si en algún momento surge una idea de producto que se acerque a esta línea (torneos con premio
  en efectivo, apuestas entre usuarios, "picks pagados" condicionados a acertar), es una señal de
  alarma — pausar y confirmar explícitamente con el usuario antes de avanzar, nunca asumir que
  encaja en el roadmap.

## Ver también

- `un documento archivado del autor (no publicado)` §2 — texto original completo.
- Fase 13-15 del roadmap (Agente Evaluador) — la implementación concreta de "hacerse honesto con
  datos", condicionada a acumular partidos verificados.
