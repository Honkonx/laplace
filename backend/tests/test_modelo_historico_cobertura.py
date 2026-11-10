"""test_modelo_historico_cobertura.py — resolución robusta de liga y equipos del módulo `historico`.

Artefacto sintético con nombres tal como los escribe football-data (abreviados, sin sufijos) y
consultas tal como las escriben LiveScore6/API-Football. Lo central: cubrir variantes reales sin
generar falsos positivos (si no hay certeza, "fuera de cobertura").
"""
from __future__ import annotations

import json

import pytest

from backend.api.ml import dixon_coles
from backend.api.services import modelo_historico as mh

# Estas pruebas usan los alias de equipos construidos con datos históricos propios (no se publican): sin ellos se omiten.
pytestmark = pytest.mark.skipif(
    not mh.RUTA_ALIAS.exists(),
    reason="falta el alias de equipos (se genera con datos históricos propios)",
)

EQUIPOS = {
    "E0": ["Man City", "Man United", "Chelsea", "Tottenham", "Sheffield United"],
    "E1": ["Cardiff", "Derby", "Birmingham", "Blackburn", "Sheffield Weds", "Sheffield United",
           "Bristol City", "Bristol Rvs", "Peterboro"],
    "E2": ["Stockport", "Exeter", "Burton", "Accrington", "Cambridge", "Mansfield"],
    "SP1": ["Real Madrid", "Real Sociedad", "Atletico Madrid", "Barcelona", "Alaves"],
    "SP2": ["Sociedad B", "Barcelona B", "Ceuta", "Celta B"],
    "I1": ["Inter", "AC Milan", "Juventus"],
    "ARG": ["Estudiantes L.P.", "Gimnasia Mendoza", "Gimnasia L.P.", "Dep. Riestra", "Central Cordoba",
            "Boca Juniors", "River Plate", "Racing Club", "Ind. Rivadavia", "Independiente"],
    "MEX": ["UNAM Pumas", "Tigres UANL", "Club America", "Club Leon", "Guadalajara Chivas"],
    "USA": ["Inter Miami", "LA Galaxy", "Seattle Sounders"],
    "BRA": ["Atletico-MG", "Flamengo RJ", "Palmeiras"],
    "COL1": ["Millonarios", "Atletico Nacional", "Junior"],
    "SAU1": ["Al-Hilal", "Al-Nassr", "Al-Ittihad"],
}


def _modelo(equipos: list[str]) -> dict:
    return dixon_coles.ModeloLiga(
        mu=0.1, gamma=0.25, rho=-0.1, n_partidos=500,
        ataque={e: 0.1 * i - 0.2 for i, e in enumerate(equipos)},
        defensa={e: 0.05 * i - 0.1 for i, e in enumerate(equipos)},
    ).a_dict()


@pytest.fixture()
def artefactos(tmp_path, monkeypatch):
    (tmp_path / "dixon_coles_ligas.json").write_text(
        json.dumps({"version": "cobertura", "ligas": {c: _modelo(e) for c, e in EQUIPOS.items()}}), encoding="utf-8")
    monkeypatch.setattr(mh, "DIR_ARTEFACTOS", tmp_path)
    mh._artefactos.cache_clear()
    yield tmp_path
    mh._artefactos.cache_clear()


def _cod(liga: str, local: str, visitante: str, **extra) -> str | None:
    r = mh._resolver({"liga": liga, "local": local, "visitante": visitante, **extra})
    return r[0]


def _equipo(codigo: str, nombre: str) -> str | None:
    return mh._resolver_equipo(mh._artefactos(), codigo, nombre)


# --- Liga -------------------------------------------------------------------------------------


@pytest.mark.parametrize("liga, local, visitante, esperado", [
    ("Liga Profesional Argentina", "Boca Juniors", "River Plate", "ARG"),
    ("Liga Profesional: Clausura", "Boca Juniors", "River Plate", "ARG"),
    ("Primera División: Clausura", "Boca Juniors", "River Plate", "ARG"),
    ("Primera A: Clausura", "Millonarios", "Junior", "COL1"),
    ("Saudi Professional League", "Al Hilal", "Al Nassr", "SAU1"),
    ("Liga MX: Apertura", "Pumas", "Tigres", "MEX"),
    ("Major League Soccer", "Inter Miami CF", "Los Angeles Galaxy", "USA"),
    ("MLS", "Inter Miami CF", "Seattle Sounders FC", "USA"),
    ("Serie A (Brazil)", "Flamengo", "Palmeiras", "BRA"),
    ("Serie A: Regular Season", "Inter Milan", "Juventus", "I1"),
    ("English Premier League", "Man City", "Chelsea", "E0"),
    ("Championship", "Cardiff City", "Derby County", "E1"),
    ("League One", "Stockport County", "Exeter City", "E2"),
])
def test_liga_resuelta_por_patron_o_sufijo_de_fase(artefactos, liga, local, visitante, esperado):
    assert _cod(liga, local, visitante) == esperado


def test_liga_id_de_api_football_tiene_prioridad_sobre_el_nombre(artefactos):
    assert _cod("Torneo sin nombre conocido", "Boca Juniors", "River Plate", liga_id=128) == "ARG"
    assert _cod("Liga X", "Boca Juniors", "River Plate", liga_id="128") == "ARG"
    # id conocido de otra liga: no se prueba con el nombre ni con otras ligas
    assert _cod("Liga Profesional Argentina", "Boca Juniors", "River Plate", liga_id=39) is None
    # id desconocido: cae al nombre
    assert _cod("Liga Profesional Argentina", "Boca Juniors", "River Plate", liga_id=999999) == "ARG"


def test_pais_desambigua_nombres_genericos(artefactos):
    assert mh.ligas_candidatas({"liga": "Primera Division", "pais": "Argentina"}) == ["ARG"]
    assert mh.ligas_candidatas({"liga": "Primera Division", "pais": "España"}) == ["SP1"]
    assert mh.ligas_candidatas({"liga": "Serie A", "pais": "Brasil"}) == ["BRA"]
    # sin país, el nombre genérico da varios candidatos y los equipos deciden
    assert set(mh.ligas_candidatas({"liga": "Primera Division"})) == {"SP1", "ARG"}
    assert _cod("Primera Division", "Boca Juniors", "River Plate") == "ARG"
    assert _cod("Primera Division", "Real Madrid", "Barcelona") == "SP1"


@pytest.mark.parametrize("liga", [
    "Liga MX Femenil", "Frauen-Bundesliga", "Premier League Women", "Championship U21",
    "Copa Argentina", "FA Trophy", "Friendlies", "MLS Next Pro",
])
def test_ligas_femeninas_juveniles_y_copas_nunca_resuelven(artefactos, liga):
    assert mh.ligas_candidatas({"liga": liga}) == []


def test_liga_inexistente_o_vacia_no_inventa(artefactos):
    assert mh.ligas_candidatas({"liga": ""}) == []
    assert mh.ligas_candidatas({}) == []
    assert _cod("Liga Inventada", "Boca Juniors", "River Plate") is None


def test_ligas_declaradas_pero_sin_modelo_se_ignoran(artefactos):
    # CHL1/URY1 están en ligas_alias.json pero no en este artefacto: no rompe, no participa.
    assert mh.ligas_candidatas({"liga": "Primera División", "pais": "Chile"}) == []


# --- Equipos ----------------------------------------------------------------------------------


@pytest.mark.parametrize("codigo, consulta, esperado", [
    ("E1", "Cardiff City", "Cardiff"),
    ("E1", "Derby County", "Derby"),
    ("E1", "Birmingham City", "Birmingham"),
    ("E1", "Blackburn Rovers", "Blackburn"),
    ("E1", "Sheffield Wednesday", "Sheffield Weds"),
    ("E1", "Bristol Rovers", "Bristol Rvs"),
    ("E1", "Peterborough United", "Peterboro"),
    ("E2", "Stockport County", "Stockport"),
    ("E2", "Exeter City", "Exeter"),
    ("E2", "Burton Albion", "Burton"),
    ("E2", "Accrington ST", "Accrington"),
    ("E2", "Accrington Stanley", "Accrington"),
    ("E2", "Cambridge United", "Cambridge"),
    ("E2", "Mansfield Town", "Mansfield"),
    ("E0", "Manchester United", "Man United"),
    ("E0", "Manchester City FC", "Man City"),
    ("ARG", "Estudiantes L.P.", "Estudiantes L.P."),
    ("ARG", "Estudiantes LP", "Estudiantes L.P."),
    ("ARG", "Deportivo Riestra", "Dep. Riestra"),
    ("ARG", "Gimnasia M.", "Gimnasia Mendoza"),
    ("ARG", "Central Cordoba de Santiago", "Central Cordoba"),
    ("ARG", "Independiente Rivadavia", "Ind. Rivadavia"),
    ("MEX", "Pumas", "UNAM Pumas"),
    ("MEX", "CD Guadalajara", "Guadalajara Chivas"),
    ("MEX", "Leon", "Club Leon"),
    ("USA", "Los Angeles Galaxy", "LA Galaxy"),
    ("SP2", "AD Ceuta FC", "Ceuta"),
    ("SP2", "Real Sociedad II", "Sociedad B"),
    ("SP2", "Celta de Vigo II", "Celta B"),
    ("BRA", "Atletico Mineiro", "Atletico-MG"),
    ("SP1", "Deportivo Alaves", "Alaves"),
])
def test_variantes_reales_de_nombres_resuelven_al_equipo_del_historico(artefactos, codigo, consulta, esperado):
    assert _equipo(codigo, consulta) == esperado


@pytest.mark.parametrize("codigo, consulta", [
    ("SP1", "Real Betis"),                # no está en el modelo: no se adivina
    ("SP1", "Atletico Mineiro"),          # Atlético Madrid ≠ Atlético Mineiro
    ("SP1", "Real Sociedad B"),           # el filial no es el primer equipo
    ("SP2", "Real Sociedad"),             # y al revés
    ("SP2", "Barcelona"),                 # Barcelona (primer equipo) ≠ Barcelona B
    ("I1", "Inter Miami"),                # Inter ≠ Inter Miami
    ("USA", "Inter Milan"),
    ("E0", "Manchester Wanderers"),
    ("E0", "Chelsea Women"),              # marca de femenino
    ("E0", "Chelsea U21"),
    ("ARG", "Independiente del Valle"),   # equipo ecuatoriano ≠ Independiente
    ("E1", "Sheffield"),                  # Sheffield United y Sheffield Weds: empate = no resuelto
    ("E1", "Bristol"),                    # Bristol City y Bristol Rvs: empate = no resuelto
    ("E0", ""),
    ("E0", "FC"),
])
def test_pares_conflictivos_y_equipos_inexistentes_no_se_resuelven(artefactos, codigo, consulta):
    assert _equipo(codigo, consulta) is None


def test_united_y_city_siguen_siendo_equipos_distintos(artefactos):
    assert _equipo("E0", "Man United") == "Man United"
    assert _equipo("E0", "Man City") == "Man City"
    assert _equipo("E1", "Sheffield United") == "Sheffield United"
    assert _equipo("E1", "Sheffield Weds") == "Sheffield Weds"
    assert _equipo("E0", "Manchester") is None  # empate Man City / Man United


def test_partido_con_un_equipo_desconocido_o_repetido_no_cubre(artefactos):
    assert _cod("Championship", "Cardiff City", "Equipo Inventado FC") is None
    assert _cod("Championship", "Cardiff City", "Cardiff") is None  # el mismo equipo dos veces


def test_homonimos_entre_paises_se_frenan_con_el_pais_o_con_el_id(artefactos):
    # "Primera División" sin país es ambigua entre ligas del histórico: con país o id el resultado es seguro
    assert _cod("Primera División", "River Plate", "Boca Juniors", pais="Argentina") == "ARG"
    assert _cod("Primera División", "River Plate", "Boca Juniors", pais="Spain") is None
    assert _cod("Primera División", "River Plate", "Boca Juniors", liga_id=140) is None


# --- Caché y recarga en caliente ----------------------------------------------------------------


def test_resolucion_se_cachea_por_artefacto_y_se_invalida_al_recargar(artefactos):
    assert _equipo("E1", "Cardiff City") == "Cardiff"
    cache = mh._artefactos()["cache_equipos"]
    assert ("E1", "Cardiff City") in cache
    assert mh._artefactos()["cache_equipos"] is cache  # misma firma: misma caché
    (artefactos / "dixon_coles_ligas.json").write_text(
        json.dumps({"version": "v2", "ligas": {"E1": _modelo(["Cardiff", "Derby"])}}), encoding="utf-8")
    assert mh._artefactos()["version"] == "v2"
    assert mh._artefactos()["cache_equipos"] == {}
    assert _equipo("E1", "Cardiff City") == "Cardiff"


def test_alias_vivos_se_recargan_sin_reiniciar(artefactos, tmp_path, monkeypatch):
    ruta = tmp_path / "equipos_alias_vivo.json"
    ruta.write_text(json.dumps({"mapeo": {"*": {}}}), encoding="utf-8")
    monkeypatch.setattr(mh, "RUTA_ALIAS_EQUIPOS_VIVO", ruta)
    mh._artefactos.cache_clear()
    assert _equipo("E0", "Citizens") is None
    ruta.write_text(json.dumps({"mapeo": {"E0": {"Citizens": "Man City"}}}) + " ", encoding="utf-8")
    assert _equipo("E0", "Citizens") == "Man City"
    assert _equipo("E1", "Citizens") is None  # el alias de E0 no vale en otra liga


def test_tabla_de_ligas_declarativa_se_amplia_solo_con_datos(artefactos, tmp_path, monkeypatch):
    ruta = tmp_path / "ligas_alias.json"
    ruta.write_text(json.dumps({"ligas": [
        {"codigo": "COL1", "pais": "colombia", "nombres": ["liga de prueba"], "api_football_id": [777]},
    ]}), encoding="utf-8")
    monkeypatch.setattr(mh, "RUTA_ALIAS_LIGAS", ruta)
    mh._artefactos.cache_clear()
    assert _cod("Liga de Prueba: Clausura", "Millonarios", "Junior") == "COL1"
    assert _cod("Otra", "Millonarios", "Junior", liga_id=777) == "COL1"


def test_analizar_expone_liga_resuelta_con_nombres_de_fuentes_en_vivo(artefactos):
    r = mh.analizar({"liga": "Liga Profesional Argentina", "local": "Deportivo Riestra", "visitante": "Estudiantes L.P."})
    assert r["ok"] is True and r["liga_codigo"] == "ARG"


# --- Contra el artefacto real (se omite si no existe) --------------------------------------------


def test_leave_one_out_en_artefactos_reales_casi_no_confunde_equipos(monkeypatch):
    real = mh.Path(mh.__file__).resolve().parents[1] / "ml" / "artefactos"
    if not (real / "dixon_coles_ligas.json").exists():
        pytest.skip("sin artefactos reales")
    monkeypatch.setattr(mh, "DIR_ARTEFACTOS", real)
    mh._artefactos.cache_clear()
    art = mh._artefactos()
    total = confundidos = 0
    # Las copas continentales (CLI, CSU, UCL, UEL) no se usan como modelo por liga y mezclan
    # variantes de escritura del mismo club entre ediciones: no son una liga doméstica.
    copas = {"CLI", "CSU", "UCL", "UEL"}
    for codigo, modelo in art["ligas"].items():
        if codigo in copas:
            continue
        for equipo in modelo.ataque:
            sin = {**art, "alias": {},
                   "indices": {codigo: {k: v for k, v in art["indices"][codigo].items() if v != equipo}},
                   "estructura": {codigo: [(e, n) for e, n in art["estructura"][codigo] if e != equipo]}}
            total += 1
            if mh._buscar_equipo(sin, codigo, equipo):
                confundidos += 1
    mh._artefactos.cache_clear()
    # Medido 2026-10-07 sobre ligas domésticas (49 ligas): ~6/1.900 (Dundee/Dundee United, Santa Cruz/Real
    # Santa Cruz, Guangzhou City/FC: clubes realmente parecidos). Tope holgado, no exacto.
    assert confundidos / total < 0.01


def test_modelo_antiguo_baja_la_confianza_y_avisa(tmp_path, monkeypatch):
    import json
    from datetime import date

    from backend.api.ml import dixon_coles
    from backend.api.services import modelo_historico as mh

    def _artefacto(fecha_corte):
        modelo = dixon_coles.ModeloLiga(
            mu=0.15, gamma=0.28, rho=-0.05, n_partidos=900, fecha_corte=fecha_corte,
            ataque={"Manchester City": 0.9, "Sheffield Utd": -0.9}, defensa={"Manchester City": 0.8, "Sheffield Utd": -0.7})
        (tmp_path / "dixon_coles_ligas.json").write_text(
            json.dumps({"version": "t", "ligas": {"E0": modelo.a_dict()}}), encoding="utf-8")
        mh._artefactos.cache_clear()

    monkeypatch.setattr(mh, "DIR_ARTEFACTOS", tmp_path)
    d = {"liga": "Premier League", "local": "Manchester City", "visitante": "Sheffield Utd"}
    hoy = date.today().toordinal()
    _artefacto(hoy - 10)
    fresco = mh.analizar(d)
    _artefacto(hoy - 400)
    viejo = mh.analizar(d)
    _artefacto(hoy - 800)
    muy_viejo = mh.analizar(d)
    assert fresco["modelo_desactualizado"] is False and viejo["modelo_desactualizado"] is True
    assert fresco["confianza_score"] > viejo["confianza_score"] > muy_viejo["confianza_score"]
    assert muy_viejo["edad_modelo_dias"] == 800
    mh._artefactos.cache_clear()


def test_nombres_enormes_y_caches_acotados_no_agotan_recursos(monkeypatch):
    """Revisión de seguridad 2026-10-07: los nombres vienen del cliente (origen app); sin tope, un nombre de
    megabytes o millones de nombres distintos crecían la CPU/memoria sin límite."""
    import time

    from backend.api.services import modelo_historico as mh

    real = mh.Path(mh.__file__).resolve().parents[1] / "ml" / "artefactos"
    if not (real / "dixon_coles_ligas.json").exists():
        pytest.skip("sin artefactos reales")
    monkeypatch.setattr(mh, "DIR_ARTEFACTOS", real)
    mh._artefactos.cache_clear()
    art = mh._artefactos()
    gigante = "Manchester " * 200_000  # ~2 MB
    inicio = time.perf_counter()
    mh.validar_historico({"liga": gigante, "local": gigante, "visitante": gigante, "pais": gigante})
    assert time.perf_counter() - inicio < 2.0
    for i in range(mh._MAX_CACHE_LIGAS + 50):
        mh.ligas_candidatas({"liga": f"Liga inventada {i}"})
    assert len(art["cache_ligas"]) <= mh._MAX_CACHE_LIGAS
    assert len(art["cache_equipos"]) <= mh._MAX_CACHE_EQUIPOS
    mh._artefactos.cache_clear()


@pytest.fixture()
def artefactos_continentales(tmp_path, monkeypatch):
    equipos = {"UCL": ["Real Madrid", "Bayern Munich", "Fenerbahce", "Slavia Prague"], "E1": ["Cardiff City", "Derby County", "Leeds"],
               "E2": ["Stockport", "Exeter", "Burton"]}
    (tmp_path / "dixon_coles_ligas.json").write_text(
        json.dumps({"version": "cont", "ligas": {c: _modelo(e) for c, e in equipos.items()}}), encoding="utf-8")
    monkeypatch.setattr(mh, "DIR_ARTEFACTOS", tmp_path)
    mh._artefactos.cache_clear()
    yield
    mh._artefactos.cache_clear()


def test_competicion_continental_en_el_campo_pais_se_resuelve_por_su_nombre(artefactos_continentales):
    """LiveScore6 manda Cnm='Champions League' y Snm='League Stage' (2.237 partidos medidos el 2026-10-19: 16 sin cubrir)."""
    d = {"liga": "League Stage", "pais": "Champions League", "local": "Fenerbahçe", "visitante": "Slavia Prague"}
    assert mh.ligas_candidatas(d) == ["UCL"]
    assert mh.validar_historico(d)[0] is True


def test_un_pais_distinto_descarta_la_liga_homonima_inglesa(artefactos_continentales):
    # Irlanda del Norte y Escocia tienen su propia "Championship"/"League One": no son E1/E2.
    for pais, liga in (("Northern Ireland", "Championship"), ("Scotland", "League One"), ("China", "League One")):
        assert mh.ligas_candidatas({"liga": liga, "pais": pais, "local": "A", "visitante": "B"}) == [], (pais, liga)
    assert mh.ligas_candidatas({"liga": "Championship", "pais": "England", "local": "A", "visitante": "B"}) == ["E1"]
    assert mh.ligas_candidatas({"liga": "Championship", "local": "A", "visitante": "B"}) == ["E1"]  # sin país no se descarta
