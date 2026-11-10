"""install/comun/configurar.py — detecta, prueba y configura las conexiones externas de Laplace (APIs de datos, IA y Telegram).

  configurar                       lista numerada con ✓ / ✗ / ⚠ (prueba cada API con una llamada gratuita); un número abre su detalle y ahí pegas la clave
  configurar --estado              qué hay puesto en .env, SIN conectarse a nada
  configurar --probar              prueba todas las claves puestas (gratis); --incluir-costosas añade LiveScore6 y la prueba de ≈ 1 token de Ollama
  configurar --solo the-odds-api   abre directamente el detalle de una conexión

Se puede ejecutar cuando quieras para cambiar claves o el orden de la IA. Las claves se piden sin eco, se prueban contra el host oficial ANTES de guardarse, nunca se
imprimen ni van en argumentos de línea de comandos, y se escriben de forma atómica en `.env` (permisos 600 en Linux/macOS). La lista de conexiones sale de
`backend/api/core/conexiones.py` (la misma que usan el panel web y `doctor`). Solo librería estándar.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

RAIZ = Path(__file__).resolve().parents[2]
for ruta in (str(RAIZ), str(Path(__file__).resolve().parent)):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import configurar_env as entorno  # noqa: E402 — asistente de .env (lectura/escritura de líneas)
from backend.api.core import conexiones as cx  # noqa: E402

ORDEN_IA_DEFECTO = "ollama_cloud,groq,gemini,openrouter,claude"
_COLORES = {"ok": "32", "bad": "31", "warn": "33", "acc": "36", "dim": "2", "neg": "1"}
_GLIFOS = {cx.ESTADO_OK: "✓", cx.ESTADO_FALLA: "✗", cx.ESTADO_AVISO: "⚠"}
_ADMIN_IDS = re.compile(r"^\d+(,\d+)*$")


class Pantalla:
    """Salida con color solo si hay terminal; `color=False` en los tests y al redirigir."""

    def __init__(self, escribir: Callable[[str], None] = print, color: bool | None = None):
        self.escribir = escribir
        self.color = sys.stdout.isatty() and not os.environ.get("NO_COLOR") if color is None else color

    def c(self, clave: str, texto: str) -> str:
        return f"\033[{_COLORES[clave]}m{texto}\033[0m" if self.color else texto

    def linea(self, texto: str = "") -> None:
        self.escribir(texto)

    def glifo(self, estado: str) -> str:
        return self.c(estado, _GLIFOS[estado])


# --------------------------------------------------------------------------------------------------------------------------
# .env
# --------------------------------------------------------------------------------------------------------------------------

def cargar_env() -> list[str]:
    return entorno.leer(entorno.ENV)


def guardar_env(lineas: list[str]) -> None:
    """Escritura atómica: se escribe un archivo temporal y se reemplaza; nunca queda un `.env` a medias."""
    destino = entorno.ENV
    temporal = destino.with_name(destino.name + ".tmp")
    temporal.write_text("\n".join(lineas).rstrip("\n") + "\n", encoding="utf-8")
    try:
        temporal.chmod(0o600)
    except OSError:
        pass
    os.replace(temporal, destino)


def clave_de(lineas: list[str], conexion: cx.Conexion) -> str | None:
    valor = entorno.valor_de(lineas, conexion.variable)
    return valor if cx.valor_definido(valor) else None


def definidas(lineas: list[str]) -> set[str]:
    return {c.id for c in cx.CONEXIONES if clave_de(lineas, c)}


def poner_clave(lineas: list[str], conexion: cx.Conexion, valor: str) -> str | None:
    """Guarda la clave en las líneas (no en disco). Devuelve el motivo del rechazo, o None."""
    motivo = cx.formato_invalido(valor)
    if motivo:
        return motivo
    entorno.poner(lineas, conexion.variable, valor.strip())
    if conexion.modelo_variable and not entorno.valor_de(lineas, conexion.modelo_variable):
        entorno.poner(lineas, conexion.modelo_variable, conexion.modelo_defecto or "")
    if conexion.ia and (entorno.valor_de(lineas, "AGENT_IA_ACTIVA") or "false").lower() == "false":
        entorno.poner(lineas, "AGENT_IA_ACTIVA", "true")  # con una clave de IA, el agente debe usarla
    return None


def borrar_clave(lineas: list[str], conexion: cx.Conexion) -> None:
    entorno.poner(lineas, conexion.variable, "")


def orden_ia(lineas: list[str]) -> list[str]:
    conocidos = [c.ia for c in cx.proveedores_ia()]
    texto = entorno.valor_de(lineas, cx.ROLES_IA[0]) or ORDEN_IA_DEFECTO
    orden = [p for p in (x.strip() for x in texto.split(",")) if p in conocidos]
    return orden + [p for p in ORDEN_IA_DEFECTO.split(",") if p not in orden]


def guardar_orden_ia(lineas: list[str], orden: list[str]) -> None:
    for rol in cx.ROLES_IA:
        entorno.poner(lineas, rol, ",".join(orden))


# --------------------------------------------------------------------------------------------------------------------------
# detección y prueba
# --------------------------------------------------------------------------------------------------------------------------

def detectar(lineas: list[str], probar: Callable = cx.probar, con_red: bool = True, costosas: set[str] | None = None) -> dict[str, cx.Resultado]:
    """Estado de cada conexión por id. Sin clave → ✗; con clave → prueba gratuita (⚠ si la prueba cuesta y no se autorizó)."""
    costosas = costosas or set()
    estados: dict[str, cx.Resultado] = {}
    por_probar: list[cx.Conexion] = []
    for c in cx.CONEXIONES:
        if not clave_de(lineas, c):
            estados[c.id] = cx.Resultado(cx.ESTADO_FALLA, "sin clave")
        elif not con_red:
            estados[c.id] = cx.Resultado(cx.ESTADO_OK, "configurada (sin probar)")
        elif c.prueba.cobra_por_llamada and c.id not in costosas:
            estados[c.id] = cx.Resultado(cx.ESTADO_AVISO, "configurada · sin prueba gratuita (cobra por llamada)")
        elif c.prueba.cuesta and c.id not in costosas:
            estados[c.id] = cx.Resultado(cx.ESTADO_AVISO, f"configurada · la prueba cuesta {c.prueba.cuesta}: pídela con t")
        else:
            por_probar.append(c)
    if por_probar:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for c, resultado in zip(por_probar, pool.map(lambda x: probar(x, clave_de(lineas, x)), por_probar)):
                estados[c.id] = resultado
    return estados


def conexiones_con_coste(lineas: list[str]) -> list[cx.Conexion]:
    return [c for c in cx.CONEXIONES if clave_de(lineas, c) and (c.prueba.cobra_por_llamada or c.prueba.cuesta)]


def texto_coste(c: cx.Conexion) -> str:
    return "1 llamada de tu cuota de RapidAPI" if c.prueba.cobra_por_llamada else c.prueba.cuesta or ""


# --------------------------------------------------------------------------------------------------------------------------
# presentación
# --------------------------------------------------------------------------------------------------------------------------

def _relleno(texto: str, ancho: int) -> str:
    return texto + " " * max(1, ancho - len(texto))


def pintar_lista(p: Pantalla, estados: dict[str, cx.Resultado], lineas: list[str]) -> None:
    cuenta = {k: sum(1 for r in estados.values() if r.estado == k) for k in (cx.ESTADO_OK, cx.ESTADO_AVISO, cx.ESTADO_FALLA)}
    p.linea()
    p.linea(f"{p.c('acc', 'LAPLACE · CONEXIONES')}   {p.c('dim', f'detectado: {cuenta[cx.ESTADO_OK]} ✓  {cuenta[cx.ESTADO_AVISO]} ⚠  {cuenta[cx.ESTADO_FALLA]} ✗')}")
    faltan = cx.faltantes_para_pronosticar(definidas(lineas))
    if faltan:
        p.linea(p.c("warn", "Para tener pronósticos aún falta: ") + "; ".join(faltan) + ".")
    else:
        p.linea(p.c("dim", "Lo mínimo para tener pronósticos está puesto (cuotas + calendario). Lo demás es opcional."))
    for g in cx.GRUPOS:
        p.linea()
        p.linea(p.c("acc", g.titulo) + (p.c("dim", f"  — {g.nota}") if g.nota else ""))
        for c in (x for x in cx.CONEXIONES if x.grupo == g.id):
            r = estados[c.id]
            marca = p.c("warn", "  ← lo principal") if c.destacada else ""
            p.linea(f" {p.c('neg', str(c.numero).rjust(2))}  {_relleno(c.nombre, 24)}{p.glifo(r.estado)} {r.detalle}{marca}")
    p.linea()
    p.linea(p.c("dim", "Número = ver el nombre, el enlace y poner la clave · t = probar todo · o = orden de la IA · a = tu id de administrador · c = canal y grupo · q = salir"))


def pintar_detalle(p: Pantalla, c: cx.Conexion, r: cx.Resultado) -> None:
    p.linea()
    p.linea(f"{p.c('acc', f'{c.numero} · {c.nombre.upper()}')}   {p.glifo(r.estado)} {r.detalle}")
    p.linea(p.c("dim", "─" * 62))
    filas = [("Para qué sirve", c.sirve), ("Plan gratis", c.plan), ("Conseguir clave", c.enlace), ("Se guarda como", f"{c.variable} (en .env; nunca se vuelve a mostrar)"),
             ("Se prueba contra", c.host + (f"  (esta API cobra cada llamada: se prueba solo si lo pides)" if c.prueba.cobra_por_llamada else "")
              + (f"  (la prueba cuesta {c.prueba.cuesta})" if c.prueba.cuesta else ""))]
    if c.grupo == "partidos":
        filas.append(("Cambiar proveedor", "el calendario usa el primero con clave y datos; para cambiar, pon la clave del otro y borra esta"))
    for etiqueta, valor in filas:
        p.linea(f" {p.c('dim', _relleno(etiqueta, 18))}{valor}")
    p.linea()
    p.linea(p.c("dim", "p = pegar o cambiar la clave · t = probar ahora · a = abrir el enlace · b = borrar la clave · v = volver"))


# --------------------------------------------------------------------------------------------------------------------------
# sesión interactiva
# --------------------------------------------------------------------------------------------------------------------------

class Sesion:
    def __init__(self, entrada: Callable[[str], str] = input, clave: Callable[[str], str] = getpass.getpass, pantalla: Pantalla | None = None,
                 probar: Callable = cx.probar, abrir_url: Callable[[str], object] = webbrowser.open):
        self.entrada, self.clave, self.p, self.probar, self.abrir_url = entrada, clave, pantalla or Pantalla(), probar, abrir_url
        self.lineas = cargar_env()
        self.estados: dict[str, cx.Resultado] = {}
        self.cambios = False

    # -- utilidades
    def leer(self, texto: str) -> str:
        """Lee una línea; Ctrl+C / Ctrl+Z cuentan como Enter vacío (volver o salir), nunca como un error."""
        try:
            return self.entrada(texto)
        except (EOFError, KeyboardInterrupt):
            self.p.linea()
            return ""

    def preguntar_si(self, texto: str) -> bool:
        return self.leer(f"{texto} [s/N] ").strip().lower() in ("s", "si", "sí", "y", "yes")

    def guardar(self) -> None:
        guardar_env(self.lineas)
        self.cambios = True

    def detectar(self, costosas: set[str] | None = None) -> None:
        self.p.linea(self.p.c("dim", "Probando las conexiones (solo llamadas gratuitas)…"))
        self.estados = detectar(self.lineas, self.probar, True, costosas)

    def elegir_costosas(self) -> set[str]:
        con_coste = conexiones_con_coste(self.lineas)
        if not con_coste:
            return set()
        detalle = " y ".join(f"{c.nombre} ({texto_coste(c)})" for c in con_coste)
        return {c.id for c in con_coste} if self.preguntar_si(f"¿Probar también {detalle}?") else set()

    # -- pantallas
    def lista(self) -> None:
        pintar_lista(self.p, self.estados, self.lineas)

    def detalle(self, c: cx.Conexion) -> None:
        while True:
            pintar_detalle(self.p, c, self.estados[c.id])
            orden = self.leer(f"{c.numero} · {c.nombre} › ").strip().lower()
            if orden in ("", "v"):
                return
            if orden == "p":
                self.pegar(c)
            elif orden == "t":
                self.probar_una(c, pedida=True)
            elif orden == "a":
                self.p.linea(self.p.c("acc", c.enlace))
                if self.preguntar_si("¿Abrir ahora en tu navegador?"):
                    self.abrir_url(c.enlace)
            elif orden == "b":
                if clave_de(self.lineas, c) and self.preguntar_si(f"¿Borrar la clave de {c.nombre} de .env?"):
                    borrar_clave(self.lineas, c)
                    self.guardar()
                    self.estados[c.id] = cx.Resultado(cx.ESTADO_FALLA, "sin clave")
                    self.p.linea(self.p.c("warn", "Clave borrada de .env."))
            else:
                self.p.linea(self.p.c("warn", "Usa p, t, a, b o v."))

    def probar_una(self, c: cx.Conexion, pedida: bool = False) -> None:
        if not clave_de(self.lineas, c):
            self.p.linea(self.p.c("bad", "No hay clave que probar: ponla con p."))
            return
        if (c.prueba.cobra_por_llamada or c.prueba.cuesta) and not (pedida and self.preguntar_si(f"Esta prueba cuesta {texto_coste(c)}. ¿Continuar?")):
            return
        self.p.linea(self.p.c("dim", f"Probando contra {c.host}…"))
        r = self.probar(c, clave_de(self.lineas, c))
        self.estados[c.id] = r
        self.p.linea(f"{self.p.glifo(r.estado)} {r.detalle}")

    def pegar(self, c: cx.Conexion) -> None:
        self.p.linea()
        self.p.linea(f"Abre el enlace, crea tu clave y pégala aquí (no se verá). {self.p.c('acc', c.enlace)}")
        try:
            valor = self.clave("Clave (Enter vacío cancela): ").strip()
        except EOFError:
            valor = ""
        if not valor:
            self.p.linea(self.p.c("dim", "Cancelado."))
            return
        motivo = cx.formato_invalido(valor)
        if motivo:
            self.p.linea(f"{self.p.glifo(cx.ESTADO_FALLA)} {motivo}. No se guardó nada.")
            return
        if c.prueba.cobra_por_llamada or c.prueba.cuesta:
            if not self.preguntar_si(f"Para validarla hay que gastar {texto_coste(c)}. ¿Probarla antes de guardar? (si no, se guarda sin probar)"):
                poner_clave(self.lineas, c, valor)
                self.guardar()
                self.estados[c.id] = cx.Resultado(cx.ESTADO_AVISO, "configurada · sin probar")
                self.p.linea(f"{self.p.glifo(cx.ESTADO_AVISO)} Guardada en .env sin probar.")
                return
        self.p.linea(self.p.c("dim", f"Probando contra {c.host}…"))
        r = self.probar(c, valor)
        if r.estado == cx.ESTADO_FALLA:
            self.p.linea(f"{self.p.glifo(r.estado)} {r.detalle}. No se guardó nada; la clave anterior sigue como estaba.")
            return
        poner_clave(self.lineas, c, valor)
        self.guardar()
        self.estados[c.id] = r
        sufijo = "" if r.estado == cx.ESTADO_OK else " (no se pudo confirmar; revisa tu conexión y vuelve a probarla con t)"
        self.p.linea(f"{self.p.glifo(r.estado)} {r.detalle}. Guardada en .env.{sufijo}")

    def orden_de_la_ia(self) -> None:
        nombres = {c.ia: c for c in cx.proveedores_ia()}
        orden = orden_ia(self.lineas)
        while True:
            self.p.linea()
            self.p.linea(self.p.c("acc", "ORDEN DE LA IA") + self.p.c("dim", "  — se usa la primera que responda; las que no tienen clave se saltan solas (AI_ROUTING_*)"))
            for i, ia in enumerate(orden, 1):
                c = nombres[ia]
                r = self.estados.get(c.id) or cx.Resultado(cx.ESTADO_OK if clave_de(self.lineas, c) else cx.ESTADO_FALLA, "configurada" if clave_de(self.lineas, c) else "sin clave")
                self.p.linea(f" {i}º  {_relleno(c.nombre, 22)}{self.p.glifo(r.estado)} {r.detalle}")
            orden_texto = self.leer("Mover: «3 1» pasa el 3º a la posición 1 · v = guardar y volver › ").strip().lower()
            if orden_texto in ("", "v"):
                guardar_orden_ia(self.lineas, orden)
                self.guardar()
                self.p.linea(self.p.c("ok", "Orden guardado: ") + ", ".join(orden))
                return
            partes = orden_texto.split()
            if len(partes) == 2 and all(x.isdigit() and 1 <= int(x) <= len(orden) for x in partes):
                orden.insert(int(partes[1]) - 1, orden.pop(int(partes[0]) - 1))
            else:
                self.p.linea(self.p.c("warn", "Escribe dos números (de dónde y a dónde) o v."))

    def administrador(self) -> None:
        actual = entorno.valor_de(self.lineas, cx.VARIABLE_ADMIN_TELEGRAM) or "(vacío)"
        self.p.linea(f"\nAdministradores del bot ({cx.VARIABLE_ADMIN_TELEGRAM}): {actual}")
        self.p.linea(self.p.c("dim", "Tu id numérico te lo da el comando /mi_id del bot. Varios, separados por coma. Enter vacío = no cambiar."))
        valor = self.leer("Id(s) › ").strip().replace(" ", "")
        if not valor:
            return
        if not _ADMIN_IDS.fullmatch(valor):
            self.p.linea(self.p.c("bad", "Solo números separados por coma (por ejemplo 123456789,987654321). No se guardó nada."))
            return
        entorno.poner(self.lineas, cx.VARIABLE_ADMIN_TELEGRAM, valor)
        self.guardar()
        self.p.linea(self.p.c("ok", "Guardado."))

    def comunidad(self) -> None:
        self.p.linea("\n" + self.p.c("dim", "Canal de Top Picks y grupo de tu comunidad (todo opcional; Enter = no cambiar; un guion «-» lo deja vacío)."))
        for variable, ayuda in (("TELEGRAM_CANAL_ID", "canal, p. ej. @mi_canal"), ("TELEGRAM_GRUPO_URL", "enlace del grupo, p. ej. https://t.me/..."), ("TELEGRAM_GRUPO_NOMBRE", "nombre que se muestra")):
            actual = entorno.valor_de(self.lineas, variable) or "(vacío)"
            valor = self.leer(f"{variable} [{actual}] ({ayuda}) › ").strip()
            if not valor:
                continue
            valor = "" if valor == "-" else valor
            if any(ord(ch) < 32 for ch in valor) or len(valor) > 200:
                self.p.linea(self.p.c("bad", "Valor no válido; se omite."))
                continue
            entorno.poner(self.lineas, variable, valor)
            self.guardar()

    # -- bucle principal
    def ejecutar(self, solo: str | None = None) -> int:
        self.detectar(self.elegir_costosas())
        if solo:
            c = cx.por_id(solo)
            if not c:
                self.p.linea(self.p.c("bad", f"No conozco «{solo}». Opciones: " + ", ".join(x.id for x in cx.CONEXIONES)))
                return 2
            self.detalle(c)
            return self.salir()
        while True:
            self.lista()
            try:
                orden = self.leer("Elige un número › ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if orden in ("", "q"):
                break
            if orden.isdigit() and cx.por_numero(int(orden)):
                self.detalle(cx.por_numero(int(orden)))
            elif orden == "t":
                self.detectar(self.elegir_costosas())
            elif orden == "o":
                self.orden_de_la_ia()
            elif orden == "a":
                self.administrador()
            elif orden == "c":
                self.comunidad()
            else:
                self.p.linea(self.p.c("warn", f"No entendí «{orden}»."))
        return self.salir()

    def salir(self) -> int:
        if self.cambios:
            self.p.linea("\n" + self.p.c("ok", "Cambios guardados en .env.") + " Para aplicarlos: " + self.p.c("neg", "laplace reiniciar") + " (o ejecuta iniciar).")
        return 0


# --------------------------------------------------------------------------------------------------------------------------
# modos sin interacción
# --------------------------------------------------------------------------------------------------------------------------

def modo_lista(p: Pantalla, con_red: bool, costosas: bool) -> int:
    lineas = cargar_env()
    ids = {c.id for c in conexiones_con_coste(lineas)} if costosas else set()
    pintar_lista(p, detectar(lineas, con_red=con_red, costosas=ids), lineas)
    return 0


def _activar_ansi_en_windows() -> None:
    """Enciende el modo de secuencias ANSI de la consola de Windows (colores) sin pasar por un shell."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        salida = kernel.GetStdHandle(-11)
        modo = ctypes.c_ulong()
        if kernel.GetConsoleMode(salida, ctypes.byref(modo)):
            kernel.SetConsoleMode(salida, modo.value | 0x0004)
    except Exception:  # noqa: BLE001 — sin colores no pasa nada
        pass


def main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    _activar_ansi_en_windows()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--estado", action="store_true", help="qué hay puesto en .env, sin conectarse a nada")
    ap.add_argument("--probar", action="store_true", help="prueba (gratis) todas las claves puestas, sin menú")
    ap.add_argument("--incluir-costosas", action="store_true", help="con --probar: incluye LiveScore6 (1 llamada) y Ollama (≈ 1 token)")
    ap.add_argument("--solo", metavar="ID", help="abre directamente el detalle de una conexión (p. ej. the-odds-api)")
    args = ap.parse_args()
    if not entorno.ENV.exists():
        print("Falta el archivo .env: ejecuta primero el instalador (instalar.bat / instalar.sh).", file=sys.stderr)
        return 1
    p = Pantalla()
    if args.estado:
        return modo_lista(p, con_red=False, costosas=False)
    if args.probar:
        return modo_lista(p, con_red=True, costosas=args.incluir_costosas)
    if not sys.stdin.isatty():
        print("Este modo es interactivo y necesita una terminal. Para scripts usa --estado o --probar.", file=sys.stderr)
        return 1
    return Sesion(pantalla=p).ejecutar(solo=args.solo)


if __name__ == "__main__":
    sys.exit(main())
