# Guía: de cero a Laplace funcionando 🚀

Paso a paso para clonar, instalar, configurar, iniciar y usar Laplace. Son **tres scripts** en la carpeta principal: **`instalar`**, **`configurar`** e **`iniciar`** (`.bat` en Windows, `.sh` en Linux y macOS). Antes, echa un ojo a los [requisitos](requisitos.md).

| Quiero… | Windows | Linux / macOS / WSL |
|---|---|---|
| 1 · Instalar | `instalar.bat` | `bash instalar.sh` |
| 2 · Configurar mis APIs (cuando quiera) | `configurar.bat` | `./configurar.sh` |
| 3 · Iniciar | `iniciar.bat` | `./iniciar.sh` |

## 1. Conseguir el código 📥

**Con git** (recomendado, así podrás actualizar fácil):

```
git clone <URL-de-este-repositorio> laplace
cd laplace
```
La URL la ves en el botón verde **Code** del repositorio.

**Sin git:** descarga el `.zip` desde ese mismo botón y descomprímelo. Todo lo que sigue se hace **dentro de esa carpeta**.

## 2. Instalar 🧰

Ejecuta **`instalar.bat`** (doble clic) o `bash instalar.sh`. Por dentro, en orden: revisa tu equipo → descarga **uv** → instala **Python 3.13** propio en `runtime/` → instala las dependencias → compila la web (si hace falta, baja Node y pnpm) → crea tu `.env` con tus secretos → crea la base de datos → corre un diagnóstico. Cada descarga se compara con su huella SHA-256 y, si no coincide, se cancela sin extraer nada. Tarda unos minutos, según tu conexión.

Al final te hace **dos preguntas** (puedes decir que no a ambas y hacerlo después):
1. **«¿Configurar ahora tus conexiones?»** → abre `configurar` (paso 3).
2. **«¿Crear tu administrador de la web?»** → te pide un nombre de usuario y te muestra una contraseña **una sola vez**: guárdala. Sirve para entrar al panel de administración.

Es **repetible**: si se corta o quieres cambiar algo, vuelve a ejecutarlo y solo completa lo que falte (no resetea tu administrador ni tus claves).

| Windows | Linux / macOS / WSL | Para qué |
|---|---|---|
| `instalar.bat -SinAsistente` | `bash instalar.sh --sin-asistente` | no preguntar nada (útil para scripts) |
| `instalar.bat -Reconfigurar` | `bash instalar.sh --reconfigurar` | al final abrir directamente `configurar` |
| `instalar.bat -ConNode` | `bash instalar.sh --con-node` | traer Node y pnpm y recompilar la web |
| `instalar.bat -ConML` | `bash instalar.sh --con-ml` | numpy/scipy/scikit-learn, para entrenar |
| `instalar.bat -Rehacer` | `bash instalar.sh --rehacer` | recrear el entorno de Python desde cero |

## 3. Configurar tus APIs 🔑

Ejecuta **`configurar.bat`** (o `./configurar.sh`). Es el script para **detectar, probar y cambiar** tus claves, y puedes usarlo **cuando quieras**, no solo la primera vez. Al abrirlo revisa tu `.env` y **prueba cada API** con una llamada gratuita:

```
 LAPLACE · CONEXIONES   detectado: 9 ✓  2 ⚠  2 ✗
 CUOTAS DEL MERCADO
   4  The Odds API            ✓ válida · 500 créditos   ← lo principal
 IA
   7  Ollama Cloud            ⚠ configurada · la prueba cuesta ≈ 1 token: pídela con t
  11  Claude (Anthropic)      ✗ sin clave
 Elige un número ›
```

- **✓** la clave existe y el proveedor la aceptó · **✗** no hay clave (o la rechazó) · **⚠** está puesta pero no se pudo probar gratis.
- **Escribe un número** para ver el nombre de esa API, para qué sirve, su plan gratis y **el enlace donde conseguir la clave**. Ahí pegas la clave (**no se ve mientras la escribes**): se prueba contra el sitio oficial **antes** de guardarla. Si el proveedor la rechaza, no se guarda nada y la anterior sigue como estaba.
- `t` prueba todo otra vez · `o` cambia el **orden de la IA** · `a` pone tu id de administrador de Telegram · `c` el canal y el grupo · `q` sale.
- Las pruebas que **cuestan algo** (LiveScore6: 1 llamada de tu cuota; Ollama Cloud: ≈ 1 token) solo se hacen si tú lo aceptas.
- **Cambiar de proveedor:** para los datos (calendario, cuotas) pon la clave del otro proveedor y borra la del actual (`b` dentro de esa API); el calendario usa el primero que tenga clave y datos. La IA sí tiene orden configurable (`o`).
- Sin menú: `configurar.bat --estado` (qué hay puesto, sin conectarse), `--probar` (prueba todo, gratis) y `--solo the-odds-api` (abre directamente una API).

Tus claves quedan en el archivo **`.env`**, que **nunca se sube a git ni se muestra en pantalla**; nunca van por argumentos de línea de comandos. Qué significa cada línea: [docs/configuracion.md](docs/configuracion.md). Qué activa cada clave y dónde conseguirla: [requisitos](requisitos.md#-cuentas-y-claves-todas-opcionales).

> 💡 **Mínimo cómodo:** una clave de **cuotas** (The Odds API), **un calendario** (LiveScore6, BSD o api-football) y, si quieres explicaciones, una clave de IA. `configurar` te dice qué falta.

## 4. Iniciar ▶️

Ejecuta **`iniciar.bat`** (o `./iniciar.sh`). Si falta algo clave para tener pronósticos te lo **avisa** (y te ofrece abrir `configurar`), enciende el backend (API, bot de Telegram, planificador y web) y el agente en segundo plano, y **abre la web** en tu navegador: **<http://127.0.0.1:9001/>**. 🎉

Para lo demás está el control completo, **`laplace.bat <comando>`** (o `./laplace.sh <comando>`):

| Comando | Qué hace |
|---|---|
| `iniciar` | enciende todo (`--sin-agente` deja solo el backend; `--lan` abre el servicio a tu red local, por ejemplo para entrar desde el celular) |
| `configurar` | lo mismo que `configurar.bat` |
| `estado` | muestra qué está encendido y si responde |
| `detener` / `reiniciar` | apaga / reinicia (**reinicia después de cambiar claves** para que el bot y el agente las usen) |
| `logs` | últimas líneas del registro (`logs agente`, `-n 100`) |
| `doctor` | diagnóstico completo de la instalación |
| `abrir` | abre la web en el navegador |

## 5. Primer uso 👋

1. **Web:** entra a <http://127.0.0.1:9001/>, crea tu cuenta y mira los partidos del día. Los que tienen pronóstico aparecen primero.
2. **Panel de administración:** entra con el administrador que creaste al instalar y abre **Administración → Conexiones**: ahí ves lo mismo que en `configurar` (estado de cada API, **Probar**, **Poner o cambiar clave**, **Conseguir clave**, orden de la IA), también sin mostrar nunca las claves. Los cambios pueden pedir reiniciar.
3. **Bot de Telegram** (si pusiste el token): escríbele `/start`. Prueba `/juegos`, `/hoy` y `/top`.
4. **Hazte administrador del bot:** escribe `/mi_id`, copia el número que te da y pégalo con la opción `a` de `configurar` (o en `SPORTS_ADMIN_IDS` dentro de `.env`); luego reinicia.
5. **Revisa que todo esté sano:** `laplace doctor`. Los avisos son normales si no pusiste todas las claves; lo importante es que no haya fallos.
6. Si quieres usar la **misma cuenta en Telegram y en la web/app**, vincúlalas con `/vincular <usuario> <contraseña>` en el bot.

¿Un partido sale como **«sin pronóstico propio»**? Es esperado cuando no hay cuotas ni modelo para ese partido: el bot te explica el motivo. Mira [qué no trae este repositorio](README.md#qué-no-trae-este-repositorio-).

## 6. Mantenerlo al día 🔄

```
laplace detener          (laplace.bat / ./laplace.sh)
git pull
instalar                 (el instalador es repetible: solo completa lo nuevo)
iniciar
```
Tus claves (`.env`), la base de datos, tu administrador y `runtime/` no se tocan.

## 7. Cuando algo no va 🩺

| Síntoma | Qué mirar |
|---|---|
| «Falta el archivo .env» | ejecuta el instalador primero |
| Puerto 9001 o 9100 ocupado | algo más lo usa (o ya hay otra copia encendida): `laplace estado`; o cambia el puerto con `LAPLACE_PUERTO_BACKEND` / `LAPLACE_PUERTO_AGENTE` |
| El bot de Telegram no responde | `configurar` (¿el bot principal sale ✓?) y `laplace logs`; recuerda reiniciar tras cambiar el token |
| Todo sale «sin pronóstico propio» | falta una clave de cuotas (The Odds API) o no hay modelo propio: `configurar` lo marca |
| Las respuestas de IA no aparecen | ninguna clave de IA válida: `configurar` muestra cuáles fallan |
| Una clave sale ✗ pero es correcta | cópiala de nuevo completa (sin espacios); si el proveedor la rechaza, el mensaje dice el código HTTP. Con un ⚠ de «bloqueo» no es culpa de tu clave: reintenta más tarde |
| La descarga falla o la huella no coincide | revisa tu conexión (o proxy/antivirus) y vuelve a ejecutar el instalador; si insiste, **no** sigas: algo altera la descarga |
| «Poco espacio libre» | libera al menos 2 GB en el disco donde está la carpeta |
| Olvidaste la contraseña del administrador | `runtime\venv\Scripts\python backend\scripts\create_admin.py --username admin` (en Linux: `runtime/venv/bin/python backend/scripts/create_admin.py --username admin`) crea una nueva y la muestra una vez |
| Quieres empezar de cero | `instalar -Rehacer` (recrea solo el entorno de Python; tu `.env` y tus datos no se borran) |

Para entender cómo encaja todo: [arquitectura](docs/arquitectura/VISION_GENERAL.md). Para contribuir: [CONTRIBUTING.md](CONTRIBUTING.md). Y recuerda: **aquí se pronostica, no se apuesta** 🚫🎰.
