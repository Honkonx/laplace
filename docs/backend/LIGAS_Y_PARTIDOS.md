# Ligas y partidos: identidad de una competición

Una competición se identifica por **nombre + país**, no solo por el nombre (`services/ligas_ident.py`).

## Qué pasaba (medido en la base real el 2026-11-12)
El `liga_slug` se armaba solo con el nombre y el país que manda la fuente (`Cnm` en LiveScore) se descartaba al guardar: `premier-league` juntaba 280 equipos distintos (Inglaterra, Egipto, Israel, Kazajistán, Kenia, Baréin…), `super-league` 101, `ligue-1` 68 (Francia tiene 18), `serie-b` mezclaba Italia con Brasil y `league-stage` a la Champions con la Europa League. El menú de Telegram, la pasarela de la app y el catálogo web agrupaban por ese identificador, así que una «liga» traía equipos y partidos de otra.

## Regla vigente
| Pieza | Qué hace |
|---|---|
| `ligas_ident.slug_competicion(nombre, pais)` | Con país: `premier-league-england` (≤ 43 caracteres: cabe en el `callback_data` de Telegram junto con la fecha). Sin país: el identificador de siempre (las filas viejas se siguen leyendo) |
| `ligas_ident.nombre_visible(nombre, pais)` | «Premier League (Inglaterra)»; si el nombre ya trae el país, se deja igual |
| `ligas_ident.pais_clave(pais)` | «Inglaterra» y «England» dan la misma clave (sinónimos de `ml/alias/ligas_alias.json`); un país sin sinónimo se usa tal cual |
| `partidos_dia.liga_pais` | País que declara la fuente (migración `fa2c4e6a8b0d`; se aplica sola al arrancar el backend en SQLite local) |

Quién la usa: el guardado desde las tres fuentes (LiveScore, BSD y API-Football agrupan ahora por nombre **y** país), el colector de resultados, el menú de Telegram (`bot/ligas.py`: cada país es una entrada), el botón de liga (`callback_liga` compara por identificador completo), la pasarela de la app y el catálogo web (`league.name` ya incluye el país y la respuesta trae `league.country`; la web y la PWA lo muestran sin cambios).

`partidos_dia.liga_codigo` NO se toca: `ml/vivo.py` lo lee como el id numérico de API-Football.

## Filas viejas
`python backend/scripts/reclasificar_partidos_dia.py` (solo informa) dice cuántas se pueden clasificar con el modelo histórico; `--aplicar` escribe, con copia previa e idempotente. En la base real del 2026-11-12: 1.102 de 11.878 clasificables; el resto (ligas fuera de la cobertura del modelo) queda sin país y se actualiza solo cuando la fuente vuelva a traer ese día.

## Qué no cubre
- El país llega en el idioma de cada fuente: `ligas_alias.json` trae 78 sinónimos español→inglés («Egipto» y «Egypt» dan `premier-league-egypt`); un país que falte en esa lista produciría dos identificadores si dos fuentes lo escriben distinto, y se agrega ahí.
- `analisis_comparativo.liga` y `resultados_partidos.liga` guardan el nombre sin país en su columna principal.
