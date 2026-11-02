"""Modelos de la API: estados, cuerpos de entrada y la tarea interna."""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Estado(str, Enum):
    PENDIENTE = 'pendiente'
    EJECUTANDO = 'ejecutando'
    COMPLETADA = 'completada'
    FALLIDA = 'fallida'
    CANCELADA = 'cancelada'


TERMINALES = {Estado.COMPLETADA, Estado.FALLIDA, Estado.CANCELADA}


# ---------------------------------------------------------------
# Cuerpos del POST: el campo 'tipo' decide qué modelo se valida
# ---------------------------------------------------------------

class Descargar(BaseModel):
    tipo: Literal['descargar']
    urls: list[str] = Field(min_length=1, max_length=100)
    timeout: float | None = Field(default=None, gt=0)


class Hashear(BaseModel):
    tipo: Literal['hashear']
    texto: str = Field(max_length=10_000)
    iteraciones: int = Field(ge=1, le=50_000_000)
    bloqueante: bool = False
    timeout: float | None = Field(default=None, gt=0)


class Esperar(BaseModel):
    tipo: Literal['esperar']
    segundos: float = Field(ge=0, le=3600)
    timeout: float | None = Field(default=None, gt=0)


TareaNueva = Annotated[Descargar | Hashear | Esperar, Field(discriminator='tipo')]


# ---------------------------------------------------------------
# Tarea interna: lo que guarda el registro
# ---------------------------------------------------------------

@dataclass
class Tarea:
    tipo: str
    parametros: dict
    timeout: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    estado: Estado = Estado.PENDIENTE
    creada: float = field(default_factory=time.time)
    iniciada: float | None = None
    terminada: float | None = None
    resultado: Any = None
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)

    def a_dict(self) -> dict:
        """Versión serializable a JSON (sin la asyncio.Task)."""
        duracion = None
        if self.iniciada is not None and self.terminada is not None:
            duracion = self.terminada - self.iniciada
        return {
            'id': self.id,
            'tipo': self.tipo,
            'parametros': self.parametros,
            'timeout': self.timeout,
            'estado': self.estado.value,
            'creada': self.creada,
            'iniciada': self.iniciada,
            'terminada': self.terminada,
            'duracion': duracion,
            'resultado': self.resultado,
            'error': self.error,
        }
