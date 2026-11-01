#!/usr/bin/env python3
"""Medición 2 de la consigna: el event loop bloqueado.

Mientras corre un hashear pesado, un sondeador pide GET /tareas cada 50 ms y
anota cuánto tarda cada respuesta (como el medidor de clase 21, pero del lado
del cliente). Con bloqueante=true el hash corre dentro del loop del servidor;
con bloqueante=false va al ProcessPoolExecutor.

Uso:
    python mediciones/medir_bloqueo.py
"""
import argparse
import asyncio
import statistics
import time

import httpx

ITERACIONES = 15_000_000
LATIDO = 0.05


async def sondeador(cliente, base, muestras, parar):
    while not parar.is_set():
        t0 = time.perf_counter()
        await cliente.get(f'{base}/tareas')
        muestras.append((time.perf_counter() - t0) * 1000)
        await asyncio.sleep(LATIDO)


async def medir(cliente, base, bloqueante):
    muestras = []
    parar = asyncio.Event()
    sonda = asyncio.create_task(sondeador(cliente, base, muestras, parar))
    await asyncio.sleep(0.2)                # que el sondeador arranque

    r = await cliente.post(f'{base}/tareas', json={
        'tipo': 'hashear', 'texto': 'x', 'iteraciones': ITERACIONES, 'bloqueante': bloqueante})
    id = r.json()['id']
    while (t := (await cliente.get(f'{base}/tareas/{id}')).json())['estado'] in ('pendiente', 'ejecutando'):
        await asyncio.sleep(0.1)

    parar.set()
    await sonda
    p95 = statistics.quantiles(muestras, n=20, method='inclusive')[18]  # 'exclusive' extrapola con pocas muestras
    print(f'| {bloqueante} | {t["estado"]} | {t["duracion"]:.2f} | {len(muestras)} '
          f'| {statistics.mean(muestras):.1f} | {p95:.1f} | {max(muestras):.1f} |')


async def main(args):
    print(f'Latencia de GET /tareas mientras corre hashear de {ITERACIONES:_} iteraciones\n')
    print('| bloqueante | estado | duracion de la tarea (s) | sondeos | media (ms) | p95 (ms) | máx (ms) |')
    print('|---|---|---|---|---|---|---|')
    async with httpx.AsyncClient(timeout=120) as cliente:
        for bloqueante in (True, False):
            await medir(cliente, args.base, bloqueante)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://localhost:8000')
    asyncio.run(main(p.parse_args()))
