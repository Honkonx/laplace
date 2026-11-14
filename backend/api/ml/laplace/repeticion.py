"""repeticion.py — la «máquina del tiempo»: repite un tramo del pasado con reloj simulado para probar que el sistema se verifica solo (SM-1 a SM-4).

Qué hace, día a día, sobre una base con las migraciones reales:
1. entrena el modelo SOLO con lo anterior a la ventana (sin fuga);
2. a las 00:00 de cada día incorpora los resultados que el SISTEMA ya verificó (filas `final` de `verificaciones`, nunca el dato oculto) y registra el pronóstico de los partidos de ese día
   en el laboratorio (que los encola en `verificaciones` con su hora de inicio);
3. avanza el reloj de a `paso_min` minutos llamando a `verificacion.procesar_vencidas` con una fuente falsa que entrega el resultado oculto SOLO cuando el reloj pasa inicio + 140 min.
Al final compara lo que quedó en la base con un cálculo directo (mismas probabilidades, mismas métricas) y audita que ningún pronóstico use algo posterior a su fecha.

El pronosticador solo recibe equipos y fecha (`Programado`): el marcador vive únicamente en `FuenteOculta`. Los partidos reales históricos no traen hora: se les da un inicio sintético
estable entre 12:00 y 20:00 UTC (así todo termina antes de la medianoche y la repetición equivale, partido a partido, a un recorrido walk-forward por días).
Solo librería estándar más lo que ya usa el modelo (numpy/scipy al entrenar).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from backend.api.core.horario import DURACION_PARTIDO_MIN, a_texto_utc, fecha_chile
from backend.api.ml import comparacion, metricas
from backend.api.ml.laplace import entrenamiento as ent, goles
from backend.api.models.predicciones import PronosticoExperimental
from backend.api.models.verificacion import Verificacion
from backend.api.services import laboratorio_pronosticos as lab, verificacion

VARIANTE = "maquina_del_tiempo"
EXPERIMENTO = "python_baseline"
RESULTADOS = ("H", "D", "A")
PICKS = ("local", "empate", "visitante")
UMBRALES = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
BANDAS = (("BAJA", 0.0, 0.50), ("MEDIA", 0.50, 0.60), ("ALTA", 0.60, 1.01))   # etiquetas vigentes de `services/consenso.py` (PROB_CONFIANZA_MEDIA y PROB_CONFIANZA_ALTA)


# ─────────────────────────────────────────────── el calendario y la verdad oculta
@dataclass(frozen=True)
class Programado:
    """Lo único que el pronosticador ve de un partido: quién juega y cuándo. Sin marcador."""
    partido_id: str
    liga: str
    local: str
    visitante: str
    dia: int            # date.toordinal() del día del partido (UTC)
    inicio: datetime    # UTC naive


def inicio_sintetico(liga: str, local: str, visitante: str, dia: int) -> datetime:
    """Hora de inicio estable (hash, no `hash()` de Python) entre 12:00 y 20:00 UTC en pasos de 30 min."""
    h = int(hashlib.sha256(f"{liga}|{local}|{visitante}|{dia}".encode()).hexdigest()[:8], 16)
    return datetime.fromordinal(dia) + timedelta(hours=12, minutes=30 * (h % 17))


def programar(por_liga: dict[str, list[dict]], ligas: list[str], desde: date, hasta: date) -> tuple[list[Programado], dict[str, tuple[int, int]]]:
    """Separa la ventana [desde, hasta] en lo que se ve (`Programado`) y lo que se oculta (marcadores)."""
    programados, ocultos = [], {}
    for liga in ligas:
        for p in por_liga.get(liga, []):
            if desde.toordinal() <= p["dia"] <= hasta.toordinal():
                pid = f"MT-{liga}-{p['dia']}-{len(programados):06d}"
                programados.append(Programado(pid, liga, p["local"], p["visitante"], p["dia"], inicio_sintetico(liga, p["local"], p["visitante"], p["dia"])))
                ocultos[pid] = (int(p["gl"]), int(p["gv"]))
    programados.sort(key=lambda q: (q.dia, q.inicio, q.partido_id))
    return programados, ocultos


class FuenteOculta:
    """Fuente de resultados falsa: entrega el marcador oculto solo cuando `reloj` pasa inicio + 140 min.

    `guion[partido_id]` = [(desplazamiento desde el inicio, respuesta)], gana la última entrada ya vencida. La respuesta puede ser una excepción (fuente caída, 429), `None` (sin dato)
    o un dict de estado ({"status": "PST"}); un {"status": "FT"} sin goles se completa con el marcador oculto."""

    def __init__(self, programados: list[Programado], ocultos: dict[str, tuple[int, int]], guion: dict[str, list[tuple[timedelta, object]]] | None = None):
        self.por_id = {p.partido_id: p for p in programados}
        self.ocultos, self.guion = ocultos, guion or {}
        self.reloj: datetime | None = None
        self.consultas = 0
        self.entregas: dict[str, datetime] = {}   # primer instante en que se entregó cada marcador

    async def __call__(self, client, fila: Verificacion):
        self.consultas += 1
        p = self.por_id.get(fila.partido_id)
        if p is None or self.reloj is None:
            return None
        respuesta = self._respuesta(p)
        if isinstance(respuesta, Exception):
            raise respuesta
        if isinstance(respuesta, dict) and respuesta.get("status") in verificacion.TERMINADOS:
            gl, gv = self.ocultos[p.partido_id]
            respuesta = {"goles_local": gl, "goles_visitante": gv, "liga": p.liga, "local": p.local, "visitante": p.visitante, **respuesta}
            self.entregas.setdefault(p.partido_id, self.reloj)
        return respuesta

    def _respuesta(self, p: Programado):
        propia = None
        for desplaza, resp in self.guion.get(p.partido_id, []):
            if self.reloj >= p.inicio + desplaza:
                propia = (resp,)
        if propia is not None:
            return propia[0]
        if self.reloj < p.inicio:
            return None
        if self.reloj < p.inicio + timedelta(minutes=DURACION_PARTIDO_MIN):
            return {"status": "2H"}
        return {"status": "FT"}


# ─────────────────────────────────────────────── el pronosticador (solo ve equipos y fecha)
class Pronosticador:
    """Estado por liga al día de lo ya verificado. `estado_hasta[liga]` es el último día cuyo resultado entró al estado (para auditar la fuga)."""

    def __init__(self, artefacto: dict, ultimo_dia_entrenamiento: dict[str, int]):
        self.art = artefacto
        self.estados = {liga: ent.EstadoLiga.de_dict(copy.deepcopy(info["estado"])) for liga, info in artefacto["ligas"].items()}   # copia: `de_dict` comparte los diccionarios y `actualizar` los muta
        self.s = (artefacto.get("goles") or {}).get("s")
        self.estado_hasta = {liga: ultimo_dia_entrenamiento.get(liga, 0) for liga in self.estados}

    def tiene_modelo(self, liga: str) -> bool:
        return liga in self.estados

    def incorporar(self, liga: str, local: str, visitante: str, gl: int, gv: int, dia: int) -> None:
        if liga in self.estados:
            self.estados[liga].actualizar(local, visitante, gl, gv)
            self.estado_hasta[liga] = max(self.estado_hasta[liga], dia)

    def pronosticar(self, p: Programado) -> dict:
        est = self.estados[p.liga]
        x = est.features(p.local, p.visitante)
        probs = ent.probs_lineal(ent.pesos_de(self.art, p.liga), x)
        lh, la = est.lambdas(p.local, p.visitante)
        if self.s is not None:
            lh, la = goles.encoger(lh, est.media_local, self.s), goles.encoger(la, est.media_visita, self.s)
        return {"p": probs, "lam_h": lh, "lam_a": la, "base_h": est.media_local, "base_a": est.media_visita, "tasa_base": tuple(self.art["ligas"][p.liga]["tasa_base"]),
                "conoce_local": est.conoce(p.local), "conoce_visitante": est.conoce(p.visitante), "estado_hasta": self.estado_hasta[p.liga]}


def entrenar_sin_fuga(por_liga: dict[str, list[dict]], desde: date, ligas: list[str], hiper: dict | None = None) -> tuple[dict, dict[str, int]]:
    """Entrena con lo ANTERIOR al día `desde`. Devuelve el artefacto y el último día de entrenamiento por liga (para la auditoría)."""
    corte = desde.toordinal()
    subconjunto = {c: por_liga[c] for c in ligas if c in por_liga}
    art = ent.entrenar_jerarquico(subconjunto, corte, especializar=False, hiper=hiper or ent.HIPERS["g3"], con_goles=True)
    ultimo = {c: max((p["dia"] for p in ps if p["dia"] < corte), default=0) for c, ps in subconjunto.items()}
    return art, ultimo


# ─────────────────────────────────────────────── la base temporal y el arnés
def crear_base_temporal(ruta: Path) -> Callable[[], Session]:
    """Base SQLite nueva construida con las migraciones reales (nunca la base de trabajo). Devuelve la fábrica de sesiones."""
    from alembic import command
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.api.core.config import settings
    from backend.api.core.esquema import _conservar_logging, _config

    ruta.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{ruta.as_posix()}"
    anterior = settings.DATABASE_URL
    settings.DATABASE_URL = url
    try:
        with _conservar_logging():
            command.upgrade(_config(), "head")
    finally:
        settings.DATABASE_URL = anterior
    return sessionmaker(bind=create_engine(url, connect_args={"check_same_thread": False}))


class MaquinaDelTiempo:
    """El arnés: reloj simulado + los trabajos reales (registro del laboratorio y `verificacion.procesar_vencidas`) sobre una base con migraciones."""

    def __init__(self, fabrica: Callable[[], Session], pronosticador: Pronosticador, programados: list[Programado], fuente: FuenteOculta, *,
                 paso_min: int = 30, dias_extra: int = 5, duplicar: set[str] | None = None, apagado: tuple[datetime, datetime] | None = None):
        self.fabrica, self.pron, self.programados, self.fuente = fabrica, pronosticador, programados, fuente
        self.paso_min, self.dias_extra = paso_min, dias_extra
        self.duplicar, self.apagado = duplicar or set(), apagado
        self.registros: list[dict] = []
        self.sin_modelo: list[str] = []
        self.reinicios = 0
        self._reloj_sim = datetime.fromordinal(min((p.dia for p in programados), default=1))
        self._incorporados: set[str] = set()
        self._por_dia: dict[int, list[Programado]] = {}
        for p in programados:
            self._por_dia.setdefault(p.dia, []).append(p)

    def correr(self) -> dict:
        original = verificacion.utc_ahora       # el reloj del sistema es el simulado: sin esto `encolar` programaría desde la fecha real de hoy y nada vencería
        verificacion.utc_ahora = lambda: self._reloj_sim
        try:
            asyncio.run(self._correr())
        finally:
            verificacion.utc_ahora = original
        return {"registrados": len(self.registros), "sin_modelo": len(self.sin_modelo), "consultas_a_la_fuente": self.fuente.consultas, "reinicios": self.reinicios}

    async def _correr(self) -> None:
        if not self.programados:
            return
        primero, ultimo = min(self._por_dia), max(self._por_dia)
        db = self.fabrica()
        reabrir = False
        for dia in range(primero, ultimo + self.dias_extra + 1):
            medianoche = datetime.fromordinal(dia)
            for k in range(24 * 60 // self.paso_min):
                reloj = self._reloj_sim = medianoche + timedelta(minutes=k * self.paso_min)
                if self.apagado and self.apagado[0] <= reloj < self.apagado[1]:
                    reabrir = True
                    if k == 0:   # el pronóstico del día no depende del verificador: se registra aunque este esté apagado
                        self._incorporar_verificados(db)
                        self._registrar_dia(db, dia, medianoche)
                    continue
                if reabrir:   # el backend vuelve a encender: sesión nueva, la cola persiste en la base
                    db.close()
                    db, reabrir = self.fabrica(), False
                    self.reinicios += 1
                self.fuente.reloj = reloj
                await verificacion.procesar_vencidas(db, None, ahora=reloj, fuente=self.fuente)
                if k == 0:   # primero se cierra lo que venció de anoche; recién entonces el día pronostica con todo lo ya verificado
                    self._incorporar_verificados(db)
                    self._registrar_dia(db, dia, medianoche)
        db.close()

    def _incorporar_verificados(self, db: Session) -> None:
        """Entra al estado lo que el sistema ya cerró (la fila `final` de la cola), no el dato oculto."""
        por_id = self.fuente.por_id
        nuevos = [(por_id[v.partido_id], v.goles_local, v.goles_visitante)
                  for v in db.query(Verificacion).filter(Verificacion.estado == "final").all() if v.partido_id in por_id and v.partido_id not in self._incorporados]
        for p, gl, gv in sorted(nuevos, key=lambda t: (t[0].dia, t[0].local)):
            self._incorporados.add(p.partido_id)
            self.pron.incorporar(p.liga, p.local, p.visitante, gl, gv, p.dia)

    def _registrar_dia(self, db: Session, dia: int, ahora: datetime) -> None:
        for p in sorted(self._por_dia.get(dia, []), key=lambda q: (q.inicio, q.partido_id)):
            if not self.pron.tiene_modelo(p.liga):
                self.sin_modelo.append(p.partido_id)
                continue
            f = self.pron.pronosticar(p)
            repeticiones = 2 if p.partido_id in self.duplicar else 1
            for i in range(repeticiones):
                corte = ahora + timedelta(minutes=60 * i)
                self._registrar(db, p, f, corte)
                self.registros.append({"partido_id": p.partido_id, "liga": p.liga, "dia": p.dia, "inicio": p.inicio, "corte": corte, **f})

    def _registrar(self, db: Session, p: Programado, f: dict, corte: datetime) -> None:
        pa, pe, pv = f["p"]
        lab.registrar_pronostico(
            db, experimento_codigo=EXPERIMENTO, partido_id=p.partido_id, fecha_partido=fecha_chile(a_texto_utc(p.inicio)) or "", local=p.local, visitante=p.visitante, liga=p.liga,
            fuente="maquina_del_tiempo", variante=VARIANTE, corte_datos_en=a_texto_utc(corte), hora_kickoff=a_texto_utc(p.inicio),
            datos={"base_h": f["base_h"], "base_a": f["base_a"], "tasa_base": list(f["tasa_base"]), "dia": p.dia, "estado_hasta": f["estado_hasta"],
                   "sin_historia": not (f["conoce_local"] and f["conoce_visitante"])},
            pick=PICKS[max(range(3), key=lambda i: f["p"][i])], prob_local=pa, prob_empate=pe, prob_visitante=pv,
            goles_local_esperados=f["lam_h"], goles_visitante_esperados=f["lam_a"])
        db.commit()


# ─────────────────────────────────────────────── casos, informe y cálculo independiente
def _resultado(gl: int, gv: int) -> str:
    return "H" if gl > gv else "A" if gv > gl else "D"


def casos_desde_base(db: Session, oraculo: dict[str, tuple] | None = None) -> list[dict]:
    """Lo que QUEDÓ en la base tras la repetición: un caso por partido verificado (el último pronóstico anterior al inicio)."""
    filas = db.query(PronosticoExperimental).filter(PronosticoExperimental.variante == VARIANTE, PronosticoExperimental.goles_local_real.isnot(None)) \
        .order_by(PronosticoExperimental.corte_datos_en.asc(), PronosticoExperimental.id.asc()).all()
    ultimo: dict[str, PronosticoExperimental] = {f.partido_id: f for f in filas}
    casos = []
    for f in sorted(ultimo.values(), key=lambda r: (json.loads(r.datos_json)["dia"], r.partido_id)):
        d = json.loads(f.datos_json)
        casos.append({"partido_id": f.partido_id, "liga": f.liga, "dia": d["dia"], "p": (f.prob_local, f.prob_empate, f.prob_visitante), "lam_h": f.goles_local_esperados,
                      "lam_a": f.goles_visitante_esperados, "base_h": d["base_h"], "base_a": d["base_a"], "tasa_base": tuple(d["tasa_base"]), "gl": f.goles_local_real,
                      "gv": f.goles_visitante_real, "resultado": _resultado(f.goles_local_real, f.goles_visitante_real), "sin_historia": d["sin_historia"],
                      "oraculo": (oraculo or {}).get(f.partido_id)})
    return casos


def casos_directos(registros: list[dict], ocultos: dict[str, tuple[int, int]], oraculo: dict[str, tuple] | None = None) -> list[dict]:
    """El mismo conjunto de casos sin pasar por la base: pronósticos en memoria + marcador oculto. Es la referencia contra la que se compara lo guardado."""
    ultimo = {r["partido_id"]: r for r in sorted(registros, key=lambda r: r["corte"])}
    casos = []
    for r in sorted(ultimo.values(), key=lambda q: (q["dia"], q["partido_id"])):
        gl, gv = ocultos[r["partido_id"]]
        casos.append({"partido_id": r["partido_id"], "liga": r["liga"], "dia": r["dia"], "p": tuple(r["p"]), "lam_h": r["lam_h"], "lam_a": r["lam_a"], "base_h": r["base_h"],
                      "base_a": r["base_a"], "tasa_base": tuple(r["tasa_base"]), "gl": gl, "gv": gv, "resultado": _resultado(gl, gv),
                      "sin_historia": not (r["conoce_local"] and r["conoce_visitante"]), "oraculo": (oraculo or {}).get(r["partido_id"])})
    return casos


def _ll_poisson(lam: float, k: int) -> float:
    lam = max(lam, 1e-6)
    return -(k * math.log(lam) - lam - math.lgamma(k + 1))


def wilson(aciertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = aciertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    mitad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centro - mitad, centro + mitad)


def _pick(p) -> str:
    return RESULTADOS[max(range(3), key=lambda i: p[i])]


def informe(casos: list[dict], n_boot: int = 300) -> dict:
    """Aciertos 1X2, RPS, log loss y Brier frente a la tasa base, y goles por equipo (error absoluto y log-verosimilitud de Poisson frente a la media de la liga), con n e IC95."""
    n = len(casos)
    if n < 3:
        return {"n": n, "aviso": "menos de 3 partidos verificados: no se calcula nada"}
    bloques = [c["dia"] // 7 for c in casos]
    cero = [0.0] * n
    aciertos = sum(1 for c in casos if _pick(c["p"]) == c["resultado"])
    base_aciertos = sum(1 for c in casos if _pick(c["tasa_base"]) == c["resultado"])
    salida: dict = {"n": n, "acierto_1x2": {"valor": aciertos / n, "ic95": wilson(aciertos, n), "tasa_base_siempre_el_mas_comun": base_aciertos / n}}
    for nombre, f in (("rps", metricas.rps), ("log_loss", metricas.log_loss), ("brier", metricas.brier)):
        modelo, base = [f(c["p"], c["resultado"]) for c in casos], [f(c["tasa_base"], c["resultado"]) for c in casos]
        r = comparacion.comparar_perdidas(base, modelo, bloques, n_boot)
        salida[nombre] = {"modelo": r["perdida_b"], "tasa_base": r["perdida_a"], "ic95_modelo": comparacion.comparar_perdidas(modelo, cero, bloques, n_boot)["ic95"],
                          "mejora_sobre_tasa_base": r["diferencia_media"], "ic95_mejora": r["ic95"], "z": r["z"]}
    for lado, lam, base, real in (("local", "lam_h", "base_h", "gl"), ("visitante", "lam_a", "base_a", "gv")):
        mae_m, mae_b = [abs(c[lam] - c[real]) for c in casos], [abs(c[base] - c[real]) for c in casos]
        ll_m, ll_b = [_ll_poisson(c[lam], c[real]) for c in casos], [_ll_poisson(c[base], c[real]) for c in casos]
        rm, rl = comparacion.comparar_perdidas(mae_b, mae_m, bloques, n_boot), comparacion.comparar_perdidas(ll_b, ll_m, bloques, n_boot)
        salida[f"goles_{lado}"] = {"error_abs_modelo": rm["perdida_b"], "error_abs_media_de_la_liga": rm["perdida_a"], "mejora_error_abs": rm["diferencia_media"], "ic95_mejora_error_abs": rm["ic95"],
                                   "poisson_ll_mejora_por_partido": rl["diferencia_media"], "ic95_poisson": rl["ic95"], "z_poisson": rl["z"]}
    salida["sin_historia"] = sum(1 for c in casos if c["sin_historia"])
    if all(c.get("oraculo") for c in casos):
        ll_m, ll_o = [metricas.log_loss(c["p"], c["resultado"]) for c in casos], [metricas.log_loss(c["oraculo"], c["resultado"]) for c in casos]
        r = comparacion.comparar_perdidas(ll_m, ll_o, bloques, n_boot)    # positiva = el oráculo es mejor: es lo que le falta al modelo
        salida["frente_al_oraculo"] = {"log_loss_oraculo": r["perdida_b"], "log_loss_modelo": r["perdida_a"], "exceso_de_log_loss": r["diferencia_media"], "ic95_exceso": r["ic95"],
                                       "exceso_de_rps": sum(metricas.rps(c["p"], c["resultado"]) - metricas.rps(c["oraculo"], c["resultado"]) for c in casos) / n}
    return salida


def calculo_independiente(casos: list[dict]) -> dict:
    """Las mismas medias escritas aparte, con bucles directos y sin `comparacion`: la comprobación cruzada de `informe` (mismo resultado dentro de 1e-9)."""
    n = len(casos)
    out = {"n": n, "acierto": sum(1 for c in casos if max(range(3), key=lambda i: c["p"][i]) == RESULTADOS.index(c["resultado"])) / n}
    for nombre, f in (("rps", metricas.rps), ("log_loss", metricas.log_loss), ("brier", metricas.brier)):
        out[nombre] = math.fsum(f(c["p"], c["resultado"]) for c in casos) / n
        out[f"{nombre}_tasa_base"] = math.fsum(f(c["tasa_base"], c["resultado"]) for c in casos) / n
    for lado, lam, base, real in (("local", "lam_h", "base_h", "gl"), ("visitante", "lam_a", "base_a", "gv")):
        out[f"mae_{lado}"] = math.fsum(abs(c[lam] - c[real]) for c in casos) / n
        out[f"poisson_ll_mejora_{lado}"] = math.fsum(_ll_poisson(c[base], c[real]) - _ll_poisson(c[lam], c[real]) for c in casos) / n
    return out


def diferencia_maxima(inf: dict, indep: dict) -> float:
    """Mayor diferencia absoluta entre `informe` y `calculo_independiente` en las cifras que ambos calculan."""
    pares = [(inf["acierto_1x2"]["valor"], indep["acierto"])]
    for nombre in ("rps", "log_loss", "brier"):
        pares += [(inf[nombre]["modelo"], indep[nombre]), (inf[nombre]["tasa_base"], indep[f"{nombre}_tasa_base"])]
    for lado in ("local", "visitante"):
        pares += [(inf[f"goles_{lado}"]["error_abs_modelo"], indep[f"mae_{lado}"]), (inf[f"goles_{lado}"]["poisson_ll_mejora_por_partido"], indep[f"poisson_ll_mejora_{lado}"])]
    return max(abs(a - b) for a, b in pares)


def recalcular_directo(artefacto: dict, programados: list[Programado], ocultos: dict[str, tuple[int, int]]) -> dict[str, tuple]:
    """Recorrido walk-forward independiente por días (`entrenamiento.predecir_liga` y el estado del artefacto): pronostica todo el día con lo anterior y luego actualiza.

    Es lo que el arnés debe reproducir cuando todas las verificaciones salen bien: mismas probabilidades y mismos goles esperados partido a partido."""
    estados = {liga: ent.EstadoLiga.de_dict(copy.deepcopy(info["estado"])) for liga, info in artefacto["ligas"].items()}
    s = (artefacto.get("goles") or {}).get("s")
    por_dia: dict[int, list[Programado]] = {}
    for p in programados:
        if p.liga in estados:
            por_dia.setdefault(p.dia, []).append(p)
    salida = {}
    for dia in sorted(por_dia):
        for p in por_dia[dia]:
            r = ent.predecir_liga(artefacto, p.liga, p.local, p.visitante, estados[p.liga])
            lh, la = r["lambdas"]
            if s is not None:
                lh, la = goles.encoger(lh, r["medias"][0], s), goles.encoger(la, r["medias"][1], s)
            salida[p.partido_id] = (tuple(r["p1x2"]), lh, la)
        for p in sorted(por_dia[dia], key=lambda q: q.local):
            gl, gv = ocultos[p.partido_id]
            estados[p.liga].actualizar(p.local, p.visitante, gl, gv)
    return salida


def auditar_fugas(registros: list[dict], fuente: FuenteOculta, desde: date, ultimo_entrenamiento: dict[str, int]) -> dict:
    """«Cero fugas»: nada de lo usado para pronosticar es posterior a su fecha, y el marcador no salió antes de inicio + 140 min."""
    violaciones = []
    for liga, ultimo in ultimo_entrenamiento.items():
        if ultimo >= desde.toordinal():
            violaciones.append(f"entrenamiento de {liga} usa el día {ultimo} (>= inicio de la ventana)")
    for r in registros:
        if r["corte"] >= r["inicio"]:
            violaciones.append(f"{r['partido_id']}: pronóstico registrado a {r['corte']} (no es anterior al inicio {r['inicio']})")
        if r["estado_hasta"] >= r["dia"]:
            violaciones.append(f"{r['partido_id']}: el estado ya contenía el día {r['estado_hasta']} (>= el día del partido {r['dia']})")
    for pid, cuando in fuente.entregas.items():
        inicio = fuente.por_id[pid].inicio
        if cuando < inicio + timedelta(minutes=DURACION_PARTIDO_MIN):
            violaciones.append(f"{pid}: marcador entregado a {cuando} antes de inicio + {DURACION_PARTIDO_MIN} min")
    return {"revisados": len(registros), "entregas": len(fuente.entregas), "violaciones": violaciones, "cero_fugas": not violaciones}


def comparar_con_recorrido_directo(registros: list[dict], directo: dict[str, tuple]) -> float:
    """Mayor diferencia absoluta entre lo que registró el arnés y el recorrido directo (probabilidades y goles esperados)."""
    diffs = [0.0]
    for r in registros:
        p, lh, la = directo[r["partido_id"]]
        diffs += [abs(a - b) for a, b in zip(r["p"], p)] + [abs(r["lam_h"] - lh), abs(r["lam_a"] - la)]
    return max(diffs)


# ─────────────────────────────────────────────── repetición completa (una llamada)
def repetir(por_liga: dict[str, list[dict]], ligas: list[str], desde: date, hasta: date, fabrica: Callable[[], Session], *, paso_min: int = 60,
            guion: dict | None = None, duplicar: set[str] | None = None, apagado: tuple[datetime, datetime] | None = None, oraculo_de: Callable[[dict], tuple] | None = None,
            artefacto: tuple[dict, dict[str, int]] | None = None, n_boot: int = 300) -> dict:
    """Entrena sin fuga, repite [desde, hasta] con reloj simulado y devuelve el informe, la comprobación independiente y la auditoría de fugas."""
    art, ultimo = artefacto or entrenar_sin_fuga(por_liga, desde, ligas)
    programados, ocultos = programar(por_liga, ligas, desde, hasta)
    oraculo = None
    if oraculo_de is not None:
        indice = {(p["dia"], p["local"], p["visitante"]): p for liga in ligas for p in por_liga.get(liga, [])}
        oraculo = {q.partido_id: oraculo_de(indice[(q.dia, q.local, q.visitante)]) for q in programados}
    fuente = FuenteOculta(programados, ocultos, guion)
    arnes = MaquinaDelTiempo(fabrica, Pronosticador(art, ultimo), programados, fuente, paso_min=paso_min, duplicar=duplicar, apagado=apagado)
    resumen = arnes.correr()
    db = fabrica()
    try:
        base = casos_desde_base(db, oraculo)
        cola = verificacion.estado_cola(db, datetime.fromordinal(hasta.toordinal() + 30))
    finally:
        db.close()
    directos = casos_directos(arnes.registros, ocultos, oraculo)
    inf = informe(base, n_boot)
    resultado = {"ventana": [desde.isoformat(), hasta.isoformat()], "ligas": ligas, "programados": len(programados), "ocultos": len(ocultos), **resumen, "cola": cola,
                 "verificados": len(base), "informe": inf, "casos": base}
    if len(base) >= 3 and len(directos) == len(base):
        resultado["diferencia_con_calculo_independiente"] = diferencia_maxima(inf, calculo_independiente(directos))
        resultado["casos_de_la_base_iguales_a_los_directos"] = all(a["partido_id"] == b["partido_id"] and a["p"] == b["p"] and (a["gl"], a["gv"]) == (b["gl"], b["gv"])
                                                                   for a, b in zip(base, directos))
    resultado["fugas"] = auditar_fugas(arnes.registros, fuente, desde, ultimo)
    resultado["diferencia_con_recorrido_directo"] = comparar_con_recorrido_directo(arnes.registros, recalcular_directo(art, programados, ocultos))
    return resultado


# ─────────────────────────────────────────────── SM-4: umbral de confianza × acierto × cobertura
def tabla_umbrales(casos: list[dict]) -> dict:
    """Para cada umbral t sobre la probabilidad del pick: n, cobertura, acierto con IC95 de Wilson; y por banda de las etiquetas vigentes (BAJA < 0,50, MEDIA 0,50–0,60, ALTA ≥ 0,60)."""
    n = len(casos)
    filas = [(max(c["p"]), 1 if _pick(c["p"]) == c["resultado"] else 0) for c in casos]

    def resumen(sel: list[tuple[float, int]]) -> dict:
        k = len(sel)
        a = sum(x for _, x in sel)
        return {"n": k, "cobertura": k / n if n else 0.0, "acierto": a / k if k else None, "ic95": wilson(a, k) if k else None, "prob_media": sum(p for p, _ in sel) / k if k else None}

    bandas = {}
    for nombre, lo, hi in BANDAS:
        r = resumen([f for f in filas if lo <= f[0] < hi])
        if r["n"]:
            r["veredicto"] = "calibrada" if r["ic95"][0] <= r["prob_media"] <= r["ic95"][1] else ("sobreconfiada" if r["prob_media"] > r["ic95"][1] else "subconfiada")
        bandas[nombre] = r
    ordenada = all(bandas[a]["n"] and bandas[b]["n"] and bandas[a]["ic95"][1] < bandas[b]["ic95"][0] for a, b in (("BAJA", "MEDIA"), ("MEDIA", "ALTA")))
    return {"n": n, "umbrales": {f"{t:.2f}": resumen([f for f in filas if f[0] >= t]) for t in UMBRALES}, "bandas": bandas, "las_bandas_se_separan_con_ic95": ordenada}
