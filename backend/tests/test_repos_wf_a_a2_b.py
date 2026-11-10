"""Tests reales (BD SQLite en memoria) para los repos portados de WF-A/WF-A2/WF-B —
ver backend/api/db/{usuarios,jobs,analisis,codigos,fixture_cache}_repo.py y las funciones
nuevas de partidos_repo.py (guardar_partidos_dia/leer_partidos_dia_agrupado)."""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.api.db import (
    analisis_repo, auditoria_repo, codigos_repo, fixture_cache_repo, jobs_repo, partidos_repo, usuarios_repo,
)
from backend.api.models.jobs import Job
from backend.api.models.predicciones import AnalisisComparativo
from backend.api.models.usuarios import CodigoAcceso, Usuario


def test_registrar_y_verificar_acceso_telegram(db_session):
    r = usuarios_repo.registrar_usuario_telegram(db_session, "111", "111", "Juan")
    assert r["nuevo"] is True and r["plan"] == "free"

    r2 = usuarios_repo.registrar_usuario_telegram(db_session, "111", "111", "Juan")
    assert r2["nuevo"] is False

    acceso = usuarios_repo.verificar_acceso(db_session, "111")
    assert acceso == {"autorizado": True, "plan": "free", "es_admin": False}


def test_verificar_limite_free_siempre_puede(db_session):
    r = usuarios_repo.verificar_limite(db_session, "222", "free")
    assert r["puede"] is True and r["limite"] == 0


def test_verificar_limite_pro_respeta_tope_sin_fail_open(db_session):
    usuarios_repo.registrar_usuario_telegram(db_session, "333", "333", "Ana")
    for i in range(10):
        jobs_repo.crear_job(db_session, f"match{i}", "20260101", "333", "333", plan="pro")
    # Ajustar status a 'listo' manualmente para simular jobs completados hoy
    for j in db_session.query(Job).all():
        j.status = "listo"
    db_session.commit()

    r = usuarios_repo.verificar_limite(db_session, "333", "pro")
    assert r["usados"] == 10
    assert r["puede"] is False  # 10/10 ya usado — no fail-open


def test_rango_utc_dia_chile_convierte_dia_calendario_a_ventana_utc():
    """`Job.creado_en`/`completado_en` se persisten en UTC (normalizado 2026-09-09) — este
    helper es lo que reemplaza el `LIKE 'YYYY-MM-DD%'` roto contra esa columna (ver
    docstring de `jobs_repo.rango_utc_dia_chile`). Junio en Chile es horario de invierno
    (UTC-4, sin horario de verano) — el día calendario de Chile 2026-06-15 corresponde al
    rango UTC [2026-06-15 04:00:00, 2026-06-16 04:00:00)."""
    inicio_utc, fin_utc = jobs_repo.rango_utc_dia_chile("2026-06-15")
    assert inicio_utc == "2026-06-15 04:00:00"
    assert fin_utc == "2026-06-16 04:00:00"


def test_verificar_limite_cuenta_job_nocturno_chile_aunque_su_creado_en_utc_sea_el_dia_siguiente(db_session):
    """Regresión real: antes de normalizar `Job.creado_en` a UTC, `verificar_limite` filtraba
    con `Job.creado_en.like(f'{hoy}%')` usando `hoy` en hora local — al pasar la columna a
    UTC ese LIKE dejaba de contar los jobs creados de noche en Chile (su `creado_en` UTC cae
    en el día calendario SIGUIENTE). El fix usa `rango_utc_dia_chile` (rango UTC real del día
    de Chile) en vez de comparar prefijos de string."""
    usuarios_repo.registrar_usuario_telegram(db_session, "555", "555", "Noc")
    inicio_utc, fin_utc = jobs_repo.rango_utc_dia_chile("2026-06-15")

    # Dentro del rango (instante inicial inclusive) — debe contar aunque en UTC ya sea otro
    # día calendario que el "2026-06-15" de Chile que se está consultando.
    db_session.add(Job(job_id="job_noche", match_id="mN", fecha_partido="20260615", chat_id="555",
                        user_id="555", plan="pro", origen="telegram", status="listo", intentos=0,
                        creado_en=inicio_utc))
    # Justo en el borde final (exclusivo) — pertenece al día de Chile SIGUIENTE, no debe contar.
    db_session.add(Job(job_id="job_borde_siguiente", match_id="mB", fecha_partido="20260616",
                        chat_id="555", user_id="555", plan="pro", origen="telegram", status="listo",
                        intentos=0, creado_en=fin_utc))
    db_session.commit()

    inicio_hoy, fin_hoy = jobs_repo.rango_utc_dia_chile()
    # Como el conteo real de `verificar_limite` usa el día de Chile actual (no uno fijo), se
    # reescribe `creado_en` del job "dentro de ventana" al equivalente de HOY para poder
    # verificar el conteo real vía `verificar_limite` sin mockear el reloj.
    job_hoy = db_session.query(Job).filter(Job.job_id == "job_noche").first()
    job_hoy.creado_en = inicio_hoy
    job_borde = db_session.query(Job).filter(Job.job_id == "job_borde_siguiente").first()
    job_borde.creado_en = fin_hoy
    db_session.commit()

    r = usuarios_repo.verificar_limite(db_session, "555", "pro")
    assert r["usados"] == 1


def test_verificar_partido_completo_encuentra_job_del_dia_chile_por_rango_utc(db_session):
    """Mismo bug real que `verificar_limite` (ver test anterior), acá en
    `analisis_repo.verificar_partido_completo`: `Job.completado_en` (UTC) se filtraba con un
    `LIKE 'YYYY-MM-DD%'` contra `fecha[:10]` (día calendario de Chile) — dejó de ser válido al
    normalizar la columna a UTC. El fix usa `rango_utc_dia_chile(fecha[:10])`."""
    usuarios_repo.registrar_usuario_app(db_session, "dev-noc", "Noc")
    creado = jobs_repo.crear_job_app(db_session, "mX", "2026-06-15", "dev-noc", "pro")
    inicio_utc, _ = jobs_repo.rango_utc_dia_chile("2026-06-15")
    fila = db_session.query(Job).filter(Job.job_id == creado["job_id"]).first()
    fila.status = "listo"
    fila.completado_en = inicio_utc
    fila.resultado_app = '{"pick": "Local"}'
    db_session.commit()

    resultado = analisis_repo.verificar_partido_completo(db_session, "mX", "dev-noc", "2026-06-15")
    assert resultado["analisis_propio"]["existe"] is True
    assert resultado["analisis_propio"]["content"] == {"pick": "Local"}


def test_verificar_partido_completo_sin_fecha_no_filtra_por_dia(db_session):
    """`fecha` vacía preserva el comportamiento original (sin filtro de fecha, el LIKE '%' de
    antes) — no debe romperse al reemplazar el LIKE por el rango UTC."""
    usuarios_repo.registrar_usuario_app(db_session, "dev-sf", "SinFecha")
    creado = jobs_repo.crear_job_app(db_session, "mY", "2026-06-15", "dev-sf", "pro")
    fila = db_session.query(Job).filter(Job.job_id == creado["job_id"]).first()
    fila.status = "listo"
    fila.resultado_app = '{"pick": "Visitante"}'
    db_session.commit()

    resultado = analisis_repo.verificar_partido_completo(db_session, "mY", "dev-sf", "")
    assert resultado["analisis_propio"]["existe"] is True


def test_crear_job_y_leer_pendiente(db_session):
    creado = jobs_repo.crear_job(db_session, "m1", "20260101", "chat1", "u1")
    pendiente = jobs_repo.leer_job_pendiente(db_session)
    assert pendiente["job_id"] == creado["job_id"]
    assert pendiente["match_id"] == "m1"


def test_verificar_job_activo(db_session):
    assert jobs_repo.verificar_job_activo(db_session, "m2")["job_activo"] is False
    jobs_repo.crear_job(db_session, "m2", "20260101", "chat1", "u1")
    assert jobs_repo.verificar_job_activo(db_session, "m2")["job_activo"] is True


def test_actualizar_job_y_job_app(db_session):
    creado = jobs_repo.crear_job_app(db_session, "m3", "2026-01-01", "dev1", "free")
    jobs_repo.actualizar_job_app(db_session, creado["job_id"], "listo", {"pick": "Local"})
    leido = jobs_repo.leer_job_especifico(db_session, creado["job_id"], "dev1")
    assert leido["encontrado"] is True
    assert leido["content"] == {"pick": "Local"}


def test_reset_jobs_colgados_marca_error_solo_a_jobs_viejos(db_session):
    """`reset_jobs_colgados` existía pero ningún cron la llamaba (hallazgo real de la auditoría
    2026-09-09, ver `main.py::_job_reset_jobs_colgados`) — este test cubre la lógica real de
    recuperación: un job viejo en 'procesando' pasa a 'error', uno reciente no se toca."""
    viejo = jobs_repo.crear_job(db_session, "m_viejo", "20260101", "chat1", "u1")
    reciente = jobs_repo.crear_job(db_session, "m_reciente", "20260101", "chat1", "u1")

    hace_20_min = (datetime.now() - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    fila_viejo = db_session.query(Job).filter(Job.job_id == viejo["job_id"]).first()
    fila_viejo.status = "procesando"
    fila_viejo.creado_en = hace_20_min
    fila_reciente = db_session.query(Job).filter(Job.job_id == reciente["job_id"]).first()
    fila_reciente.status = "procesando"
    db_session.commit()

    resultado = jobs_repo.reset_jobs_colgados(db_session, timeout_min=15)

    assert resultado["reseteados"] == 1
    assert resultado["detalle"][0]["job_id"] == viejo["job_id"]
    assert resultado["detalle"][0]["status_anterior"] == "procesando"

    # Post-condición real en la BD, no solo el valor devuelto (empirical-verification-before-fix.md).
    db_session.expire_all()
    assert db_session.query(Job).filter(Job.job_id == viejo["job_id"]).first().status == "error"
    assert db_session.query(Job).filter(Job.job_id == reciente["job_id"]).first().status == "procesando"


def test_reset_jobs_colgados_es_idempotente(db_session):
    """Correrlo dos veces seguidas no re-marca ni duplica — el segundo pase no encuentra nada
    en 'pendiente'/'procesando' que siga viejo (ver `.claude/rules/database-safety.md`)."""
    job = jobs_repo.crear_job(db_session, "m_idemp", "20260101", "chat1", "u1")
    fila = db_session.query(Job).filter(Job.job_id == job["job_id"]).first()
    fila.status = "procesando"
    fila.creado_en = (datetime.now() - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    db_session.commit()

    primero = jobs_repo.reset_jobs_colgados(db_session, timeout_min=15)
    segundo = jobs_repo.reset_jobs_colgados(db_session, timeout_min=15)

    assert primero["reseteados"] == 1
    assert segundo["reseteados"] == 0


def test_guardar_analisis_individual_y_consenso_cache(db_session):
    analisis_repo.guardar_analisis_individual(db_session, "p1", "Local", "ALTA", 80, "texto1")
    r = analisis_repo.verificar_consenso_cache(db_session, "p1")
    assert r["debe_generar"] is True
    assert r["total_analisis"] == 1


def test_activar_cache_consenso_requiere_coincidencia(db_session):
    analisis_repo.guardar_analisis_individual(db_session, "p2", "Local", "ALTA", 80, "t1", fuente="python")
    analisis_repo.guardar_analisis_individual(db_session, "p2", "Local", "ALTA", 75, "t2", fuente="python")
    r = analisis_repo.activar_cache_consenso(db_session, "p2")
    assert r["activado"] is True
    assert r["tipo_consenso"] == "python"

    cache = analisis_repo.verificar_consenso_cache(db_session, "p2")
    assert cache["cache_consenso_hit"] is True
    assert cache["pick_consenso"] == "Local"


def test_guardar_analisis_multimodelo(db_session):
    r = analisis_repo.guardar_analisis_multimodelo(
        db_session,
        partido_id="p3", local="A", visitante="B", liga="Liga X", pick_final="A",
        confianza="ALTA", score_final=70, consenso_nivel="FUERTE",
        pick_poisson="Local", score_poisson=70,
        modulos_data=[{"modulo": "poisson", "pick": "Local", "score": 70}],
    )
    assert r["guardado"] is True
    assert r["modulos_insertados"] == 1


def test_guardar_analisis_multimodelo_preserva_consenso_peso_python_peso_ia(db_session):
    """2026-09-09 — antes de este fix, `guardar_analisis_multimodelo` no seteaba `consenso`,
    `peso_python` ni `peso_ia` en `AnalisisComparativo` (solo los seteaba `guardar_comparativo`,
    la función que de verdad llamaba `_persistir` en `analisis_completo.py`). Al conectar
    `_persistir` a `guardar_analisis_multimodelo` (para poblar `AnalisisModulo` de verdad), esos
    3 campos se agregaron acá para no perderlos — ninguno es un campo por-módulo, así que no son
    parte de la normalización en sí, pero deben preservarse por paridad. Si no se pasa `consenso`
    explícito, cae a `consenso_nivel` (mismo criterio que usa `_persistir` real)."""
    r = analisis_repo.guardar_analisis_multimodelo(
        db_session,
        partido_id="p4", local="A", visitante="B", liga="Liga X", pick_final="A",
        confianza="ALTA", score_final=70, consenso_nivel="COINCIDEN",
        pick_poisson="Local", score_poisson=70,
        peso_python=0.6, peso_ia=0.4,
        modulos_data=[],
    )
    assert r["guardado"] is True
    fila = db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == "p4").first()
    assert fila.consenso == "COINCIDEN"  # sin `consenso` explícito, cae a consenso_nivel
    assert fila.peso_python == 0.6
    assert fila.peso_ia == 0.4

    r2 = analisis_repo.guardar_analisis_multimodelo(
        db_session,
        partido_id="p5", local="A", visitante="B", liga="Liga X", pick_final="A",
        confianza="ALTA", score_final=70, consenso_nivel="MODERADO", consenso="DIVERGEN",
        modulos_data=[],
    )
    assert r2["guardado"] is True
    fila2 = db_session.query(AnalisisComparativo).filter(AnalisisComparativo.partido_id == "p5").first()
    assert fila2.consenso == "DIVERGEN"  # `consenso` explícito tiene prioridad sobre consenso_nivel
    assert fila2.peso_python == 0.5 and fila2.peso_ia == 0.5  # default de paridad con guardar_comparativo


def test_activar_codigo_una_vez(db_session):
    db_session.add(CodigoAcceso(codigo="KS-PRO-TEST123", plan="pro", dias=30, usado=0,
                                 creado_en=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db_session.commit()

    r1 = codigos_repo.activar_codigo(db_session, "KS-PRO-TEST123", "dev-x")
    assert r1["activado"] is True and r1["plan"] == "pro"

    r2 = codigos_repo.activar_codigo(db_session, "KS-PRO-TEST123", "dev-y")
    assert r2["activado"] is False and r2["error"] == "codigo_usado"


def test_fixture_cache_hit_miss(db_session):
    assert fixture_cache_repo.leer_fixture_cache(db_session, "m9")["hit"] is False
    fixture_cache_repo.guardar_fixture_cache(db_session, "m9", "2026-01-01", 555, league_id=39, season=2025)
    hit = fixture_cache_repo.leer_fixture_cache(db_session, "m9")
    # FixtureIdCache.apifootball_fixture_id es TEXT (ver models/partidos.py) — SQLite con
    # afinidad TEXT devuelve el valor como string aunque se haya guardado un int.
    assert hit["hit"] is True and str(hit["apifootball_fixture_id"]) == "555"


def test_guardar_y_leer_partidos_dia_agrupado(db_session):
    partidos_repo.guardar_partidos_dia(db_session, "2026-01-01", [
        {"match_id": "e1", "liga_slug": "premier", "liga_nombre": "Premier League",
         "local": "A", "visitante": "B", "hora_chile": "10:00"},
    ])
    r = partidos_repo.leer_partidos_dia_agrupado(db_session, "2026-01-01")
    assert r["total"] == 1
    assert "premier" in r["ligas"]

    r_liga = partidos_repo.leer_partidos_dia_agrupado(db_session, "2026-01-01", liga_slug="premier")
    assert r_liga["total"] == 1


def test_asignar_rol_valido_actualiza_y_registra_auditoria(db_session):
    """rol separado de plan desde 2026-09-10 (ver models/usuarios.py §v7) — regresión directa:
    antes de esto, "admin" era un pseudo-valor de `plan`; ahora `asignar_rol` es el único punto
    de escritura real de permiso, y debe quedar auditado igual que `cambiar_plan`."""
    usuarios_repo.registrar_usuario_telegram(db_session, "777", "777", "Rol")
    assert db_session.query(Usuario).filter(Usuario.device_id == "777").first().rol == "usuario"

    r = usuarios_repo.asignar_rol(db_session, "777", "admin", actor_admin_id="admin_test")
    assert r == {"accion": "rol_actualizado", "device_id": "777", "rol_anterior": "usuario", "rol": "admin"}
    assert db_session.query(Usuario).filter(Usuario.device_id == "777").first().rol == "admin"

    historial = auditoria_repo.listar_acciones_admin(db_session)
    assert any(h["accion"] == "cambiar_rol" and "777" in h["detalle"] for h in historial["acciones"])


def test_asignar_rol_invalido_no_toca_la_fila(db_session):
    usuarios_repo.registrar_usuario_telegram(db_session, "778", "778", "Rol2")
    r = usuarios_repo.asignar_rol(db_session, "778", "superadmin")
    assert "error" in r
    assert db_session.query(Usuario).filter(Usuario.device_id == "778").first().rol == "usuario"


def test_asignar_rol_usuario_inexistente_da_error(db_session):
    r = usuarios_repo.asignar_rol(db_session, "no_existe", "admin")
    assert r == {"error": "usuario no_existe no encontrado"}


def test_verificar_acceso_reconoce_admin_por_rol_no_solo_por_admin_ids(db_session):
    """`_es_admin` (lista fija `settings.admin_ids` de `.env`) y `rol == 'admin'` (asignado vía
    `asignar_rol`/`/gestionarusuario rol:admin`) son dos fuentes independientes — un usuario
    promovido por rol debe verse como admin en `verificar_acceso` sin estar en `admin_ids`."""
    usuarios_repo.registrar_usuario_telegram(db_session, "779", "779", "RolAdmin")
    usuarios_repo.asignar_rol(db_session, "779", "admin")

    acceso = usuarios_repo.verificar_acceso(db_session, "779")
    assert acceso == {"autorizado": True, "plan": "admin", "es_admin": True}


def test_verificar_limite_app_admin_por_rol_tiene_cuota_ilimitada(db_session):
    usuarios_repo.registrar_usuario_app(db_session, "dev-rol-admin", "RolApp")
    usuarios_repo.asignar_rol(db_session, "dev-rol-admin", "admin")

    r = usuarios_repo.verificar_limite_ia_app(db_session, "dev-rol-admin")
    assert r["puede"] is True and r["plan"] == "admin"
