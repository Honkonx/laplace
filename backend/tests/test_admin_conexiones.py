"""Panel «Conexiones» (routers/admin.py): listar, probar, guardar, borrar y ordenar la IA, sin exponer jamás una clave."""
from __future__ import annotations

import pytest

from backend.api.core import conexiones as cx
from backend.api.core.config import settings
from backend.api.db.session import get_db
from backend.tests.test_admin import _token_admin, _token_no_admin, client  # noqa: F401  (fixtures y ayudantes de test_admin)

CLAVE = "clave-de-prueba-super-secreta-123456"
BASE = "/api/v1/admin"


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    """`.env` temporal (el panel nunca debe tocar el real) y las claves de este proceso restauradas al terminar."""
    (tmp_path / ".env").write_text("KAIROS_AUTH_SECRET=" + "k" * 40 + "\nBSD_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(type(settings), "repo_root", property(lambda self: tmp_path))
    for variable in ("BSD_API_KEY", "GROQ_API_KEY", "LIVESCORE6_KEY", "OLLAMA_API_KEY", "THE_ODDS_API_KEY", "ODDSPAPI_KEY", "AI_ROUTING_BOT", "AI_ROUTING_CANAL",
                     "AI_ROUTING_AGENTE", "AI_ROUTING_LABORATORIO"):
        monkeypatch.setattr(settings, variable, "")
    return tmp_path


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _acciones(client):
    from backend.api.models.auditoria import AccionAdminAuditoria
    db = client.app.dependency_overrides[get_db]().__next__()
    try:
        return [(a.accion, a.detalle) for a in db.query(AccionAdminAuditoria).all()]
    finally:
        db.close()


def test_solo_un_administrador_ve_las_conexiones(client, entorno):
    assert client.get(f"{BASE}/conexiones").status_code in (401, 422)   # sin cabecera Authorization FastAPI da 422 (comportamiento ya documentado en test_admin.py)
    assert client.get(f"{BASE}/conexiones", headers=_auth("token-invalido")).status_code == 401
    assert client.get(f"{BASE}/conexiones", headers=_auth(_token_no_admin(client))).status_code == 403


def test_listar_devuelve_las_13_conexiones_con_su_estado_y_nunca_una_clave(client, entorno, monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", CLAVE)
    r = client.get(f"{BASE}/conexiones", headers=_auth(_token_admin(client)))
    assert r.status_code == 200
    cuerpo = r.json()
    assert len(cuerpo["conexiones"]) == 13 and [g["id"] for g in cuerpo["grupos"]] == [g.id for g in cx.GRUPOS]
    por_id = {c["id"]: c for c in cuerpo["conexiones"]}
    assert por_id["groq"]["configurada"] is True and por_id["bsd"]["configurada"] is False
    assert por_id["livescore6"]["cobra_por_llamada"] is True and por_id["ollama_cloud"]["cuesta"] == "≈ 1 token"
    assert any("cuotas" in f for f in cuerpo["faltantes"]) and cuerpo["orden_ia"][0] == "ollama_cloud"
    assert CLAVE not in r.text


def test_guardar_una_clave_valida_la_prueba_antes_la_escribe_y_audita_sin_el_valor(client, entorno, monkeypatch):
    llamadas = []
    monkeypatch.setattr(cx, "probar", lambda c, k, **_: llamadas.append((c.id, k)) or cx.Resultado(cx.ESTADO_OK, "válida", 200))
    r = client.post(f"{BASE}/conexiones/bsd", json={"clave": CLAVE}, headers=_auth(_token_admin(client)))
    assert r.status_code == 200 and r.json()["estado"] == "ok" and r.json()["restart_required"] is True
    assert CLAVE not in r.text
    assert llamadas == [("bsd", CLAVE)]
    texto = (entorno / ".env").read_text(encoding="utf-8")
    assert f"BSD_API_KEY={CLAVE}" in texto and "KAIROS_AUTH_SECRET=" + "k" * 40 in texto   # conserva el resto del archivo
    assert settings.BSD_API_KEY == CLAVE                                                    # este proceso ya la usa
    assert ("conexion_configurada", "bsd") in _acciones(client) and all(CLAVE not in (d or "") for _, d in _acciones(client))


def test_una_clave_rechazada_por_el_proveedor_no_se_guarda_y_la_anterior_sigue(client, entorno, monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", "clave-anterior-1234567")
    monkeypatch.setattr(cx, "probar", lambda c, k, **_: cx.Resultado(cx.ESTADO_FALLA, "clave inválida (HTTP 401)", 401))
    r = client.post(f"{BASE}/conexiones/bsd", json={"clave": CLAVE}, headers=_auth(_token_admin(client)))
    assert r.status_code == 422 and "No se guardó nada" in r.json()["detail"] and CLAVE not in r.text
    assert "BSD_API_KEY=\n" in (entorno / ".env").read_text(encoding="utf-8") + "\n" and settings.BSD_API_KEY == "clave-anterior-1234567"


def test_un_formato_imposible_se_rechaza_sin_llamar_al_proveedor(client, entorno, monkeypatch):
    monkeypatch.setattr(cx, "probar", lambda *a, **k: pytest.fail("no debe probar"))
    r = client.post(f"{BASE}/conexiones/bsd", json={"clave": "con espacios y no sirve 123"}, headers=_auth(_token_admin(client)))
    assert r.status_code == 422 and "con espacios" not in (entorno / ".env").read_text(encoding="utf-8")


def test_una_conexion_desconocida_es_404(client, entorno):
    cabeceras = _auth(_token_admin(client))
    assert client.post(f"{BASE}/conexiones/no-existe", json={"clave": CLAVE}, headers=cabeceras).status_code == 404
    assert client.delete(f"{BASE}/conexiones/no-existe", headers=cabeceras).status_code == 404
    assert client.post(f"{BASE}/conexiones/no-existe/probar", headers=cabeceras).status_code == 404


def test_las_pruebas_con_coste_piden_confirmacion(client, entorno, monkeypatch):
    monkeypatch.setattr(settings, "LIVESCORE6_KEY", CLAVE)
    monkeypatch.setattr(cx, "probar", lambda *a, **k: pytest.fail("no debe probar sin confirmar"))
    cabeceras = _auth(_token_admin(client))
    r = client.post(f"{BASE}/conexiones/livescore6/probar", headers=cabeceras)
    assert r.json()["requiere_confirmacion"] is True and "cuesta" in r.json()["detalle"]
    monkeypatch.setattr(cx, "probar", lambda c, k, **_: cx.Resultado(cx.ESTADO_OK, "válida", 200))
    r2 = client.post(f"{BASE}/conexiones/livescore6/probar?confirmar_coste=true", headers=cabeceras)
    assert r2.json()["estado"] == "ok" and CLAVE not in r2.text


def test_guardar_una_clave_con_coste_sin_confirmar_se_guarda_sin_probar(client, entorno, monkeypatch):
    monkeypatch.setattr(cx, "probar", lambda *a, **k: pytest.fail("no debe probar sin confirmar"))
    r = client.post(f"{BASE}/conexiones/livescore6", json={"clave": CLAVE}, headers=_auth(_token_admin(client)))
    assert r.status_code == 200 and r.json()["detalle"] == "guardada sin probar"
    assert f"LIVESCORE6_KEY={CLAVE}" in (entorno / ".env").read_text(encoding="utf-8")


def test_probar_sin_clave_guardada_es_un_400(client, entorno):
    assert client.post(f"{BASE}/conexiones/bsd/probar", headers=_auth(_token_admin(client))).status_code == 400


def test_borrar_una_clave_la_vacia_en_env_y_en_el_proceso(client, entorno, monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", CLAVE)
    (entorno / ".env").write_text(f"BSD_API_KEY={CLAVE}\n", encoding="utf-8")
    r = client.delete(f"{BASE}/conexiones/bsd", headers=_auth(_token_admin(client)))
    assert r.status_code == 200 and r.json()["configurada"] is False and CLAVE not in r.text
    assert CLAVE not in (entorno / ".env").read_text(encoding="utf-8") and settings.BSD_API_KEY == ""
    assert ("conexion_borrada", "bsd") in _acciones(client)


def test_cambiar_el_orden_de_la_ia_escribe_los_cuatro_roles_y_rechaza_ids_raros(client, entorno):
    cabeceras = _auth(_token_admin(client))
    r = client.put(f"{BASE}/conexiones-orden-ia", json={"orden": ["gemini", "ollama_cloud", "groq"]}, headers=cabeceras)
    assert r.status_code == 200
    texto = (entorno / ".env").read_text(encoding="utf-8")
    assert all(f"{rol}=gemini,ollama_cloud,groq" in texto for rol in cx.ROLES_IA)
    assert settings.AI_ROUTING_AGENTE == "gemini,ollama_cloud,groq"
    for malo in (["gemini", "gemini"], ["no-existe"], ["groq", "claude; rm -rf"]):
        assert client.put(f"{BASE}/conexiones-orden-ia", json={"orden": malo}, headers=cabeceras).status_code == 422
    assert ("orden_ia_cambiado", "gemini,ollama_cloud,groq") in _acciones(client)


def test_el_panel_de_fuentes_y_el_de_ia_siguen_leyendo_del_registro(client, entorno, monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", CLAVE)
    cabeceras = _auth(_token_admin(client))
    fuentes = client.get(f"{BASE}/sports/fuentes", headers=cabeceras).json()["sources"]
    assert [f["id"] for f in fuentes] == ["livescore6", "api-football", "football-data", "the-odds-api", "bsd", "oddspapi"]
    assert fuentes[3]["role"] == cx.por_id("the-odds-api").rol_panel
    ia = client.get(f"{BASE}/ia/proveedores", headers=cabeceras).json()["proveedores"]
    assert [p["id"] for p in ia] == ["groq", "gemini", "openrouter", "ollama_cloud", "claude"]
    assert next(p for p in ia if p["id"] == "groq")["configurado"] is True and CLAVE not in client.get(f"{BASE}/ia/proveedores", headers=cabeceras).text
