"""test_telegram_hoy.py — `/hoy` del bot: lista los partidos de hoy con cobertura propia. Sin APIs ni BD real."""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from backend.api.bot import laplace_bot
from backend.api.models.partidos import PartidoDia
from backend.api.services import pronosticables

HOY = datetime.now(laplace_bot.TZ_CHILE).strftime("%Y-%m-%d")


def _partido(match_id: str, liga: str, local: str, visitante: str, hora: str, status: str = "scheduled") -> PartidoDia:
    return PartidoDia(fecha=HOY, match_id=match_id, liga_nombre=liga, local=local, visitante=visitante, hora_chile=hora, status=status)


def _falso_validar(partido: dict) -> tuple[bool, str]:
    if partido["liga"] == "Sin Datos":
        return False, "liga_sin_historial"
    if partido["local"] == "Equipo Nuevo":
        return True, "equipo_sin_historial"
    return True, "ok"


def _ejecutar(monkeypatch, db_session) -> str:
    monkeypatch.setattr(pronosticables.modelo_historico, "validar_historico", _falso_validar)
    monkeypatch.setattr(laplace_bot, "SessionLocal", lambda: db_session)
    update = MagicMock()
    update.message.reply_html = AsyncMock()
    asyncio.run(laplace_bot.cmd_hoy(update, MagicMock()))
    return update.message.reply_html.call_args[0][0]


def test_hoy_lista_solo_programados_con_cobertura_y_marca_parciales(db_session, monkeypatch):
    db_session.add_all([
        _partido("1", "Premier League", "Arsenal", "Chelsea", "15:00"),
        _partido("2", "Premier League", "Equipo Nuevo", "Everton", "13:00"),
        _partido("3", "Premier League", "Fulham", "Wolves", "17:00", status="finished"),
        _partido("4", "Sin Datos", "Alfa", "Beta", "10:00"),
    ])
    db_session.commit()
    texto = _ejecutar(monkeypatch, db_session)
    assert "Arsenal vs Chelsea" in texto
    assert "~13:00 Equipo Nuevo vs Everton" in texto
    assert "15:00 Arsenal" in texto and "~15:00" not in texto
    assert "Fulham" not in texto and "Alfa" not in texto
    assert len(texto.splitlines()) <= 25


def test_hoy_sin_partidos_responde_mensaje_honesto(db_session, monkeypatch):
    texto = _ejecutar(monkeypatch, db_session)
    assert "Hoy no hay partidos que pueda pronosticar" in texto
    assert "/juegos" in texto


def test_hoy_escapa_html_de_los_nombres(db_session, monkeypatch):
    db_session.add(_partido("1", "Liga <Rara>", "Harland & Wolff", "Belfast <FC>", "12:00"))
    db_session.commit()
    texto = _ejecutar(monkeypatch, db_session)
    assert "Harland &amp; Wolff" in texto
    assert "Belfast &lt;FC&gt;" in texto
    assert "Liga &lt;Rara&gt;" in texto


def test_hoy_limita_a_20_partidos(db_session, monkeypatch):
    db_session.add_all([_partido(str(i), "Liga A", f"Local{i:02d}", f"Visita{i:02d}", f"{i % 24:02d}:00") for i in range(30)])
    db_session.commit()
    texto = _ejecutar(monkeypatch, db_session)
    assert texto.count(" vs ") == 20


def test_hoy_esta_en_la_ayuda():
    assert "/hoy" in laplace_bot.TEXTO_AYUDA
