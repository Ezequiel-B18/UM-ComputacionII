"""Cola de tareas y pool de workers (patrón de clase 21, cola.py)."""
import asyncio
import logging
import time
from concurrent.futures import ProcessPoolExecutor

import httpx

import tareas
from modelos import TERMINALES, Estado, Tarea
from registro import Registro

log = logging.getLogger('tp2.pool')


class Pool:
    def __init__(self, registro: Registro, workers: int, tamano_cola: int, procesos: int,
                 cliente: httpx.AsyncClient):
        self.registro = registro
        self.n_workers = workers
        self.cliente = cliente
        self.cola = asyncio.Queue(maxsize=tamano_cola)
        self.ejecutor = ProcessPoolExecutor(max_workers=procesos)
        self.ocupados = 0
        self.aceptando = True
        self._workers = []

    def iniciar(self):
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(self.n_workers)]

    def encolar(self, t: Tarea):
        if not self.aceptando:
            raise RuntimeError('apagando')
        self.cola.put_nowait(t)  # QueueFull se propaga: main responde 503
        self.registro.agregar(t)

    async def _worker(self, wid: int):
        while True:
            t = await self.cola.get()
            try:
                if t.estado is Estado.CANCELADA:
                    continue  # la cancelaron mientras esperaba en la cola
                await self._correr(t)
            except Exception:  # último recurso: un worker nunca debe morir
                log.exception('worker %d: error inesperado con la tarea %s', wid, t.id)
                if t.estado not in TERMINALES:
                    t.estado = Estado.FALLIDA
            finally:
                self.cola.task_done()

    async def _correr(self, t: Tarea):
        t.estado = Estado.EJECUTANDO
        t.iniciada = time.time()
        self.ocupados += 1
        # La tarea interna es lo que cancela un DELETE; así el worker sobrevive.
        t.task = asyncio.create_task(self._ejecutar(t))
        try:
            t.resultado = await t.task
            t.estado = Estado.COMPLETADA
        except TimeoutError:
            t.estado = Estado.FALLIDA
            t.error = f'timeout: superó {t.timeout}s'
        except asyncio.CancelledError:
            t.estado = Estado.CANCELADA
            if asyncio.current_task().cancelling() > 0:
                t.error = 'apagado del servidor'
                raise  # cancelan al worker mismo: hay que propagarlo
            t.error = 'cancelada por el usuario'
        except Exception as e:
            t.estado = Estado.FALLIDA
            t.error = f'{type(e).__name__}: {e}'
        finally:
            t.terminada = time.time()
            self.ocupados -= 1
            t.task = None

    async def _ejecutar(self, t: Tarea):
        async with asyncio.timeout(t.timeout):
            if t.tipo == 'esperar':
                return await tareas.esperar(t.parametros['segundos'])
            raise ValueError(f'tipo no soportado todavía: {t.tipo}')

    def cancelar(self, t: Tarea) -> bool:
        if t.estado is Estado.PENDIENTE:
            t.estado = Estado.CANCELADA  # el worker la descarta al sacarla de la cola
            t.terminada = time.time()
            return True
        if t.estado is Estado.EJECUTANDO:
            t.task.cancel()
            return True
        return False

    async def apagar(self, gracia: float):
        self.aceptando = False
        for t in self.registro.listar(Estado.PENDIENTE):
            t.estado = Estado.CANCELADA
            t.terminada = time.time()
            t.error = 'apagado del servidor'
        en_curso = [t.task for t in self.registro.listar(Estado.EJECUTANDO) if t.task]
        if en_curso:
            log.info('esperando hasta %ss a %d tareas en curso', gracia, len(en_curso))
            await asyncio.wait(en_curso, timeout=gracia)
        for t in self.registro.listar(Estado.EJECUTANDO):
            if t.task:
                t.task.cancel()
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self.ejecutor.shutdown(wait=False, cancel_futures=True)
