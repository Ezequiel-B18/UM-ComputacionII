"""Pruebas de punta a punta por HTTP, con el lifespan real (TestClient como context manager)."""
import time

import pytest
from fastapi.testclient import TestClient

import main
import persistencia


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(persistencia, 'DIRECTORIO', tmp_path)  # el volcado del apagado va al tmp
    with TestClient(main.app) as c:
        yield c


def test_id_inexistente_da_404(cliente):
    assert cliente.get('/tareas/noexiste').status_code == 404
    assert cliente.delete('/tareas/noexiste').status_code == 404


def test_cuerpo_invalido_da_422(cliente):
    r = cliente.post('/tareas', json={'tipo': 'esperar', 'segundos': -1})
    assert r.status_code == 422


def test_completar_y_cancelar_terminada_da_409(cliente):
    r = cliente.post('/tareas', json={'tipo': 'esperar', 'segundos': 0})
    assert r.status_code == 202
    id = r.json()['id']
    limite = time.monotonic() + 5
    while cliente.get(f'/tareas/{id}').json()['estado'] != 'completada':
        assert time.monotonic() < limite, 'la tarea no terminó a tiempo'
        time.sleep(0.01)
    assert cliente.delete(f'/tareas/{id}').status_code == 409
