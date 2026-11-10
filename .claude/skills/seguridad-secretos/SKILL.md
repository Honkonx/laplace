# seguridad-secretos

Rule-driven scanner for leaked secrets, credentials, tokens and sensitive data in local files (source code, logs, dumps). Use before committing, before sharing files externally, or when auditing the repo for exposed keys/tokens/credentials.

**Fusionado de**: `HaESkill-main`

---

## Qué hace

Escanea archivos y directorios en busca de huellas, secretos y datos sensibles usando
reglas del proyecto HaE (originalmente una extensión de Burp Suite), vía `ripgrep` +
PCRE2 sobre `rules/Rules.json`. El resultado es un reporte JSON deduplicado por
`(grupo, regla, match)`, con referencias `file:line:column` a cada hallazgo.

No reemplaza revisión humana: las reglas HaE están orientadas a recall (detectan de
más) y producen falsos positivos, sobre todo en código fuente normal. Siempre hay
que confirmar los hallazgos de valor leyendo la línea real antes de reportarlos como
un problema.

## Requisito: ripgrep

El script depende de `ripgrep` (`rg`) en el `PATH`. **No está instalado en este
entorno Windows todavía** — instalarlo antes de usar la skill:

```powershell
winget install BurntSushi.ripgrep.MSVC
```

(alternativas: `choco install ripgrep`, o descargar el binario desde
[github.com/BurntSushi/ripgrep/releases](https://github.com/BurntSushi/ripgrep/releases)
y agregarlo al `PATH`). Verificar con `rg --version`. Si `rg` no está en el `PATH`,
se puede indicar la ruta explícita con `--rg C:\ruta\a\rg.exe`.

No se necesita ninguna dependencia de Python fuera de la librería estándar (PyYAML es
opcional, solo si se quiere apuntar a un archivo de reglas `.yml`/`.yaml` en vez de
JSON).

## Uso para este proyecto

Un objetivo (archivo o directorio) siempre es obligatorio — el script nunca escanea
el directorio actual por defecto. Invocar el script desde la ruta absoluta de esta
skill, ya que el directorio de trabajo suele ser otro:

```bash
python ".claude/skills/seguridad-secretos/scripts/hae_scan.py" "backend/python" "frontend/src" "app-android"
```

(correr desde la raíz del repo — `<tu-carpeta>\bot deportivo`)

Casos de uso concretos en Laplace:

- **Antes de un commit** con cambios en `backend/python/` o `frontend/src/` — sobre todo si se
  tocó `.env`, algún script que llama a las APIs externas (The Odds API, api-football, BSD API,
  Claude, Telegram Bot Token), o cualquier archivo `.env*` que se haya podido colar fuera de
  `.gitignore`.
- **Auditoría periódica** de `backend/python/`, `frontend/src/` y `app-android/` completos,
  filtrando por el grupo `Sensitive Information` (keys, tokens, credenciales, Authorization
  headers) que es el de mayor prioridad.
- Si el escaneo confirma una fuga real (secreto en un archivo que sí llegó a un commit, a un
  artefacto compartido, o a un log), tratarlo como incidente: rotar la credencial expuesta de
  inmediato, no solo borrar el archivo.

## Cómo correr el script

```bash
python <ruta-skill>/scripts/hae_scan.py /ruta/a/objetivo [/ruta/objetivo2 ...]
```

El comando escribe `.hae/hae-scan-<timestamp>.json` en el directorio actual e imprime
un resumen por regla en stdout. Leer el JSON para el detalle, no recorrer el árbol de
archivos a mano.

Filtrar por grupo o por nombre de regla cuando solo interesa una categoría:

```bash
python <ruta-skill>/scripts/hae_scan.py /ruta/objetivo --group "Sensitive Information" --group "Basic Information"
```

Leer el reporte con una consulta pequeña en vez de volcar el archivo entero:

```bash
python -c "
import json,sys
d=json.load(open(sys.argv[1]))
for f in d['findings']:
    if f['group'] in ('Sensitive Information','Basic Information','Maybe Vulnerability'):
        loc=f['locations'][0]
        print(f\"{f['group']}/{f['rule']}\t{f['match']}\t{loc['file']}:{loc['line']}:{loc['column']}\tx{f['count']}\")
" .hae/hae-scan-<timestamp>.json
```

**Verificar antes de reportar.** Confirmar los hallazgos de valor leyendo la línea
real del archivo (`sed -n 'N,Mp' archivo` o el equivalente con el lector de
archivos). Tratar como ruido salvo que el contexto pruebe lo contrario: valores de
ejemplo (`example.com`, `xxx`), fixtures de tests, dependencias vendorizadas
(`node_modules`, `venv`), código minificado de librerías de terceros.

### Opciones principales

| Opción | Default | Propósito |
|--------|---------|-----------|
| `targets` | obligatorio | Uno o más archivos/directorios |
| `--rules RUTA` | `<skill-dir>/rules/Rules.json` | Set de reglas alternativo con el mismo esquema reducido |
| `--group NOMBRE` | todos | Mantiene grupos cuyo nombre contiene NOMBRE (repetible) |
| `--rule NOMBRE` | todas | Mantiene reglas cuyo nombre contiene NOMBRE (repetible) |
| `-o, --out RUTA` | `.hae/hae-scan-<ts>.json` | Ruta de salida; `-` imprime el JSON a stdout |
| `--context N` | `50` | Caracteres de contexto guardados alrededor de cada match, `0` desactiva |
| `--max-locations N` | `5` | Ubicaciones guardadas por valor único de match, `0` = todas |
| `--max-matches N` | `200` | Valores únicos de match guardados por regla, `0` = todos |
| `--ignore-ext EXT` | extensiones de imagen | Extensión a omitir (repetible, reemplaza los defaults) |
| `--rg RUTA` | busca `rg` en el `PATH` | Ruta explícita al binario de ripgrep |

## Grupos de reglas

| Grupo | Contenido | Señal |
|-------|-----------|-------|
| Fingerprint | Shiro, JWT, Swagger UI, Druid, Vite DevMode, … | Alta — indica qué corre el objetivo |
| Maybe Vulnerability | Deserialización Java, parámetros de debug, formularios de upload, … | Media — necesita confirmación manual |
| Basic Information | Email, teléfono, cédula, IP, dominio | Media — verificar que sea dato real, no fixture |
| Sensitive Information | Keys, tokens, campos de credenciales, cloud AK/SK, campos de auth | Máxima prioridad |
| Other | Linkfinder, All URL, Request URI, Source Map | Baja — material de inventario, muy ruidoso |

`Request URI`, `Linkfinder`, `All URL` y `Userinfo In Link` disparan mucho en código
fuente normal. Reportarlos como conteos y ejemplos, nunca como listado completo.

## Mantenimiento de reglas

`rules/Rules.json` es una copia del set de reglas HaE reducido a lo que necesita el
escaneo de archivos: solo se usan `group`, `name`, `loaded`, `regex`, `sensitive`. Los
campos orientados a HTTP de HaE (`scope`, `engine`, `color`, `validator`) y la
extracción en dos etapas `s_regex` / `format` se descartan a propósito — esta skill no
tiene mensaje HTTP que acotar, ni UI que colorear, ni contexto de request contra el
cual validar.

Para agregar o actualizar reglas, editar este archivo directamente: copiar la regla
de un set de reglas HaE, renombrar `f_regex` a `regex` y quitar los demás campos.
