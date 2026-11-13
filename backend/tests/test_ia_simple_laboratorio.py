"""test_ia_simple_laboratorio.py — hipótesis IA mínima del laboratorio: validación de la salida del
proveedor (JSON válido, con cercas de markdown, inválido, probabilidades que no suman 1) y
propagación del fallo del proveedor. Sin red: `generar_texto_ia_con_meta` se simula."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from backend.api.services import ia_simple_laboratorio as lab
from backend.api.services.ai_client import AnalisisIAError

_VALIDO = {"pick": "local", "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2, "marcador_probable": "2-1"}


def _simular_proveedor(monkeypatch, texto: str | None = None, error: Exception | None = None) -> AsyncMock:
    mock = AsyncMock(return_value=(texto, "groq", "modelo-x"), side_effect=error)
    monkeypatch.setattr(lab, "generar_texto_ia_con_meta", mock)
    return mock


def test_construir_prompt_incluye_partido_y_contrato_json():
    prompt = lab.construir_prompt("River", "Boca", "Liga Profesional")
    assert "River vs Boca" in prompt
    assert "Liga Profesional" in prompt
    assert "prob_local" in prompt and "sumar 1.00" in prompt


def test_generar_hipotesis_json_valido_devuelve_hipotesis_cruda_proveedor_y_modelo(monkeypatch):
    texto = json.dumps(_VALIDO)
    mock = _simular_proveedor(monkeypatch, texto)

    hipotesis, crudo, proveedor, modelo = asyncio.run(lab.generar_hipotesis("River", "Boca", "Liga"))

    assert hipotesis == {
        "pick": "local", "prob_local": 0.5, "prob_empate": 0.3, "prob_visitante": 0.2, "marcador_probable": "2-1",
    }
    assert crudo == texto
    assert (proveedor, modelo) == ("groq", "modelo-x")
    kwargs = mock.await_args.kwargs
    assert kwargs["rol"] == "laboratorio" and kwargs["max_tokens"] == 180 and kwargs["temperature"] == 0.2
    assert "River vs Boca" in mock.await_args.args[0]


def test_generar_hipotesis_acepta_cercas_markdown_y_texto_alrededor(monkeypatch):
    texto = "```json\n" + json.dumps(_VALIDO) + "\n```"
    _simular_proveedor(monkeypatch, texto)
    hipotesis, crudo, _, _ = asyncio.run(lab.generar_hipotesis("A", "B", "L"))
    assert hipotesis["pick"] == "local"
    assert crudo == texto  # el texto crudo se conserva tal cual para auditoría


def test_extraer_json_normaliza_pick_y_probabilidades_que_suman_casi_uno():
    data = {"pick": " Empate ", "prob_local": 0.33, "prob_empate": 0.34, "prob_visitante": 0.34}  # suma 1.01
    res = lab._extraer_json(json.dumps(data))
    assert res["pick"] == "empate"
    assert res["prob_local"] + res["prob_empate"] + res["prob_visitante"] == pytest.approx(1.0, abs=2e-4)
    assert res["marcador_probable"] is None  # ausente -> None, no cadena vacía


def test_extraer_json_trunca_marcador_a_32_caracteres():
    res = lab._extraer_json(json.dumps({**_VALIDO, "marcador_probable": "x" * 100}))
    assert len(res["marcador_probable"]) == 32


@pytest.mark.parametrize("texto, motivo", [
    ("no hay nada estructurado aquí", "no devolvió JSON"),
    ("} antes {", "no devolvió JSON"),
    ("[1, 2]{", "no devolvió JSON"),
])
def test_extraer_json_sin_objeto_lanza_valueerror(texto, motivo):
    with pytest.raises(ValueError, match=motivo):
        lab._extraer_json(texto)


def test_extraer_json_lista_dentro_de_llaves_no_es_objeto():
    # `{...}` válido como JSON pero que no es un dict no se puede construir con llaves; se prueba el
    # caso de JSON mal formado, que propaga JSONDecodeError (subclase de ValueError).
    with pytest.raises(ValueError):
        lab._extraer_json("{pick: local}")


def test_extraer_json_pick_invalido():
    with pytest.raises(ValueError, match="pick IA inválido"):
        lab._extraer_json(json.dumps({**_VALIDO, "pick": "victoria"}))
    with pytest.raises(ValueError, match="pick IA inválido"):
        lab._extraer_json(json.dumps({"prob_local": 0.4, "prob_empate": 0.3, "prob_visitante": 0.3}))


def test_extraer_json_probabilidades_incompletas_o_no_numericas():
    sin_clave = {k: v for k, v in _VALIDO.items() if k != "prob_visitante"}
    with pytest.raises(ValueError, match="incompletas"):
        lab._extraer_json(json.dumps(sin_clave))
    with pytest.raises(ValueError, match="incompletas"):
        lab._extraer_json(json.dumps({**_VALIDO, "prob_local": "mucha"}))
    with pytest.raises(ValueError, match="incompletas"):
        lab._extraer_json(json.dumps({**_VALIDO, "prob_empate": None}))


@pytest.mark.parametrize("probs", [
    (0.5, 0.3, 0.1),    # suma 0,90
    (0.5, 0.4, 0.3),    # suma 1,20
    (1.2, -0.1, -0.1),  # fuera de rango aunque sume 1
])
def test_extraer_json_probabilidades_que_no_suman_uno_o_fuera_de_rango(probs):
    data = {"pick": "local", "prob_local": probs[0], "prob_empate": probs[1], "prob_visitante": probs[2]}
    with pytest.raises(ValueError, match="probabilidades IA inválidas"):
        lab._extraer_json(json.dumps(data))


def test_generar_hipotesis_json_invalido_propaga_valueerror(monkeypatch):
    _simular_proveedor(monkeypatch, "Lo siento, no puedo ayudar con eso.")
    with pytest.raises(ValueError, match="no devolvió JSON"):
        asyncio.run(lab.generar_hipotesis("A", "B", "L"))


def test_generar_hipotesis_probabilidades_invalidas_propaga_valueerror(monkeypatch):
    malo = {**_VALIDO, "prob_local": 0.9, "prob_empate": 0.9, "prob_visitante": 0.9}
    _simular_proveedor(monkeypatch, json.dumps(malo))
    with pytest.raises(ValueError, match="probabilidades IA inválidas"):
        asyncio.run(lab.generar_hipotesis("A", "B", "L"))


def test_generar_hipotesis_proveedor_que_falla_propaga_analisisiaerror(monkeypatch):
    _simular_proveedor(monkeypatch, error=AnalisisIAError("todos los proveedores fallaron"))
    with pytest.raises(AnalisisIAError, match="todos los proveedores"):
        asyncio.run(lab.generar_hipotesis("A", "B", "L"))
