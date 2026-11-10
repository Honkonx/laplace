"""test_calidad_datos.py — puerta de calidad única compartida por analisis_completo y top_picks.

Auditoría 2026-10-06: la puerta no contaba `historico` (que no necesita fuentes externas), contaba
odds y BSD como dos fuentes independientes aunque BSD consume cuotas, y cada flujo tenía su propia
lista de fuentes."""
from __future__ import annotations

from backend.api.services import analisis_completo, calidad_datos, top_picks


def _sin_historico(monkeypatch):
    monkeypatch.setattr(calidad_datos.modelo_historico_svc, "validar_historico", lambda d: (False, "fuera de cobertura"))


def _con_historico(monkeypatch):
    monkeypatch.setattr(calidad_datos.modelo_historico_svc, "validar_historico", lambda d: (True, "ok"))


def test_odds_y_bsd_cuentan_como_un_solo_canal_de_mercado(monkeypatch):
    _sin_historico(monkeypatch)
    calidad = calidad_datos.calcular_calidad_datos({"odds": True, "bsd": True}, {"local": "A"})
    assert calidad["sources"] == ["mercado"]
    assert calidad["source_count"] == 1
    assert calidad["eligible"] is True and calidad["tier"] == "completa"  # cuotas reales: ancla medido
    assert calidad["detalle_mercado"] == ["odds", "bsd"]


def test_bsd_solo_tambien_es_mercado(monkeypatch):
    _sin_historico(monkeypatch)
    calidad = calidad_datos.calcular_calidad_datos({"bsd": True}, {"local": "A"})
    assert calidad["sources"] == ["mercado"]
    assert calidad["eligible"] is False and calidad["tier"] == "exploratoria"  # BSD no vota ni es ancla


def test_historico_cuenta_como_fuente_propia_sin_fuentes_externas(monkeypatch):
    _con_historico(monkeypatch)
    calidad = calidad_datos.calcular_calidad_datos({}, {"local": "Arsenal", "visitante": "Chelsea", "liga": "Premier League"})
    assert calidad["sources"] == ["historico"]
    assert calidad["source_count"] == 1
    assert calidad["tier"] == "completa" and calidad["ancla"] is True  # ancla medido: publica sin segunda fuente


def test_historico_mas_mercado_habilita_publicacion(monkeypatch):
    _con_historico(monkeypatch)
    calidad = calidad_datos.calcular_calidad_datos({"odds": True}, {"local": "A"})
    assert set(calidad["sources"]) == {"mercado", "historico"}
    assert calidad["eligible"] is True and calidad["tier"] == "completa"


def test_sin_nada_es_sin_datos(monkeypatch):
    _sin_historico(monkeypatch)
    calidad = calidad_datos.calcular_calidad_datos({}, {"local": "A"})
    assert calidad["source_count"] == 0 and calidad["tier"] == "sin_datos" and calidad["eligible"] is False


def test_fallo_de_artefactos_no_tumba_la_puerta(monkeypatch):
    def explota(d):
        raise RuntimeError("artefacto ilegible")
    monkeypatch.setattr(calidad_datos.modelo_historico_svc, "validar_historico", explota)
    calidad = calidad_datos.calcular_calidad_datos({"tabla": True, "h2h": True}, {"local": "A"})
    assert calidad["eligible"] is True and "historico" not in calidad["sources"]


def test_analisis_completo_y_top_picks_usan_la_misma_funcion(monkeypatch):
    """Una sola definición de fuentes: mismas entradas, mismo veredicto en los dos flujos."""
    assert analisis_completo.calidad_datos_svc is calidad_datos
    assert top_picks.calidad_datos_svc is calidad_datos
    _sin_historico(monkeypatch)
    entrada = {"estadisticas_equipo": True, "tabla": True, "h2h": False, "odds": True}
    assert (
        analisis_completo.calidad_datos_svc.calcular_calidad_datos(entrada, {})
        == top_picks.calidad_datos_svc.calcular_calidad_datos(entrada, {})
    )
