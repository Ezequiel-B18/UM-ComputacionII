import json

import persistencia


def test_volcar_y_ultimo_volcado(tmp_path, monkeypatch):
    monkeypatch.setattr(persistencia, 'DIRECTORIO', tmp_path)
    assert persistencia.ultimo_volcado() is None
    ruta = persistencia.volcar([{'id': 'abc', 'estado': 'completada', 'texto': 'ñandú'}])
    assert persistencia.ultimo_volcado() == ruta
    datos = json.loads(ruta.read_text(encoding='utf-8'))
    assert datos['tareas'] == [{'id': 'abc', 'estado': 'completada', 'texto': 'ñandú'}]
    assert 'volcado' in datos
