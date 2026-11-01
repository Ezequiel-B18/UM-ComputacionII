"""API de tareas asíncronas (TP2).

Uso:
    python src/main.py
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from modelos import TERMINALES, Estado, Tarea, TareaNueva
from persistencia import ultimo_volcado, volcar
from pool import Pool
from registro import Registro

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('tp2')

WORKERS = int(os.environ.get('WORKERS', 4))
PROCESOS = int(os.environ.get('PROCESOS', 2))
TAMANO_COLA = int(os.environ.get('TAMANO_COLA', 1000))
TIMEOUT_DEFECTO = float(os.environ.get('TIMEOUT_DEFECTO', 60))
GRACIA_APAGADO = float(os.environ.get('GRACIA_APAGADO', 10))


@asynccontextmanager
async def ciclo(app):
    previo = ultimo_volcado()
    if previo:
        try:
            n = len(json.loads(previo.read_text(encoding='utf-8'))['tareas'])
            log.info('volcado previo encontrado: %s (%d tareas)', previo, n)
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning('volcado previo ilegible: %s (%s)', previo, e)
    cliente = httpx.AsyncClient(timeout=30, follow_redirects=True)
    app.state.registro = Registro()
    app.state.pool = Pool(app.state.registro, WORKERS, TAMANO_COLA, PROCESOS, cliente)
    app.state.pool.iniciar()
    log.info('servidor listo: %d workers, %d procesos, cola de %d', WORKERS, PROCESOS, TAMANO_COLA)
    yield
    log.info('apagando: gracia de %ss para las tareas en curso', GRACIA_APAGADO)
    await app.state.pool.apagar(GRACIA_APAGADO)
    await cliente.aclose()
    ruta = volcar([t.a_dict() for t in app.state.registro.listar(None)])
    log.info('apagado completo; estado volcado en %s', ruta)


app = FastAPI(title='Tareas', description='TP2: cola de tareas asíncronas', lifespan=ciclo)


def _buscar(request: Request, id: str) -> Tarea:
    t = request.app.state.registro.obtener(id)
    if t is None:
        raise HTTPException(status_code=404, detail='tarea no encontrada')
    return t


@app.post('/tareas', status_code=202)
async def crear(nueva: TareaNueva, request: Request):
    t = Tarea(
        tipo=nueva.tipo,
        parametros=nueva.model_dump(exclude={'tipo', 'timeout'}),
        timeout=nueva.timeout or TIMEOUT_DEFECTO,
    )
    try:
        request.app.state.pool.encolar(t)
    except RuntimeError:
        raise HTTPException(status_code=503, detail='el servidor se está apagando')
    except asyncio.QueueFull:
        raise HTTPException(status_code=503, detail='cola llena')
    return {'id': t.id, 'estado': t.estado.value}


@app.get('/tareas')
async def listar(request: Request, estado: Estado | None = None):
    return [t.a_dict() for t in request.app.state.registro.listar(estado)]


@app.get('/tareas/{id}')
async def obtener(id: str, request: Request):
    return _buscar(request, id).a_dict()


@app.delete('/tareas/{id}')
async def cancelar(id: str, request: Request):
    """Si estaba ejecutando, la respuesta puede decir 'ejecutando' un instante:
    la cancelación se aplica cuando la tarea interna llega a su próximo await."""
    t = _buscar(request, id)
    if t.estado in TERMINALES:
        raise HTTPException(status_code=409, detail='la tarea ya terminó')
    request.app.state.pool.cancelar(t)
    return t.a_dict()


@app.get('/estadisticas')
async def estadisticas(request: Request):
    pool = request.app.state.pool
    return request.app.state.registro.estadisticas(pool.ocupados, WORKERS, pool.cola.qsize())


@app.get('/demo/lento', response_class=PlainTextResponse)
async def lento(segundos: float = Query(default=1.0, ge=0), bytes: int = Query(default=1000, ge=0)):
    """Destino local para las mediciones: no dependen de internet."""
    await asyncio.sleep(segundos)
    return 'x' * bytes


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
