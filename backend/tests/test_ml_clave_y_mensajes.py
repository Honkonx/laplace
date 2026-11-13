"""Clave del endpoint interno (generada sin mostrarla) y línea del modelo en los mensajes de Telegram del bot."""
from __future__ import annotations

from backend.api.ml.laplace import clave, pronostico, servicio
from backend.api.services import mensajes_analisis


def test_genera_la_clave_en_el_env_sin_devolverla(tmp_path):
    r = clave.generar(tmp_path)
    contenido = (tmp_path / ".env").read_text(encoding="utf-8")
    valor = contenido.split("ML_API_KEY=", 1)[1].splitlines()[0]
    assert r["creada"] is True and valor.startswith("lap-ml-") and len(valor) > 30 and valor not in str(r)


def test_conserva_el_resto_del_env_y_no_pisa_una_clave_existente(tmp_path):
    (tmp_path / ".env").write_text("OTRA=1\nML_API_KEY=existente-12345\n", encoding="utf-8")
    r = clave.generar(tmp_path)
    assert r["creada"] is False and "OTRA=1" in (tmp_path / ".env").read_text(encoding="utf-8") and "existente-12345" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_rotar_reemplaza_la_clave_y_conserva_lo_demas(tmp_path):
    (tmp_path / ".env").write_text("OTRA=1\nML_API_KEY=existente-12345\n", encoding="utf-8")
    r = clave.generar(tmp_path, rotar=True)
    texto = (tmp_path / ".env").read_text(encoding="utf-8")
    assert r["creada"] is True and "existente-12345" not in texto and "OTRA=1" in texto and texto.count("ML_API_KEY=") == 1


def test_el_mensaje_de_telegram_muestra_la_lectura_del_modelo_y_avisa_del_respaldo():
    modelo = servicio.resumen_para_consumidores({"ok": True, "fuente": "modelo_laplace", "degradado": False, "modelo": None, "validados": ["total", "btts", "o25"], **pronostico.pronosticar(1.6, 1.1)})
    con = mensajes_analisis._lineas_contexto_historico({"modelo_laplace": modelo})
    assert "🧮 Modelo Laplace:" in con and "goles 1.6-1.1" in con and "publicar" not in con.lower()
    respaldo = mensajes_analisis._lineas_contexto_historico({"modelo_laplace": {**modelo, "degradado": True}})
    assert "Respaldo Dixon-Coles" in respaldo
    assert "Laplace" not in mensajes_analisis._lineas_contexto_historico({"modelo_laplace": None})
    assert "Laplace" not in mensajes_analisis._lineas_contexto_historico({})


def test_los_mercados_de_goles_no_validados_no_llegan_a_ningun_consumidor():
    bruto = {"ok": True, "fuente": "modelo_laplace", "degradado": False, "modelo": None, "validados": [], **pronostico.pronosticar(1.6, 1.1)}
    r = servicio.resumen_para_consumidores(bruto)
    assert r["goles_esperados"] is None and r["btts_si"] is None and r["mas_2_5"] is None and r["marcador_mas_probable"] is None and r["p1x2"]
    assert "goles" not in mensajes_analisis._lineas_contexto_historico({"modelo_laplace": r})
    pub = servicio.publico(bruto)
    assert "btts" not in pub and "over_under" not in pub and "marcadores" not in pub and "goles_esperados" not in pub and pub["p1x2"]
    parcial = servicio.publico({**bruto, "validados": ["btts"]})
    assert "btts" in parcial and "over_under" not in parcial
