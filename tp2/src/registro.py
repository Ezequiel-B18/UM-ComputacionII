"""Registro en memoria de todas las tareas.

Sin locks: todo corre en el hilo del event loop, entre awaits.
"""
from modelos import Estado, Tarea


class Registro:
    def __init__(self):
        self.tareas: dict[str, Tarea] = {}

    def agregar(self, t: Tarea):
        self.tareas[t.id] = t

    def obtener(self, id: str) -> Tarea | None:
        return self.tareas.get(id)

    def listar(self, estado: Estado | None = None) -> list[Tarea]:
        return [t for t in self.tareas.values() if estado is None or t.estado is estado]

    def estadisticas(self, ocupados: int, total_workers: int, en_cola: int) -> dict:
        duraciones = [t.terminada - t.iniciada for t in self.listar(Estado.COMPLETADA)]
        return {
            'por_estado': {e.value: len(self.listar(e)) for e in Estado},
            'total': len(self.tareas),
            'tiempo_promedio': sum(duraciones) / len(duraciones) if duraciones else None,
            'workers_ocupados': ocupados,
            'workers_total': total_workers,
            'en_cola': en_cola,
        }
