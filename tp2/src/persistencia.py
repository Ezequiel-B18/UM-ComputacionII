"""Volcado del estado a JSON al apagar el servidor."""
import json
import os
from datetime import datetime
from pathlib import Path

DIRECTORIO = Path(os.environ.get('DIRECTORIO_DATOS', 'datos'))


def volcar(tareas: list[dict]) -> Path:
    DIRECTORIO.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now()
    ruta = DIRECTORIO / f'estado_{ahora:%Y%m%d_%H%M%S}.json'
    datos = {'volcado': ahora.isoformat(), 'tareas': tareas}
    # Escritura atómica: si el proceso muere a mitad, queda un .tmp y nunca un JSON cortado.
    tmp = ruta.with_name(ruta.name + '.tmp')
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, ruta)
    return ruta


def ultimo_volcado() -> Path | None:
    # El nombre lleva la fecha en formato ordenable: el mayor es el más nuevo.
    return max(DIRECTORIO.glob('estado_*.json'), default=None)
