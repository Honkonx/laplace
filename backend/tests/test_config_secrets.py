"""test_config_secrets.py — `validar_secretos_arranque` (core/config.py): con ENV != "local" un
secreto por defecto/vacío/corto impide arrancar; con ENV == "local" solo avisa."""
from __future__ import annotations

import pytest

from backend.api.core.config import SECRETO_PLACEHOLDER, Settings, validar_secretos_arranque

SECRETO_BUENO_A = "a" * 40
SECRETO_BUENO_B = "b" * 40


def _cfg(env: str, kairos: str, jwt: str) -> Settings:
    return Settings(_env_file=None, ENV=env, KAIROS_AUTH_SECRET=kairos, WEB_JWT_SECRET=jwt)


def test_secretos_fuertes_pasan_en_cualquier_entorno():
    assert validar_secretos_arranque(_cfg("produccion", SECRETO_BUENO_A, SECRETO_BUENO_B)) == []
    assert validar_secretos_arranque(_cfg("local", SECRETO_BUENO_A, SECRETO_BUENO_B)) == []


@pytest.mark.parametrize("inseguro", [SECRETO_PLACEHOLDER, "", "corto-31-caracteres-xxxxxxxxxxx"])
@pytest.mark.parametrize("campo", ["kairos", "jwt"])
def test_fuera_de_local_un_secreto_inseguro_impide_arrancar(campo, inseguro):
    kairos, jwt = (inseguro, SECRETO_BUENO_B) if campo == "kairos" else (SECRETO_BUENO_A, inseguro)
    with pytest.raises(RuntimeError) as exc:
        validar_secretos_arranque(_cfg("docker", kairos, jwt))
    nombre = "KAIROS_AUTH_SECRET" if campo == "kairos" else "WEB_JWT_SECRET"
    assert nombre in str(exc.value)


def test_el_error_nunca_incluye_el_valor_del_secreto():
    secreto_corto = "valor-secreto-visible"
    with pytest.raises(RuntimeError) as exc:
        validar_secretos_arranque(_cfg("produccion", secreto_corto, SECRETO_BUENO_B))
    assert secreto_corto not in str(exc.value)


def test_en_local_solo_avisa_sin_valores(caplog):
    secreto_corto = "valor-secreto-visible"
    with caplog.at_level("WARNING", logger="laplace.config"):
        inseguros = validar_secretos_arranque(_cfg("local", secreto_corto, SECRETO_PLACEHOLDER))
    assert inseguros == ["KAIROS_AUTH_SECRET", "WEB_JWT_SECRET"]
    assert caplog.messages
    assert all(secreto_corto not in m and SECRETO_PLACEHOLDER not in m for m in caplog.messages)
