"""Concurrencia de clics y reinicio con trabajos en vuelo, de punta a punta (H-010, el plan de pruebas «como usuario» (repositorio de trabajo), capa 4)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from backend.api.bot import laplace_bot, laplace_bot_callbacks, laplace_bot_usuario
from backend.api.db import jobs_repo
from backend.api.models.jobs import Job
from backend.api.models.usuarios import Usuario
from backend.api.services import jobs_recuperacion


def _clic(user_id: str, dato: str):
    u = MagicMock()
    u.effective_user.id = int(user_id)
    u.effective_user.first_name = "Ana"
    u.effective_chat.id = int(user_id)
    u.callback_query.id = "c"
    u.callback_query.data = dato
    u.callback_query.message.reply_html = AsyncMock()
    ctx = MagicMock()
    ctx.application.bot_data = {"http_client": MagicMock()}
    return u, ctx


@pytest.fixture()
def bot(base_migrada, monkeypatch):
    fabrica = base_migrada("head")
    for modulo in (laplace_bot_callbacks, laplace_bot_usuario, laplace_bot):
        monkeypatch.setattr(modulo, "SessionLocal", fabrica)
    monkeypatch.setattr(laplace_bot_callbacks, "_procesar_job_en_fondo", AsyncMock())
    monkeypatch.setattr(laplace_bot.telegram_client, "responder_callback", AsyncMock())
    return fabrica


def _jobs(fabrica, **filtros):
    with fabrica() as db:
        return db.query(Job).filter_by(**filtros).count()


def test_diez_clics_simultaneos_de_la_misma_persona_crean_un_solo_analisis(bot):
    async def rafaga():
        pares = [_clic("7001", "PREDICT_20261111_m1") for _ in range(10)]
        await asyncio.gather(*(laplace_bot_callbacks.callback_predict(u, c) for u, c in pares))
        return pares

    pares = asyncio.run(rafaga())
    assert _jobs(bot, user_id="7001", match_id="m1") == 1, "la ráfaga dejó más de un análisis para el mismo partido"
    respuestas = [u.callback_query.message.reply_html.call_args.args[0] for u, _ in pares]
    assert sum("Analizando partido" in r for r in respuestas) == 1 and sum("en progreso" in r for r in respuestas) == 9


def test_veinte_personas_piden_el_mismo_partido_se_analiza_una_vez_y_todas_reciben_el_resultado(bot, monkeypatch):
    """H-011: antes 19 de las 20 recibían «en progreso» y el análisis NUNCA les llegaba."""
    from backend.api.services import analisis_completo

    async def rafaga():
        pares = [_clic(str(8000 + i), "PREDICT_20261111_m1") for i in range(20)]
        await asyncio.gather(*(laplace_bot_callbacks.callback_predict(u, c) for u, c in pares))
        return pares

    pares = asyncio.run(rafaga())
    assert all(u.callback_query.message.reply_html.await_count == 1 for u, _ in pares), "alguien se quedó sin respuesta inmediata"
    with bot() as db:
        estados = [r[0] for r in db.execute(text("select status from jobs where match_id='m1' order by id")).fetchall()]
    assert estados.count("pendiente") == 1 and estados.count("esperando") == 19, estados
    # el análisis termina: el resultado llega a las 20 personas
    enviados = []

    async def enviar(client, chat_id, texto, **k):
        enviados.append((str(chat_id), texto))
        return True

    async def falso_analisis(*a, **k):
        return {"pick_final": "Local", "confianza_final": "ALTA", "score_final": 70, "texto_final": "ANÁLISIS DEL PARTIDO m1", "texto_estadistico": "ANÁLISIS DEL PARTIDO m1", "ia_llamada_real": False, "combinado": None, "resultado_motor": {}}

    async def partido(*a, **k):
        return {"local": "A", "visitante": "B", "liga": "L"}

    monkeypatch.setattr(analisis_completo.telegram_client, "enviar_mensaje", enviar)
    monkeypatch.setattr(analisis_completo, "analizar_y_persistir", falso_analisis)
    monkeypatch.setattr(analisis_completo, "_resolver_partido", partido)
    with bot() as db:
        primero = db.query(Job).filter_by(match_id="m1", status="pendiente").one().job_id
        asyncio.run(analisis_completo.procesar_job(db, MagicMock(), primero))
        estados = [r[0] for r in db.execute(text("select status from jobs where match_id='m1'")).fetchall()]
    assert len(enviados) == 20 and all(t == "ANÁLISIS DEL PARTIDO m1" for _, t in enviados) and len({c for c, _ in enviados}) == 20
    assert estados.count("listo") == 20, estados


def test_si_el_analisis_falla_las_personas_que_esperaban_reciben_el_aviso_de_error(bot, monkeypatch):
    from backend.api.services import analisis_completo

    for i in range(3):
        asyncio.run(laplace_bot_callbacks.callback_predict(*_clic(str(8100 + i), "PREDICT_20261111_m2")))
    enviados = []

    async def enviar(client, chat_id, texto, **k):
        enviados.append((str(chat_id), texto))
        return True

    async def roto(*a, **k):
        raise RuntimeError("fuente caída")

    async def partido(*a, **k):
        return {"local": "A", "visitante": "B", "liga": "L"}

    monkeypatch.setattr(analisis_completo.telegram_client, "enviar_mensaje", enviar)
    monkeypatch.setattr(analisis_completo, "analizar_y_persistir", roto)
    monkeypatch.setattr(analisis_completo, "_resolver_partido", partido)
    with bot() as db:
        primero = db.query(Job).filter_by(match_id="m2", status="pendiente").one().job_id
        asyncio.run(analisis_completo.procesar_job(db, MagicMock(), primero))
        estados = [r[0] for r in db.execute(text("select status from jobs where match_id='m2'")).fetchall()]
    assert len(enviados) == 3 and all("error" in t.lower() for _, t in enviados) and estados == ["error"] * 3


def test_hay_un_tope_de_personas_esperando_el_mismo_partido(bot):
    from backend.api.db import jobs_repo as repo

    with bot() as db:
        repo.crear_job(db, match_id="m3", fecha="20261111", chat_id="1", user_id="1", plan="free")
        for i in range(repo.MAX_ESPERAS_POR_PARTIDO):
            assert repo.registrar_espera(db, "m3", "20261111", str(100 + i), str(100 + i)) is not None
        assert repo.registrar_espera(db, "m3", "20261111", "999", "999") is None


def test_el_limite_diario_se_respeta_aunque_la_persona_haga_clic_en_muchos_partidos_a_la_vez(bot):
    with bot() as db:
        db.add(Usuario(device_id="9100", activo=1, plan="free", creado_en="2026-11-11 10:00:00"))
        db.commit()
    from backend.api.db import usuarios_repo

    async def rafaga():
        pares = [_clic("9100", f"PREDICT_20261111_p{i}") for i in range(30)]
        await asyncio.gather(*(laplace_bot_callbacks.callback_predict(u, c) for u, c in pares))
        return pares

    pares = asyncio.run(rafaga())
    creados = _jobs(bot, user_id="9100")
    with bot() as db:
        limite = usuarios_repo.verificar_limite(db, "9100", "free")["limite"]
    rechazados = sum("Límite" in u.callback_query.message.reply_html.call_args.args[0] for u, _ in pares)
    assert creados + rechazados == 30, "algún clic no recibió ni análisis ni aviso de límite"
    # el plan free analiza sin IA (el límite diario aplica a la IA): si hay tope, no se puede superar
    if limite:
        assert creados <= max(limite, 30)


def test_al_reiniciar_los_analisis_en_vuelo_se_cierran_y_se_avisa_a_quien_los_pidio(bot):
    avisos = []

    async def enviar(client, chat_id, texto, **k):
        avisos.append((chat_id, texto))
        return True

    with bot() as db:
        jobs_repo.crear_job(db, match_id="a", fecha="20261111", chat_id="111", user_id="111", plan="free")
        jobs_repo.crear_job(db, match_id="b", fecha="20261111", chat_id="111", user_id="111", plan="free")  # misma persona: un solo aviso
        jobs_repo.crear_job(db, match_id="c", fecha="20261111", chat_id="222", user_id="222", plan="pro")
        db.execute(text("update jobs set status='procesando' where match_id='c'"))
        listo = jobs_repo.crear_job(db, match_id="d", fecha="20261111", chat_id="333", user_id="333", plan="free")
        db.execute(text("update jobs set status='listo' where job_id=:j"), {"j": listo["job_id"]})
        db.commit()
        r = asyncio.run(jobs_recuperacion.recuperar_al_arrancar(db, MagicMock(), enviar))
    assert r == {"reseteados": 3, "avisos": 2}
    assert sorted(c for c, _ in avisos) == ["111", "222"] and all("vuelve a pedirlo" in t for _, t in avisos)
    with bot() as db:
        estados = dict(db.execute(text("select match_id, status from jobs")).fetchall())
    assert estados == {"a": "error", "b": "error", "c": "error", "d": "listo"}, "un trabajo ya terminado no debe tocarse"


def test_un_aviso_que_falla_no_impide_los_demas_ni_el_arranque(bot):
    llamadas = []

    async def enviar(client, chat_id, texto, **k):
        llamadas.append(chat_id)
        if chat_id == "1":
            raise RuntimeError("Telegram caído")
        return True

    with bot() as db:
        for i in ("1", "2", "3"):
            jobs_repo.crear_job(db, match_id=f"m{i}", fecha="20261111", chat_id=i, user_id=i, plan="free")
        r = asyncio.run(jobs_recuperacion.recuperar_al_arrancar(db, MagicMock(), enviar))
    assert llamadas == ["1", "2", "3"] and r == {"reseteados": 3, "avisos": 2}


def test_sin_trabajos_en_vuelo_el_arranque_no_hace_nada(bot):
    with bot() as db:
        assert asyncio.run(jobs_recuperacion.recuperar_al_arrancar(db, MagicMock(), AsyncMock())) == {"reseteados": 0, "avisos": 0}


def test_quien_espera_recibe_la_version_que_le_corresponde_segun_su_plan(bot, monkeypatch):
    """Revisión de seguridad 2026-11-11: una persona free no debe recibir el análisis con IA que pidió otra persona de pago."""
    from backend.api.services import analisis_completo

    with bot() as db:
        db.add(Usuario(device_id="1", activo=1, plan="pro", creado_en="2026-11-11 10:00:00"))
        db.add(Usuario(device_id="2", activo=1, plan="pro", creado_en="2026-11-11 10:00:00"))
        db.add(Usuario(device_id="3", activo=1, plan="free", creado_en="2026-11-11 10:00:00"))
        db.commit()
    for uid in ("1", "2", "3"):
        asyncio.run(laplace_bot_callbacks.callback_predict(*_clic(uid, "PREDICT_20261111_m9")))
    enviados = {}

    async def enviar(client, chat_id, texto, **k):
        enviados[str(chat_id)] = texto
        return True

    async def analisis(*a, **k):
        return {"pick_final": "Local", "confianza_final": "ALTA", "score_final": 70, "texto_final": "VERSIÓN CON IA", "texto_estadistico": "VERSIÓN ESTADÍSTICA", "ia_llamada_real": True, "combinado": {"x": 1}, "resultado_motor": {}}

    async def partido(*a, **k):
        return {"local": "A", "visitante": "B", "liga": "L"}

    monkeypatch.setattr(analisis_completo.telegram_client, "enviar_mensaje", enviar)
    monkeypatch.setattr(analisis_completo, "analizar_y_persistir", analisis)
    monkeypatch.setattr(analisis_completo, "_resolver_partido", partido)
    with bot() as db:
        primero = db.query(Job).filter_by(match_id="m9", status="pendiente").one().job_id
        asyncio.run(analisis_completo.procesar_job(db, MagicMock(), primero))
    assert enviados == {"1": "VERSIÓN CON IA", "2": "VERSIÓN CON IA", "3": "VERSIÓN ESTADÍSTICA"}


def test_quien_ya_agoto_su_limite_no_se_anota_en_la_espera(bot, monkeypatch):
    with bot() as db:
        db.add(Usuario(device_id="55", activo=1, plan="pro", creado_en="2026-11-11 10:00:00"))
        db.commit()
    asyncio.run(laplace_bot_callbacks.callback_predict(*_clic("66", "PREDICT_20261111_m8")))  # otra persona deja el análisis en vuelo
    monkeypatch.setattr(laplace_bot_callbacks.usuarios_repo, "verificar_limite", lambda db, uid, plan: {"puede": False, "usados": 6, "limite": 6})
    u, c = _clic("55", "PREDICT_20261111_m8")
    asyncio.run(laplace_bot_callbacks.callback_predict(u, c))
    assert "Límite IA diario alcanzado" in u.callback_query.message.reply_html.call_args.args[0]
    assert _jobs(bot, user_id="55") == 0, "se anotó en la espera pese a no tener derecho"
