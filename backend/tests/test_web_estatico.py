"""web_estatico: la web compilada se sirve desde el backend sin romper la API (instalación portable sin Node)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api.web_estatico import directorio_web, montar_web


@pytest.fixture()
def cliente(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>laplace</html>", encoding="utf-8")
    (dist / "sw.js").write_text("// sw", encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secreto.txt").write_text("no debe salir", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/v1/algo")
    def algo():
        return {"ok": True}

    @app.get("/api/v1/falta")
    def falta():
        raise HTTPException(status_code=404, detail="partido no encontrado")

    @app.post("/api/v1/solo-post")
    def solo_post():
        return {"ok": True}

    assert montar_web(app, tmp_path) is True
    return TestClient(app)


def test_la_raiz_y_las_rutas_de_la_spa_devuelven_el_index_sin_cache(cliente):
    for ruta in ("/", "/historial", "/agente/chat"):
        r = cliente.get(ruta)
        assert r.status_code == 200 and "laplace" in r.text and r.headers["cache-control"] == "no-cache", ruta


def test_los_assets_con_hash_se_cachean_y_sw_js_nunca(cliente):
    assert "immutable" in cliente.get("/assets/app-abc123.js").headers["cache-control"]
    assert cliente.get("/sw.js").headers["cache-control"] == "no-cache"


def test_la_api_sigue_siendo_json_y_un_404_de_la_api_no_cae_en_el_index(cliente):
    assert cliente.get("/api/v1/algo").json() == {"ok": True}
    r = cliente.get("/api/v1/falta")
    assert r.status_code == 404 and r.json() == {"detail": "partido no encontrado"}
    assert cliente.get("/api/v1/no-existe").status_code == 404
    assert cliente.get("/api/v1/no-existe").headers["content-type"].startswith("application/json")
    assert cliente.post("/api/v1/ruta-inexistente").status_code == 404  # no se vuelve 405 por la web


def test_un_archivo_con_extension_que_no_existe_es_404_y_no_se_sale_de_dist(cliente):
    assert cliente.get("/assets/falta.js").status_code == 404
    assert cliente.get("/..%2Fsecreto.txt").status_code in (404, 200) and "no debe salir" not in cliente.get("/..%2Fsecreto.txt").text
    assert "no debe salir" not in cliente.get("/../secreto.txt").text


def test_sin_dist_no_se_monta_nada(tmp_path):
    app = FastAPI()
    assert directorio_web(tmp_path) is None
    assert montar_web(app, tmp_path) is False
    assert TestClient(app).get("/").status_code == 404
