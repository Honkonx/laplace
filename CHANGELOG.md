# Changelog

## Sin publicar (desde la 1.0.0)
- Modelo propio de Laplace (ratings Elo y tasas de gol con regresión logística jerárquica, combinado con las cuotas sin margen) y su memoria por equipo en la base, reconstruida a diario; los equipos recién ascendidos entran con su historia.
- Simulador de temporadas (campeón, copa y descenso) con núcleo en Rust, respaldo en Go y en Python, y un servicio local en Go con tope de simulaciones y plazo que mata el cálculo; en la web, la PWA, Telegram y el agente es solo para planes con acceso al simulador y administradores.
- Ligas identificadas por nombre y país: dos competiciones homónimas de países distintos ya no se mezclan en el menú, la web ni la base.
- `modelo_laplace.py predecir`: pronóstico por lotes sin Telegram ni servidor; la entrada HTTP acepta `pais` y `liga_id`.
- H2H y tabla con respaldo en el historial propio cuando las fuentes externas no los dan; el mensaje indica qué fuentes votaron y cuáles quedaron sin dato.
- Predicción conforme del 1X2 como experimento (aún fuera del producto).
- Seguir equipos y ligas desde el chat de Telegram, la web y la PWA («Mis seguimientos»): un solo almacén, el mismo consentimiento y topes por plan. Avisos del partido y de su resultado con el pronóstico del modelo, un aviso por partido, en el horario y la zona horaria de cada persona.
- Memoria tipada del usuario (zona horaria, estilo y mercados), con borrado total, y ajuste del estilo con frases como «más corto» o «como antes».
- Agente: tabla propia y última jornada de una liga (la simulación, solo para planes pro/max y administradores), apodos de equipos, fechas relativas, nivel «abierto» de permisividad con IA y defensa contra la inyección de instrucciones (saneo del texto externo y 32 ataques de prueba).
- Modelo: memoria de errores, cadena de sellos de los pronósticos, alerta de deriva y memoria por equipo expuesta por API; la memoria del modelo aparece en el perfil de un equipo.
- La cascada de IA aparta unos minutos a un proveedor que responde 401, 402, 403 o 404 y tolera respuestas sin texto.
- Corregido: un cuerpo JSON con `NaN` devolvía 500 en vez de 422; «la liga chilena» se resolvía como La Liga de España.
- Términos de uso del modelo (`docs/terminos-del-modelo.md`) y mediciones documentadas: el modelo supera a la tasa base y no alcanza al mercado donde hay cuotas.

## 1.0.0 — primera versión pública
- Backend FastAPI con bot de Telegram, planificador y web en el mismo proceso (puerto 9001), y agente de chat independiente (puerto 9100).
- Motor de pronóstico: modelo histórico Dixon-Coles (sin datos ni modelos entrenados incluidos), cuotas sin margen, consenso ponderado con puerta de calidad y nivel de evidencia N4…N0.
- Tres scripts a la vista: `instalar`, `configurar` (detecta y prueba cada API, ✓/✗/⚠, clave por número, también desde el panel web) e `iniciar`.
- Instalación portable para Windows, Linux, macOS y WSL: Python propio (uv) y Node/pnpm opcionales, descargas verificadas por SHA-256, asistente de `.env`, `laplace doctor`.
- Web, PWA y app Android (Kotlin/Compose).
- Licencia AGPL-3.0.
