from datetime import datetime, timedelta, timezone

from backend.api.core.tiempo import utc_ahora


def test_utc_ahora_es_ingenuo():
    assert utc_ahora().tzinfo is None


def test_utc_ahora_esta_en_utc():
    referencia = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs(utc_ahora() - referencia) < timedelta(seconds=5)


def test_utc_ahora_difiere_del_local_solo_por_el_desfase():
    desfase = datetime.now().astimezone().utcoffset()
    diferencia = datetime.now() - utc_ahora()
    assert abs(diferencia - desfase) < timedelta(seconds=5)
