import json
import os
import time

from senales import ignorar_senales_en_hijo


def correr_exportador(snapshot, intervalo=30.0, directorio="exports"):
    # bonus: exportación periódica de snapshots (extensión #4 de la consigna).
    # Proceso independiente, igual patrón que los 7 analizadores -- solo que
    # en vez de leer /proc, vuelca lo que ya está en el snapshot compartido.
    ignorar_senales_en_hijo()
    os.makedirs(directorio, exist_ok=True)

    while True:
        time.sleep(intervalo)
        try:
            marca = int(time.time())
            ruta = f"{directorio}/export_{marca}.json"
            with open(ruta, "w") as f:
                json.dump(dict(snapshot), f, indent=2, default=str)
        except (ConnectionResetError, BrokenPipeError, EOFError, OSError):
            # el Manager murió -- probablemente hay un shutdown en curso,
            # no tiene sentido loguear un error acá
            return
