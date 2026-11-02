"""Pruebas del Pool sin HTTP: cola, workers, cancelación, timeout y apagado."""
import asyncio
import hashlib

import httpx
import pytest

from modelos import TERMINALES, Estado, Tarea
from pool import Pool
from registro import Registro


async def esperar_estado(t: Tarea, estados, limite=5):
    """Sondea hasta que la tarea llega a alguno de los estados (o falla por tiempo)."""
    async with asyncio.timeout(limite):
        while t.estado not in estados:
            await asyncio.sleep(0.01)


def esperar(segundos, timeout=60):
    return Tarea(tipo='esperar', parametros={'segundos': segundos}, timeout=timeout)


@pytest.fixture
async def pool():
    async with httpx.AsyncClient() as cliente:
        p = Pool(Registro(), workers=2, tamano_cola=10, procesos=1, cliente=cliente)
        p.iniciar()
        yield p
        await p.apagar(1)


async def test_esperar_completa(pool):
    t = esperar(0.05)
    pool.encolar(t)
    await esperar_estado(t, TERMINALES)
    assert t.estado is Estado.COMPLETADA
    assert t.resultado == {'durmio': 0.05}
    assert t.a_dict()['duracion'] >= 0.04  # reloj de pared contra el monotónico del sleep


async def test_timeout_falla(pool):
    t = esperar(10, timeout=0.1)
    pool.encolar(t)
    await esperar_estado(t, TERMINALES)
    assert t.estado is Estado.FALLIDA
    assert 'timeout' in t.error


async def test_cancelar_en_curso_y_el_worker_sobrevive(pool):
    t = esperar(10)
    pool.encolar(t)
    await esperar_estado(t, {Estado.EJECUTANDO})
    assert pool.cancelar(t)
    await esperar_estado(t, TERMINALES)
    assert t.estado is Estado.CANCELADA
    assert pool.ocupados == 0
    otra = esperar(0.01)
    pool.encolar(otra)
    await esperar_estado(otra, TERMINALES)
    assert otra.estado is Estado.COMPLETADA


async def test_cancelar_pendiente_nunca_corre(pool):
    largas = [esperar(10), esperar(10)]
    for t in largas:
        pool.encolar(t)
    for t in largas:
        await esperar_estado(t, {Estado.EJECUTANDO})
    t = esperar(0.01)
    pool.encolar(t)
    assert pool.cancelar(t)
    for larga in largas:
        pool.cancelar(larga)
    await asyncio.wait_for(pool.cola.join(), 5)  # el worker ya la sacó de la cola
    assert t.estado is Estado.CANCELADA
    assert t.iniciada is None


async def test_cancelar_terminada_devuelve_false(pool):
    t = esperar(0)
    pool.encolar(t)
    await esperar_estado(t, TERMINALES)
    assert pool.cancelar(t) is False


async def test_hashear_en_el_ejecutor(pool):
    t = Tarea(tipo='hashear', parametros={'texto': 'hola', 'iteraciones': 1000, 'bloqueante': False},
              timeout=30)
    pool.encolar(t)
    await esperar_estado(t, TERMINALES, limite=30)
    h = b'hola'
    for _ in range(1000):
        h = hashlib.sha256(h).digest()
    assert t.estado is Estado.COMPLETADA
    assert t.resultado == {'hash': h.hex(), 'iteraciones': 1000}


async def test_apagar_cancela_las_encoladas(pool):
    largas = [esperar(10), esperar(10)]
    for t in largas:
        pool.encolar(t)
    for t in largas:
        await esperar_estado(t, {Estado.EJECUTANDO})
    encolada = esperar(0.01)
    pool.encolar(encolada)
    await pool.apagar(0.1)
    assert encolada.estado is Estado.CANCELADA
    assert encolada.error == 'apagado del servidor'
    assert all(t.estado is Estado.CANCELADA for t in largas)
    assert all(t.error == 'apagado del servidor' for t in largas)  # estaban corriendo
    with pytest.raises(RuntimeError):
        pool.encolar(esperar(0))


async def test_cola_llena():
    async with httpx.AsyncClient() as cliente:
        p = Pool(Registro(), workers=0, tamano_cola=1, procesos=1, cliente=cliente)
        p.encolar(esperar(0))
        with pytest.raises(asyncio.QueueFull):
            p.encolar(esperar(0))
        await p.apagar(0)


async def test_descargar_resultado_parcial():
    """Una URL mala no tumba a las demás: cada una trae su propio resultado."""
    transporte = httpx.MockTransport(lambda pedido: httpx.Response(200, content=b'x' * 10))
    async with httpx.AsyncClient(transport=transporte) as cliente:
        p = Pool(Registro(), workers=1, tamano_cola=10, procesos=1, cliente=cliente)
        p.iniciar()
        # 'http://[::1' levanta httpx.InvalidURL, que no es HTTPError ('http://[mal' httpx lo acepta).
        t = Tarea(tipo='descargar', parametros={'urls': ['http://ok/', 'http://[::1']}, timeout=5)
        p.encolar(t)
        await esperar_estado(t, TERMINALES)
        await p.apagar(1)
    bueno, malo = t.resultado
    assert t.estado is Estado.COMPLETADA
    assert (bueno['estado'], bueno['bytes']) == (200, 10)
    assert 'error' in malo
