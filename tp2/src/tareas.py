"""Las funciones que hacen el trabajo de cada tipo de tarea."""
import asyncio


async def esperar(segundos: float) -> dict:
    await asyncio.sleep(segundos)
    return {'durmio': segundos}
