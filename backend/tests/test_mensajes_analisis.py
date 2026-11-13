"""test_mensajes_analisis.py — formateo del mensaje final de Telegram/App. Port de
`Formatear Respuesta`/`Combinar Análisis` (plan con IA) y `Formatear Respuesta Free`
(plan free/sin IA) de WF-B."""
from __future__ import annotations

from backend.api.services.mensajes_analisis import formatear_mensaje_con_ia, formatear_mensaje_free


def _resultado_motor_base(**overrides):
    d = {
        "local": "Boca Juniors",
        "visitante": "River Plate",
        "liga": "Liga Profesional",
        "modulos": {
            "poisson": {
                "ok": True,
                "prob_local": 0.45,
                "prob_empate": 0.27,
                "prob_visitante": 0.28,
                "over25_prob": 0.55,
                "btts_prob": 0.60,
                "value_bet": True,
                "pick": "Local",
                "value_pct": 9.5,
                "confianza": "ALTA",
                "confianza_score": 72,
                "marcador_probable": "2-1",
            },
            "forma": {
                "ok": True,
                "prob_local": 0.50,
                "prob_visitante": 0.30,
                "score_para_claude": "Forma reciente: Boca 4W/5 | River 2W/5",
            },
            "h2h": {"score_para_claude": "River 4V 3E 3D en los últimos 10"},
            "odds": {"score_para_claude": "Boca @1.90 | Empate @3.30 | River @4.00"},
        },
    }
    d.update(overrides)
    return d


def _combinado_base(**overrides):
    d = {
        "texto_claude": (
            "🏆 Boca Juniors vs River Plate\n📍 Liga Profesional\n\nDATOS\n\n"
            "📈 Boca: buena forma\n📈 River: forma irregular\n\n"
            "⚖️ Balance y PICK: Boca Juniors"
        ),
        "pick_unificado": "Boca Juniors",
        "confianza_final": "ALTA",
        "score_consolidado": 78,
        "nivel_ia": "COINCIDEN",
        "pick_claude": "Boca Juniors",
    }
    d.update(overrides)
    return d


def test_formatear_mensaje_con_ia_incluye_bloque_de_claude_y_pick():
    msg = formatear_mensaje_con_ia(_resultado_motor_base(), _combinado_base(), "@LaplaceCanal", "https://t.me/grupo")
    assert "🏆 Boca Juniors vs River Plate" in msg
    assert "🎯 PICK: <b>Boca Juniors</b>" in msg
    assert "🟢 Confianza: ALTA (78/100)" in msg
    assert "Bankroll" not in msg  # sin lenguaje de apuestas (MB-08)
    # el bloque de Claude se corta ANTES de "⚖️ Balance y PICK:" (ese texto no debe duplicarse)
    assert msg.count("⚖️ Balance y PICK:") == 0
    assert "📢 Canal: @LaplaceCanal" in msg
    assert 'href="https://t.me/grupo"' in msg


def test_formatear_mensaje_con_ia_incluye_linea_de_forma_si_ok():
    msg = formatear_mensaje_con_ia(_resultado_motor_base(), _combinado_base(), "@c", "https://t.me/g")
    assert "📊 Forma: 50.0% | 30.0%" in msg


def test_formatear_mensaje_con_ia_texto_divergen():
    combinado = _combinado_base(nivel_ia="DIVERGEN")
    msg = formatear_mensaje_con_ia(_resultado_motor_base(), combinado, "@c", "https://t.me/g")
    assert "⚠️ Estadístico e IA divergen" in msg


def test_formatear_mensaje_con_ia_sin_texto_pick_usa_todo_el_texto():
    """Caso límite: si el texto de Claude no trae la línea '⚖️ Balance y PICK:' (formato
    roto/inesperado de la IA), _bloque_datos_desde_claude devuelve el texto completo sin
    cortar — no debe lanzar."""
    combinado = _combinado_base(texto_claude="Texto libre sin el marcador esperado")
    msg = formatear_mensaje_con_ia(_resultado_motor_base(), combinado, "@c", "https://t.me/g")
    assert "Texto libre sin el marcador esperado" in msg


def test_formatear_mensaje_free_muestra_candado_de_ia():
    msg = formatear_mensaje_free(_resultado_motor_base(), "@c", "https://t.me/g")
    assert "🔒 Análisis IA disponible en plan Pro" in msg
    assert "🏆 Boca Juniors vs River Plate" in msg
    assert "🎯 PICK: <b>Local</b>" in msg
    # los mercados de goles del Poisson crudo (sin calibrar) ya no se muestran (MB-02); los validados salen del modelo
    assert "Over 2.5" not in msg and "BTTS" not in msg and "Marcador esperado" not in msg and "Bankroll" not in msg
    # El value bet se calcula con el Poisson (sin evidencia de ventaja): no se muestra.
    assert "Value" not in msg
    assert "💎" not in msg


def test_formatear_mensaje_free_sin_h2h_ni_odds_usa_fallback():
    resultado = _resultado_motor_base()
    resultado["modulos"]["h2h"] = None
    resultado["modulos"]["odds"] = None
    msg = formatear_mensaje_free(resultado, "@c", "https://t.me/g")
    assert "Sin historial directo disponible." in msg
    assert "Sin odds disponibles — análisis estadístico puro." in msg


def test_formatear_mensaje_free_poisson_no_ok_usa_pick_indeterminado():
    resultado = _resultado_motor_base()
    resultado["modulos"]["poisson"] = {"ok": False}
    msg = formatear_mensaje_free(resultado, "@c", "https://t.me/g")
    assert "🎯 PICK: <b>Indeterminado</b>" in msg
    assert "📐 Estadístico: Sin datos" in msg


def test_formatear_mensaje_free_usa_consenso_si_poisson_no_participa():
    resultado = _resultado_motor_base(
        consenso={"pick_final": "Visitante", "confianza_final": "BAJA", "score_consenso": 32}
    )
    resultado["modulos"]["poisson"] = {"ok": False}
    msg = formatear_mensaje_free(resultado, "@c", "https://t.me/g")
    assert "🎯 PICK: <b>Visitante</b>" in msg
    assert "🔴 Confianza: BAJA (32/100)" in msg


def _consenso_ponderado(**overrides):
    d = {
        "pick_final": "Visitante", "confianza_final": "MEDIA", "score_consenso": 50,
        "total_modulos": 3, "nivel": "MODERADO",
        "prob_ponderada": {"local": 0.30, "empate": 0.25, "visitante": 0.45},
        "peso_efectivo": {"poisson": 0.10, "historico": 0.0, "forma": 0.0, "h2h": 0.0, "odds": 0.70, "tabla": 0.20, "bsd_ml": 0.0},
    }
    d.update(overrides)
    return d


def test_mensaje_free_muestra_probabilidad_ponderada_y_poisson_como_detalle():
    """El pick sale de la probabilidad ponderada: es la que se muestra. El Poisson (Local 45%)
    contradice al pick Visitante y por eso solo puede aparecer como detalle secundario."""
    resultado = _resultado_motor_base(consenso=_consenso_ponderado())
    msg = formatear_mensaje_free(resultado, "@c", "https://t.me/g")
    assert "Probabilidad del pick (consenso): Local 30.0% | Empate 25.0% | Visitante 45.0%" in msg
    assert "odds 70%" in msg and "tabla 20%" in msg and "poisson 10%" in msg
    assert "Detalle Poisson (un módulo más): 45.0% | Empate 27.0% | 28.0%" in msg
    assert msg.index("Probabilidad del pick") < msg.index("Detalle Poisson")


def test_mensaje_con_ia_muestra_probabilidad_ponderada():
    resultado = _resultado_motor_base(consenso=_consenso_ponderado())
    msg = formatear_mensaje_con_ia(resultado, _combinado_base(), "@c", "https://t.me/g")
    assert "Probabilidad del pick (consenso)" in msg
    assert "Value" not in msg


def test_mensaje_sin_poisson_pero_con_consenso_no_dice_sin_datos():
    resultado = _resultado_motor_base(consenso=_consenso_ponderado())
    resultado["modulos"]["poisson"] = {"ok": False}
    msg = formatear_mensaje_free(resultado, "@c", "https://t.me/g")
    assert "Probabilidad del pick (consenso)" in msg
    assert "Sin datos" not in msg.split("Probabilidad del pick")[1].splitlines()[0]
    assert "Detalle Poisson" not in msg


def test_mensaje_no_depende_de_que_la_ia_traiga_la_linea_value():
    combinado = _combinado_base(texto_claude="Datos\n💎 Value: Local (+9%)\n⚖️ Balance y PICK: Boca Juniors")
    msg = formatear_mensaje_con_ia(_resultado_motor_base(), combinado, "@c", "https://t.me/g")
    assert "🎯 PICK: <b>Boca Juniors</b>" in msg
    assert "Value" not in msg

# ─── Pie de comunidad configurable (repo público: sin canal ni grupo propios) ──────────────────

def test_pie_comunidad_muestra_solo_lo_configurado():
    from backend.api.services.mensajes_analisis import pie_comunidad

    assert pie_comunidad("", "") == ""
    assert pie_comunidad("@c", "") == "📢 Canal: @c"
    assert pie_comunidad("", "https://t.me/g") == '💬 <a href="https://t.me/g">Grupo de la comunidad</a>'
    assert pie_comunidad("@c", "https://t.me/g").splitlines()[0] == "📢 Canal: @c"


def test_el_mensaje_sin_canal_ni_grupo_no_deja_lineas_vacias_de_enlace():
    msg = formatear_mensaje_free(_resultado_motor_base(), "", "")
    assert "Canal:" not in msg and "Grupo de la comunidad" not in msg and 'href=""' not in msg


def test_los_goles_validados_del_modelo_se_muestran_y_los_no_validados_no():
    base = {**_resultado_motor_base(), "modelo_laplace": {"fuente": "modelo_laplace", "degradado": False, "p1x2": {"local": 0.5, "empate": 0.3, "visitante": 0.2},
                                                           "goles_esperados": {"local": 1.6, "visitante": 1.1, "total": 2.7}, "btts_si": 0.52, "mas_2_5": 0.55, "marcador_mas_probable": "1-1"}}
    con = formatear_mensaje_free(base, "@c", "https://t.me/g")
    assert "ambos marcan 52%" in con and "más de 2,5 55%" in con and "marcador 1-1" in con
    sin = formatear_mensaje_free({**base, "modelo_laplace": {**base["modelo_laplace"], "goles_esperados": None, "btts_si": None, "mas_2_5": None, "marcador_mas_probable": None}}, "@c", "https://t.me/g")
    assert "ambos marcan" not in sin and "marcador" not in sin.lower().replace("marcador esperado", "") and "Modelo Laplace" in sin
