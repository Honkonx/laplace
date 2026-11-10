# Seguridad, datos de terceros y límites del producto

## Secretos
- `.env` nunca se sube a git ni se muestra: los instaladores y `laplace doctor` solo dicen si una clave está definida, jamás su valor.
- Un secreto ya guardado solo se usa, se reemplaza o se borra; ninguna pantalla ni endpoint lo vuelve a mostrar.
- `x-kairos-key` es solo para la app Android compilada: un secreto dentro del JavaScript de un navegador es público por definición.
- Antes de publicar un fork, escanea el árbol completo en busca de tokens (no confíes solo en `.gitignore`).

## Datos de terceros
Laplace puede usar api-football, football-data.org, football-data.co.uk, The Odds API, LiveScore6 (RapidAPI), BSD y proveedores de IA. **Cada uno tiene sus propios términos y planes; tú eres responsable de cumplirlos.**
- **football-data.co.uk** limita el uso de sus archivos (incluye restricciones sobre bots y sistemas de IA). Este repositorio **no incluye** sus datos, ni modelos entrenados con ellos, ni los scripts que los descargan. Si vas a usar esa u otra fuente, revisa sus términos antes.
- Los archivos crudos de api-football y football-data.org tampoco se redistribuyen.
- El plan gratis de api-football solo cubre algunas temporadas: `laplace doctor` y los mensajes del bot lo reflejan.

## Límites del producto
- **No es una casa de apuestas.** No acepta dinero para apostar, no intermedia apuestas entre usuarios ni hacia terceros, no custodia fondos y no condiciona nada a un resultado deportivo. Las cuotas son un insumo estadístico.
- **No promete aciertos.** Muestra el nivel de evidencia y la frecuencia real de acierto, también cuando es mala.
- Pronosticar no equivale a asesoría financiera.
