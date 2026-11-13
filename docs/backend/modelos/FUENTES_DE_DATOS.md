# Fuentes de datos: las que usamos y las candidatas (2026-11-12)

Marcas: **✔** contrastado por el asistente principal contra la fuente, **[S]** resumen o fragmento de un buscador, **[I]** inferido, **[?]** sin evidencia. Detalle de la investigación: `un documento archivado del autor (no publicado)*`.

## 1. Las que usamos hoy
| Fuente | Qué trae | Límite o licencia | Dónde entra |
|---|---|---|---|
| football-data.co.uk (histórico) | Resultados, tiros, tarjetas, córners y cuotas de varias casas desde 2012 en nuestro maestro (154.421 partidos, 49 ligas; 137.297 con cuotas y 67.997 con tiros) | **«Solo para particulares, NO productos comerciales ni de entrenamiento con bots, scrapers o IA»; «para predicción de partidos de liga solamente»** ✔ | Maestro `backend/data/datos/football-data/` (no se publica) |
| football-data.co.uk (temporada en curso) | Igual, de 34 ligas | Misma licencia ✔ | Capa «actual», diaria 06:15 |
| ESPN (API pública de marcadores) | La Serie B de Brasil completa en una llamada (`dates=<año>`: 371 partidos) | Sin términos ni garantía de continuidad [S]; uso local | Capa «actual» (`BRA2`) |
| LiveScore6 (RapidAPI) | Partidos del día, resultados y **país de cada competición** (36 de 36 etapas con `Cnm`; también `Ccd`, `CompId`, `Sid`) ✔ | Cuota del plan | Cascada de partidos y colector de resultados |
| API-Football (plan gratis) | Partidos, estadísticas, alineaciones según el endpoint | Unas 100 peticiones por día [S]; la temporada actual está bloqueada según los errores propios de la API ✔ | Cascada de partidos, H2H, cuotas puntuales |
| BSD API | Predicciones de terceros y xG | Cuota del plan | Módulo `bsd_ml` (peso 0) y xG |
| The Odds API y OddsPapi | Cuotas previas al partido | Cuota del plan | Módulo `odds`, apilado, refresco 2 veces al día |
| football-data.org (clave gratis) | Tablas y resultados con retraso | **12 competiciones y 10 llamadas por minuto** ✔ | Módulo `tabla` |
| Resultados que verifica el bot | Resultados propios | — | Capa en vivo |

## 2. Candidatas
| Fuente | Qué trae | Licencia o límite | Utilidad |
|---|---|---|---|
| **openfootball** | Calendario y resultados de ligas europeas, 2010-11 a 2026-27, actualización diaria | CC0 [S]; sin cuotas | **Alta**: segunda fuente de resultados con licencia limpia para cruzar la capa «actual» |
| StatsBomb Open Data | Datos de eventos, alineaciones, 360 | Atribución con logo [S]; competiciones parciales | Estudiar xG, xT y VAEP; no para producción |
| Understat | xG por tiro (vía terceros) | Términos no hallados [?] | Baja-media |
| FBref / Opta | Estadísticas básicas; las avanzadas se retiraron [S] | Términos no hallados [?] | Baja |
| Transfermarkt | Valores de mercado y fichajes | Copyright y bloqueo de bots [S] | Evitar |
| clubelo.com | Elo de clubes | No se pudo consultar [?] | Media; alternativa: Elo propio, que ya calculamos |

## 3. Licencias de las fuentes
Cada fuente tiene sus propios términos y quien use el proyecto debe respetarlos. El caso más restrictivo de las que usamos es football-data.co.uk ✔: su página dice que los datos son «solo para particulares, NO productos comerciales ni de entrenamiento con bots, scrapers o IA»
y «para predicción de partidos de liga solamente». Por eso este repositorio **no incluye datos** ni los scripts que los descargan (`publico-solo-codigo-y-sin-datos-personales.md`): cada persona genera los suyos con sus fuentes y bajo sus términos, y los modelos entrenados con ellos tampoco se publican.
Si el uso del proyecto cambiara (por ejemplo, un servicio con cobro), habría que volver a revisar los términos de cada fuente. Alternativas con licencia clara para resultados: openfootball (CC0, sin cuotas).

## 4. Prácticas de validación que importan para los datos
Cuotas de **apertura** como entrada y de cierre solo como referencia de evaluación (nuestro apilado usa `ap_prom`: sin la fuga más habitual ✔); características solo con información previa al partido; mismos partidos para todos los modelos; reportar la cobertura de cuotas y no extrapolar a ligas sin ellas; periodo de prueba que el ajuste no ve.
