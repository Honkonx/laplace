---
name: sports-domain
description: "Dominio estadístico y de pronósticos deportivos. Activar cuando la tarea involucre: diseñar o modificar el prompt de predicción de Claude, ajustar pesos del consenso, cambiar mercados (1X2/Over-Under/BTTS), calibrar confianza, interpretar xG o divergencia de odds, crear templates para nuevos deportes, entender la lógica de Poisson/Dixon-Coles, o evaluar si un pick tiene value real."
allowed-tools: [Read, Write]
---

# Sports Domain — Estadística y Pronósticos

## 1. MOTOR ESTADÍSTICO ACTUAL

### Arquitectura del consenso

```
datos.py (orquestador, ThreadPoolExecutor)
  ├── pronostico.py  [35%] — Poisson bivariante + Dixon-Coles + xG
  ├── h2h.py         [20%] — Head-to-head ponderado por antigüedad
  ├── odds.py        [20%] — Probabilidades implícitas de mercado
  ├── form_recent.py [15%] — Forma últimos 5 partidos
  └── tabla_pos.py   [10%] — Posición + momentum
      + bsd_ml       [+5%] — Bonus CatBoost ML (si BSD encuentra el partido)
```

### Pesos dinámicos Python vs Claude (WF-B)

| Fuentes disponibles | Python | Claude |
|---------------------|--------|--------|
| 3 módulos ok        | 65%    | 35%    |
| 2 módulos ok        | 55%    | 45%    |
| 1 módulo ok         | 45%    | 55%    |
| 0 módulos ok        | 35%    | 65%    |

### Score WF-D (Top 3 picks canal)
```
score_canal = Poisson×0.4 + Forma×0.2 + IA×0.4
Umbral mínimo: score >= 60 para entrar al Top 3
```

---

## 2. POISSON + DIXON-COLES

### Fórmula de lambda

```python
HOME_ADVANTAGE = 0.35   # goles extra al local (valor calibrado académico)
PESO_XG = 0.30          # peso del xG en lambda final (cuando BSD lo provee)
DC_RHO = -0.13          # corrección Dixon-Coles (estándar fútbol)

# Sin xG:
lambda_local = goles_local_avg * (1 + HOME_ADV / goles_local_avg)

# Con xG BSD disponible:
lambda_local = lambda_base * 0.70 + xg_local * 0.30
```

### Corrección Dixon-Coles

Corrige la subestimación de Poisson en marcadores de baja puntuación:

```
tau(0,0) = 1 - λL × λV × ρ  → baja probabilidad empate a 0
tau(1,0) = 1 + λV × ρ        → sube probabilidad victoria local 1-0
tau(0,1) = 1 + λL × ρ        → sube probabilidad victoria visitante 0-1
tau(1,1) = 1 - ρ             → baja probabilidad empate 1-1
tau(x,y) = 1                 → resto sin cambio
```

Impacto real: ±2-4% en esos 4 marcadores. Renormalizar después.

### Penalty factor por lesionados (BSD)

```python
_PENALTY = {1: 0.95, 2: 0.90}   # 1 baja → lambda ×0.95; 2 bajas → ×0.90
_PENALTY_3MAS = 0.85              # 3+ bajas → lambda ×0.85
# Solo actúa sobre goles_*_avg ANTES de pasarlo a pronostico.py
# Solo si BSD encontró el partido (bsd_data.found == True)
```

---

## 3. MERCADOS — FÚTBOL

### 1X2 (Resultado final)

```
Local    → equipo de casa gana
Empate   → 90 min terminan igualados
Visitante → equipo visitante gana
Incluye tiempo extra y penales SOLO si se especifica (AET/PENS)
```

### Over/Under 2.5 goles

```
Over 2.5  → 3 o más goles en el partido
Under 2.5 → 0, 1 o 2 goles en el partido
Umbral del modelo: prob_over25 >= 0.55 para recomendar Over
```

### BTTS (Both Teams to Score)

```
BTTS Sí → ambos equipos anotan al menos 1 gol
BTTS No → alguno (o ambos) termina a 0
Cálculo: (1 - P(0 goles local)) × (1 - P(0 goles visitante))
Umbral del modelo: prob_btts >= 0.55 para recomendar Sí
```

### Correct Score

```
Marcador más probable de la distribución Poisson
Limitado a marcadores 0-4 por equipo en predicción
Solo incluir si prob_marcador > 0.12 (12%)
```

### Value Bet (OddsPapi / Pinnacle)

```
value_signal = True  cuando:
  divergencia = (prob_poisson_pick - prob_impl_pinnacle) × 100 >= 5pp
  Y el pick Poisson coincide con el pick de mayor divergencia

Bankroll sugerido:
  ALTA + value_signal = True  → 3-5% bankroll
  ALTA                        → 2-3%
  MEDIA                       → 1-2%
  BAJA                        → 0.5-1%
  Sin confianza clara         → no recomendar
```

---

## 4. NIVELES DE CONFIANZA

```
🟢 ALTA   → ≥3 módulos coinciden + score_consenso >= 70
🟡 MEDIA  → 2 módulos coinciden O score_consenso 55-69
🔴 BAJA   → 1 módulo O score_consenso < 55 O módulos divergen

Nivel consenso Python:
  FUERTE   → peso_coincidente >= 70% del total
  MODERADO → peso_coincidente 55-69%
  DÉBIL    → peso_coincidente < 55%
```

---

## 5. FUENTES EXTERNAS

### BSD API (bzzoiro.com)
- **Datos:** xG pre-partido, lesionados/suspendidos, odds consenso, predicción CatBoost ML
- **Límite:** Sin límite conocido
- **Uso:** Enriquece lambdas Poisson + módulo bsd_ml en consenso
- **Matching:** Fuzzy (primera pasada local, segunda pasada visitante)
- **No encontrado:** devuelve `found:false` → motor sigue sin xG, sin penalty

### OddsPapi (Pinnacle)
- **Datos:** Odds sharps (Pinnacle → Singbet → SBOBet → Betfair), divergencia de valor
- **Límite:** 250 req/mes — activar SOLO cuando score Poisson >= 65
- **Uso:** Detectar value real vs mercado sharp

### Forebet (scraping HTML)
- **Datos:** Pick 1X2, % probabilidades, marcador predicho
- **Límite:** Sin límite (HTML estático, sin Cloudflare)
- **Rol:** Referencia INFORMATIVA — NO entra al consenso
- **Razón:** Scraping es frágil; si falla silenciosamente no puede afectar el pick

### apis externas — límites actuales

| API | Límite | Uso |
|-----|--------|-----|
| api-football v3 | 100 req/día (free) | Fixtures fallback, standings, resultados |
| Livescore6 (RapidAPI) | Cuota mensual | Fixtures primario (puede agotarse) |
| The Odds API | 500 req/mes | Cuotas 1X2 |
| BSD API | Sin límite | xG, lesionados, ML |
| OddsPapi | 250 req/mes | Solo score Poisson >= 65 |

---

## 6. PROMPT TEMPLATES

### Regla general

```
Sin Markdown (prohibido * # _ `). Solo emojis + texto plano.
No prometer % de acierto garantizado.
Value bet ≠ apuesta segura — es ventaja estadística a largo plazo.
```

### Fútbol — estructura del análisis

```
DATOS mínimos requeridos:
  partido, liga, fecha
  H2H (mínimo 3 partidos para ser "útil")
  Standings (posición + puntos + forma últimas 5)
  Odds 1X2 actuales (con % implícito calculado)
  xG si BSD disponible

MERCADOS a cubrir siempre:
  1. 1X2 con confianza (ALTA/MEDIA/BAJA)
  2. Over/Under 2.5
  3. BTTS
  4. Marcador más probable (solo si prob > 12%)
  5. Value bet (solo si OddsPapi activado y value_signal=True)

BANKROLL:
  Recomendar % según confianza (ver tabla §4)
  Si BAJA: indicar pero no recomendar apostar
```

### Basketball

```
DATOS: partido, liga, local, visitante, H2H, standings, odds
MERCADOS:
  - Moneyline (ganador — sin empate)
  - Spread (handicap de puntos, línea más común ±5.5)
  - Over/Under total puntos (línea habitual NBA: 220-230)
CONFIANZA: mismos criterios base
DIFERENCIA FÚTBOL: no hay empate, el overround es menor (~4-5%)
```

### Béisbol

```
DATOS: partido, liga, local, visitante, H2H, standings, odds, pitcher titular
MERCADOS:
  - Moneyline (ganador)
  - Run Line (spread de ±1.5 carreras — el más común)
  - Over/Under total de carreras
  - NRFI (No Run First Inning) si hay datos de pitcher
CONFIANZA: agregar criterio de pitcher titular conocido vs desconocido
```

### Tenis

```
DATOS: partido, torneo, superficie, jugador 1, jugador 2, H2H, ranking ATP/WTA
MERCADOS:
  - Ganador del partido
  - Total de sets (Over/Under 2.5 en best of 3; Over/Under 4.5 en best of 5)
  - Total de games
CONFIANZA: agregar criterio de superficie (ventaja H2H por superficie)
DIFERENCIA FÚTBOL: no hay empate, estadísticas individuales más relevantes
```

---

## 7. SPORT KEYS — The Odds API

| Liga | Sport Key |
|------|-----------|
| Premier League | `soccer_epl` |
| LaLiga | `soccer_spain_la_liga` |
| Serie A | `soccer_italy_serie_a` |
| Bundesliga | `soccer_germany_bundesliga` |
| Ligue 1 | `soccer_france_ligue_one` |
| Champions League | `soccer_uefa_champs_league` |
| Europa League | `soccer_uefa_europa_league` |
| Eredivisie | `soccer_netherlands_eredivisie` |
| Championship | `soccer_efl_champ` |
| MLS | `soccer_usa_mls` |
| Liga MX | `soccer_mexico_ligamx` |
| Copa Libertadores | `soccer_conmebol_copa_libertadores` |
| Liga Profesional ARG | `soccer_argentina_primera_division` |
| Brasileirão | `soccer_brazil_campeonato` |

---

## 8. VERIFICACIÓN DE RESULTADOS

### Lógica de acierto por mercado

| Mercado | Acierto |
|---------|---------|
| 1X2 | pick == resultado (Local/Empate/Visitante) |
| Over 2.5 | goles_local + goles_visit >= 3 |
| Under 2.5 | goles_local + goles_visit <= 2 |
| BTTS Sí | goles_local >= 1 AND goles_visit >= 1 |
| BTTS No | goles_local == 0 OR goles_visit == 0 |

### Fuentes de verificación (cascada)

```
1. BSD API (primaria) — busca por equipo + fecha + status=finished
2. api-football v3 (fallback) — por fixture_id
Umbral: STATUS_TERMINADOS = {'FT', 'AET', 'PEN'}
```

---

## 9. MÉTRICAS DE CALIDAD DEL MODELO

```
RPS (Ranked Probability Score) — métrica principal
  Mide calibración de probabilidades, no solo acierto binario
  Poisson puro fútbol: ~0.210
  Poisson + xG BSD:    ~0.199 (mejora significativa)
  Objetivo largo plazo: < 0.190

Winrate pick 1X2:
  Poisson puro: ~55%
  Con xG + ML:  ~58-60% (estimado)
  LightGBM features suficientes: ~67% (objetivo fase 3)

Activar Agente Evaluador: >= 50 partidos verificados en BD
Calibrar pesos por módulo: >= 30 partidos por módulo verificados
```
