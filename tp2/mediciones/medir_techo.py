#!/usr/bin/env python3
"""Medición 3 de la consigna: el techo del pool.

(a) I/O: N tareas 'esperar' de 1 s enviadas a la vez. Con W workers, el ideal
    es ceil(N / W) segundos; los 503 aparecen cuando se llena la cola.
(b) CPU: N tareas 'hashear' a la vez. El tope es el mínimo entre workers,
    procesos del executor y núcleos reales.

Uso:
    python mediciones/medir_techo.py
    python mediciones/medir_techo.py --solo io
"""
import argparse
import asyncio
import os
import time

import httpx


async def post(cliente, base, cuerpo):
    t0 = time.perf_counter()
    r = await cliente.post(f'{base}/tareas', json=cuerpo)
    return r.status_code, time.perf_counter() - t0


async def esperar_vacio(cliente, base):
    """Hasta que no quede nada pendiente ni ejecutando (las rondas anteriores ya terminaron)."""
    while True:
        e = (await cliente.get(f'{base}/estadisticas')).json()['por_estado']
        if e['pendiente'] == 0 and e['ejecutando'] == 0:
            return
        await asyncio.sleep(0.05)


async def ronda(cliente, base, n, cuerpo):
    t0 = time.perf_counter()
    respuestas = await asyncio.gather(*(post(cliente, base, cuerpo) for _ in range(n)))
    await esperar_vacio(cliente, base)
    total = time.perf_counter() - t0
    ok = sum(codigo == 202 for codigo, _ in respuestas)
    peor = max(latencia for _, latencia in respuestas) * 1000
    return total, ok, n - ok, peor


async def main(args):
    async with httpx.AsyncClient(timeout=600, limits=httpx.Limits(max_connections=100)) as cliente:
        workers = (await cliente.get(f'{args.base}/estadisticas')).json()['workers_total']
        print(f'os.cpu_count()={os.cpu_count()}  workers_total={workers}  '
              f'PROCESOS (env)={os.environ.get("PROCESOS", "?")}  TAMANO_COLA (env)={os.environ.get("TAMANO_COLA", "?")}\n')

        if args.solo in (None, 'io'):
            print('(a) I/O: N x esperar(1 s)\n')
            print('| N | total (s) | ideal ceil(N/W) (s) | tareas/s | peor POST (ms) | aceptadas | 503 |')
            print('|---|---|---|---|---|---|---|')
            for n in (10, 50, 100, 500, 1000, 2000):
                total, ok, fallas, peor = await ronda(cliente, args.base, n, {'tipo': 'esperar', 'segundos': 1})
                print(f'| {n} | {total:.2f} | {-(-ok // workers)} | {ok / total:.1f} | {peor:.0f} | {ok} | {fallas} |')

        if args.solo in (None, 'cpu'):
            print('\n(b) CPU: N x hashear(3_000_000)\n')
            print('| N | total (s) | aceptadas | 503 |')
            print('|---|---|---|---|')
            cuerpo = {'tipo': 'hashear', 'texto': 'x', 'iteraciones': 3_000_000}
            for n in (1, 2, 4, 8):
                total, ok, fallas, _ = await ronda(cliente, args.base, n, cuerpo)
                print(f'| {n} | {total:.2f} | {ok} | {fallas} |')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://localhost:8000')
    p.add_argument('--solo', choices=['io', 'cpu'])
    asyncio.run(main(p.parse_args()))
