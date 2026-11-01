"""Las funciones que hacen el trabajo de cada tipo de tarea."""
import asyncio
import hashlib
import time

import httpx


async def esperar(segundos: float) -> dict:
    await asyncio.sleep(segundos)
    return {'durmio': segundos}


def hashear(texto: str, iteraciones: int) -> str:
    """CPU pura. Está a nivel de módulo para que se pueda picklear hacia otro proceso."""
    h = texto.encode()
    for _ in range(iteraciones):
        h = hashlib.sha256(h).digest()
    return h.hex()


async def _bajar_una(cliente: httpx.AsyncClient, url: str) -> dict:
    t0 = time.perf_counter()
    try:
        r = await cliente.get(url)
    except (httpx.HTTPError, httpx.InvalidURL) as e:  # InvalidURL no hereda de HTTPError
        return {'url': url, 'error': f'{type(e).__name__}: {e}',
                'segundos': round(time.perf_counter() - t0, 3)}
    return {'url': url, 'estado': r.status_code, 'bytes': len(r.content),
            'segundos': round(time.perf_counter() - t0, 3)}


async def descargar(cliente: httpx.AsyncClient, urls: list[str]) -> list[dict]:
    return await asyncio.gather(*(_bajar_una(cliente, url) for url in urls))
