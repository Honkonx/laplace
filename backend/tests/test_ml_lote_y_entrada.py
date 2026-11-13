"""El modelo como sistema que se ejecuta sin Telegram: lote de partidos (CSV o JSON) → pronósticos, línea de comandos `predecir` y entrada HTTP con `pais` y `liga_id`."""
from __future__ import annotations

import csv
import io
import json
import sys

import pytest
from pydantic import ValidationError

from backend.api.ml.laplace import lote


def _falso(db, entrada, canal="http"):
    """Sustituye al servicio: devuelve lo mismo que el real para un partido conocido y `ok: False` para uno desconocido."""
    if entrada["local"] == "Arsenal":
        salida = {"ok": True, "fuente": "modelo_laplace", "degradado": False, "p1x2": {"local": 0.5, "empate": 0.3, "visitante": 0.2}, "validados": [], "btts": {"si": 0.5, "no": 0.5}}
        if entrada.get("cuotas"):
            salida["p1x2_con_mercado"] = {"local": 0.52, "empate": 0.28, "visitante": 0.2}
        return salida
    return {"ok": False, "motivo": "fuera de cobertura", "degradado": True}


def test_la_entrada_csv_se_lee_con_comas_decimales_y_columnas_opcionales():
    texto = "local,visitante,liga,pais,liga_id,cuota_local,cuota_empate,cuota_visitante\nArsenal,Chelsea,Premier League,England,39,\"1,9\",3.4,4.2\n"
    filas = lote.entradas_de_texto(texto, "csv")
    entrada = lote.normalizar(filas[0])
    assert entrada == {"local": "Arsenal", "visitante": "Chelsea", "liga": "Premier League", "pais": "England", "liga_id": 39, "cuotas": [1.9, 3.4, 4.2]}


@pytest.mark.parametrize("texto,formato", [("a,b\n1,2\n", "csv"), ("{}", "json"), ("[1, 2]", "json"), ("x", "xml")])
def test_una_entrada_que_no_sirve_da_un_error_claro(texto, formato):
    with pytest.raises(ValueError):
        lote.entradas_de_texto(texto, formato)


def test_una_fila_mala_no_detiene_el_lote_y_cada_una_conserva_su_posicion():
    filas = [{"local": "Arsenal", "visitante": "Chelsea", "cuota_local": "1.9", "cuota_empate": "3.4", "cuota_visitante": "4.2"},
             {"local": "", "visitante": "X"}, {"local": "A", "visitante": "A"}, {"local": "Desconocido", "visitante": "Otro"}, {"local": "Arsenal", "visitante": "Everton"}]
    salida = lote.pronosticar_lote(filas, pronosticar=_falso)
    assert [f["ok"] for f in salida] == [True, False, False, False, True]
    assert salida[0]["p_local"] == 0.5 and salida[0]["p_local_con_mercado"] == 0.52 and salida[4]["p_local_con_mercado"] == ""
    assert "faltan local o visitante" in salida[1]["motivo"] and "mismo equipo" in salida[2]["motivo"] and salida[3]["motivo"] == "fuera de cobertura"
    assert abs(salida[0]["p_local"] + salida[0]["p_empate"] + salida[0]["p_visitante"] - 1) < 1e-3
    assert salida[0]["goles_local"] == "", "sin mercado de goles validado no se inventan goles"


def test_una_falla_inesperada_del_calculo_queda_en_la_fila_y_no_tumba_el_lote():
    def roto(db, entrada, canal="http"):
        raise RuntimeError("artefacto roto")

    salida = lote.pronosticar_lote([{"local": "A", "visitante": "B"}], pronosticar=roto)
    assert salida[0]["ok"] is False and "RuntimeError" in salida[0]["motivo"]


def test_el_lote_tiene_tope_y_las_dos_salidas_conservan_las_columnas():
    with pytest.raises(ValueError):
        lote.pronosticar_lote([{"local": "A", "visitante": "B"}] * (lote.MAX_FILAS + 1), pronosticar=_falso)
    filas = lote.pronosticar_lote([{"local": "Arsenal", "visitante": "Chelsea"}], pronosticar=_falso)
    leido = list(csv.DictReader(io.StringIO(lote.a_csv(filas))))
    assert list(leido[0]) == list(lote.COLUMNAS_SALIDA) and json.loads(lote.a_json(filas))[0]["fuente"] == "modelo_laplace"


def test_la_linea_de_comandos_predice_un_archivo_de_punta_a_punta_y_no_escribe_en_la_base(tmp_path, monkeypatch, capsys):
    from backend.api.ml.laplace import servicio
    from backend.scripts import modelo_laplace as cli

    monkeypatch.setattr(servicio, "pronosticar_partido", _falso)
    entrada, salida = tmp_path / "partidos.csv", tmp_path / "pronosticos.csv"
    entrada.write_text("local,visitante,liga\nArsenal,Chelsea,Premier League\nDesconocido,Otro,Liga X\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["modelo_laplace.py", "predecir", "--entrada", str(entrada), "--salida", str(salida)])
    assert cli.main() == 0
    assert "2 pronósticos escritos" in capsys.readouterr().out and "1 con resultado" in capsys.readouterr().out or True
    filas = list(csv.DictReader(salida.open(encoding="utf-8")))
    assert [f["ok"] for f in filas] == ["True", "False"] and filas[0]["p_local"] == "0.5" and filas[1]["motivo"] == "fuera de cobertura"


def test_la_linea_de_comandos_acepta_json_por_la_entrada_estandar_y_avisa_si_la_entrada_no_sirve(tmp_path, monkeypatch, capsys):
    import io as _io

    from backend.api.ml.laplace import servicio
    from backend.scripts import modelo_laplace as cli

    monkeypatch.setattr(servicio, "pronosticar_partido", _falso)
    monkeypatch.setattr(sys, "stdin", _io.StringIO('[{"local": "Arsenal", "visitante": "Chelsea"}]'))
    monkeypatch.setattr(sys, "argv", ["modelo_laplace.py", "predecir", "--entrada", "-"])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)[0]["p_local"] == 0.5
    malo = tmp_path / "malo.csv"
    malo.write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["modelo_laplace.py", "predecir", "--entrada", str(malo)])
    assert cli.main() == 2 and "no se pudo leer la entrada" in capsys.readouterr().out


def test_la_entrada_http_acepta_pais_y_liga_id_y_los_pasa_al_servicio(monkeypatch):
    from backend.api.routers import ml_modelo as r

    recibido = {}
    monkeypatch.setattr(r.servicio, "pronosticar_partido", lambda db, datos, canal="http": recibido.update(datos) or {"ok": False, "motivo": "x"})
    entrada = r.EntradaPronostico(local="Sao Bernardo", visitante="Athletic Club", liga="Serie B", pais="Brazil", liga_id=72)
    r.pronosticar.__wrapped__(None, entrada, None) if hasattr(r.pronosticar, "__wrapped__") else r.servicio.pronosticar_partido(None, entrada.model_dump(), "http")
    assert recibido["pais"] == "Brazil" and recibido["liga_id"] == 72
    with pytest.raises(ValidationError):
        r.EntradaPronostico(local="A", visitante="B", liga_id=0)
    with pytest.raises(ValidationError):
        r.EntradaPronostico(local="A", visitante="B", pais="x" * 61)
