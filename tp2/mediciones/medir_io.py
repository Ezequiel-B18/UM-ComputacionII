#!/usr/bin/env python3
"""Medición 1 de la consigna: concurrencia I/O.

Compara 20 descargas hechas una tras otra (un for con await, del lado del
cliente) contra las mismas 20 dentro de UNA tarea 'descargar' del servidor,
que las lanza todas juntas con asyncio.gather.

Uso:
    python mediciones/medir_io.py
    python mediciones/medir_io.py --externa https://www.python.org/
"""
import argparse
import asyncio
import time

import httpx

N = 20


async def esperar_fin(cliente, base, id):
    while True:
        t = (await cliente.get(f'{base}/tareas/{id}')).json()
        if t['estado'] in ('completada', 'fallida', 'cancelada'):
            return t
        await asyncio.sleep(0.05)


async def medir(cliente, base, url):
    t0 = time.perf_counter()
    for _ in range(N):
        await cliente.get(url)              # una por vez: cada await espera la anterior
    secuencial = time.perf_counter() - t0

    t0 = time.perf_counter()
    r = await cliente.post(f'{base}/tareas', json={'tipo': 'descargar', 'urls': [url] * N})
    t = await esperar_fin(cliente, base, r.json()['id'])
    concurrente = time.perf_counter() - t0

    errores = sum('error' in x for x in t['resultado'] or [])
    print(f'| {url} | {secuencial:.2f} | {concurrente:.2f} | {t["duracion"]:.2f} '
          f'| {secuencial / concurrente:.1f}x | {t["estado"]}, {errores} errores |')


async def main(args):
    print(f'{N} descargas: secuenciales contra concurrentes\n')
    print('| URL | secuencial (s) | concurrente, reloj (s) | concurrente, duracion de la tarea (s) | speedup | tarea |')
    print('|---|---|---|---|---|---|')
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as cliente:
        await medir(cliente, args.base, f'{args.base}/demo/lento?segundos=0.5')
        if args.externa:
            await medir(cliente, args.base, args.externa)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://localhost:8000')
    p.add_argument('--externa', help='repetir con una URL real de internet')
    asyncio.run(main(p.parse_args()))
