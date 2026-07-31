import json
import multiprocessing as mp
import signal
import time

from recolector import correr_recolector
from analizadores.resumen import correr_resumen
from analizadores.memoria import correr_memoria
from analizadores.fds import correr_fds
from analizadores.threads import correr_threads
from analizadores.senales import correr_senales
from analizadores.scheduling import correr_scheduling
from analizadores.sistema import correr_sistema

ANALIZADORES = {
    "resumen": correr_resumen,
    "memoria": correr_memoria,
    "fds": correr_fds,
    "threads": correr_threads,
    "senales": correr_senales,
    "scheduling": correr_scheduling,
    "sistema": correr_sistema,
}


def cargar_config():
    with open("config.json", "r") as f:
        return json.load(f)


def main():
    config = cargar_config()

    manager = mp.Manager()
    snapshot = manager.dict()
    pids_compartidos = manager.list()

    intervalos = {
        nombre: mp.Value("d", config["intervalos"][nombre]["default"])
        for nombre in ANALIZADORES
    }

    procesos = [
        mp.Process(target=correr_recolector, args=(pids_compartidos, 1.0), daemon=True)
    ]
    for nombre, funcion in ANALIZADORES.items():
        p = mp.Process(
            target=funcion,
            args=(snapshot, pids_compartidos, intervalos[nombre]),
            daemon=True,
        )
        procesos.append(p)

    for p in procesos:
        p.start()

    corriendo = {"valor": True}

    def manejar_sigint(signum, frame):
        corriendo["valor"] = False

    signal.signal(signal.SIGINT, manejar_sigint)

    while corriendo["valor"]:
        if "sistema" in snapshot:
            datos = snapshot["sistema"]["datos"]
            print(
                f"--- sistema: cpu_user={datos['cpu_pct']['user']}% "
                f"procesos={datos['procesos_totales']} zombies={datos['zombies']} "
                f"threads={datos['threads_totales']} load={datos['loadavg']['load_1min']} ---"
            )
        vistas_listas = [v for v in ANALIZADORES if v in snapshot]
        print(f"vistas con datos: {vistas_listas}")
        time.sleep(2)

    print("\nSIGINT recibido, cerrando procesos hijos...")
    for p in procesos:
        p.terminate()
        p.join()


if __name__ == "__main__":
    main()
