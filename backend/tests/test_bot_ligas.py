"""test_bot_ligas.py — filtro/prioridad de ligas del menú de /juegos (port de wfa-022)."""
from __future__ import annotations

from backend.api.bot.ligas import ligas_con_partidos, slug_liga


def test_excluye_ligas_amateur_y_prioriza_top():
    stages = [
        {"Snm": "Premier League", "Events": [{"Eps": "NS"}, {"Eps": "NS"}]},
        {"Snm": "Ligue 1 Senegal", "Events": [{"Eps": "NS"}]},
        {"Snm": "Serie B", "Events": [{"Eps": "NS"}]},
    ]
    ligas = ligas_con_partidos(stages)
    nombres = [l["nombre"] for l in ligas]
    assert "Ligue 1 Senegal" not in nombres
    assert nombres[0] == "Premier League"


def test_sin_prioritarias_muestra_el_resto():
    stages = [{"Snm": "Torneo Regional X", "Events": [{"Eps": "NS"}]}]
    ligas = ligas_con_partidos(stages)
    assert len(ligas) == 1


def test_slug_liga_normaliza():
    assert slug_liga("Premier League") == "premier-league"


def test_las_ligas_con_partidos_pronosticables_van_primero_y_los_conteos_se_suman(monkeypatch):
    """Auditoría 2026-10-09: 'Ligue 1' de Argelia y de Francia compartían entrada y el menú ofrecía la de Argelia
    (sin cobertura). Ahora se suma por nombre, se cuentan los partidos con modelo histórico y esos van primero."""
    from backend.api.bot import ligas as modulo

    monkeypatch.setattr(modulo, "_evento_cubierto", lambda stage, ev: stage.get("Cnm") == "Francia")
    stages = [
        {"Snm": "Ligue 1", "Cnm": "Argelia", "Events": [{"Eps": "NS"}, {"Eps": "NS"}, {"Eps": "NS"}]},
        {"Snm": "Ligue 1", "Cnm": "Francia", "Events": [{"Eps": "NS"}]},
        {"Snm": "Eredivisie", "Cnm": "Países Bajos", "Events": [{"Eps": "NS"}]},
    ]
    ligas = modulo.ligas_con_partidos(stages)
    assert ligas[0]["nombre"] == "Ligue 1" and ligas[0]["partidos"] == 4 and ligas[0]["cubiertos"] == 1
    assert ligas[0]["paises"] == ["Argelia", "Francia"]
