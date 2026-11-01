"""API de tareas asíncronas (TP2).

Uso:
    python src/main.py
"""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

from modelos import TERMINALES, Estado, Tarea, TareaNueva

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('tp2')

WORKERS = int(os.environ.get('WORKERS', 4))
PROCESOS = int(os.environ.get('PROCESOS', 2))
TAMANO_COLA = int(os.environ.get('TAMANO_COLA', 1000))
TIMEOUT_DEFECTO = float(os.environ.get('TIMEOUT_DEFECTO', 60))
GRACIA_APAGADO = float(os.environ.get('GRACIA_APAGADO', 10))

# Provisorio: registro en memoria sin cola ni workers (se reemplaza en la fase siguiente).
tareas: dict[str, Tarea] = {}


@asynccontextmanager
async def ciclo(app):
    log.info('iniciando servidor')
    yield
    log.info('apagando servidor')


app = FastAPI(title='Tareas', description='TP2: cola de tareas asíncronas', lifespan=ciclo)


def _buscar(id: str) -> Tarea:
    t = tareas.get(id)
    if t is None:
        raise HTTPException(status_code=404, detail='tarea no encontrada')
    return t


@app.post('/tareas', status_code=202)
async def crear(nueva: TareaNueva):
    t = Tarea(
        tipo=nueva.tipo,
        parametros=nueva.model_dump(exclude={'tipo', 'timeout'}),
        timeout=nueva.timeout or TIMEOUT_DEFECTO,
    )
    tareas[t.id] = t
    return {'id': t.id, 'estado': t.estado.value}


@app.get('/tareas')
async def listar(estado: Estado | None = None):
    return [t.a_dict() for t in tareas.values() if estado is None or t.estado is estado]


@app.get('/tareas/{id}')
async def obtener(id: str):
    return _buscar(id).a_dict()


@app.delete('/tareas/{id}')
async def cancelar(id: str):
    t = _buscar(id)
    if t.estado in TERMINALES:
        raise HTTPException(status_code=409, detail='la tarea ya terminó')
    t.estado = Estado.CANCELADA
    t.terminada = time.time()
    return t.a_dict()


@app.get('/estadisticas')
async def estadisticas():
    return {
        'por_estado': {e.value: sum(t.estado is e for t in tareas.values()) for e in Estado},
        'total': len(tareas),
        'tiempo_promedio': None,
        'workers_ocupados': 0,
        'workers_total': WORKERS,
        'en_cola': 0,
    }


@app.get('/demo/lento', response_class=PlainTextResponse)
async def lento(segundos: float = Query(default=1.0, ge=0), bytes: int = Query(default=1000, ge=0)):
    """Destino local para las mediciones: no dependen de internet."""
    await asyncio.sleep(segundos)
    return 'x' * bytes


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
