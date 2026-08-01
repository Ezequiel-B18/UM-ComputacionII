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
from senales import ManejadorSenales

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


def dump_snapshot(snapshot):
    marca = int(time.time())
    ruta = f"dump_{marca}.json"
    # dict(snapshot) materializa el DictProxy del Manager en un dict real de Python
    with open(ruta, "w") as f:
        json.dump(dict(snapshot), f, indent=2, default=str)
    return ruta


def main():
    config = cargar_config()

    manager = mp.Manager()
    snapshot = manager.dict()
    pids_compartidos = manager.list()
    modo_verbose = mp.Value("i", 0)

    intervalos = {
        nombre: mp.Value("d", config["intervalos"][nombre]["default"])
        for nombre in ANALIZADORES
    }

    procesos = [
        mp.Process(target=correr_recolector, args=(pids_compartidos, 1.0), daemon=True)
    ]
    for nombre, funcion in ANALIZADORES.items():
        procesos.append(
            mp.Process(
                target=funcion,
                args=(snapshot, pids_compartidos, intervalos[nombre]),
                daemon=True,
            )
        )

    for p in procesos:
        p.start()

    # se instala DESPUÉS de p.start() a propósito: cada hijo ya se auto-ignora
    # estas 5 señales apenas arranca (ignorar_senales_en_hijo), así que el
    # orden de instalación acá ya no importa como importó con el bug de SIGINT
    manejador = ManejadorSenales()

    corriendo = True
    while corriendo:
        for signum in manejador.esperar(timeout=2.0):
            if signum in (signal.SIGINT, signal.SIGTERM):
                print(f"\n{signal.Signals(signum).name} recibido, cerrando limpiamente...")
                corriendo = False

            elif signum == signal.SIGHUP:
                print("SIGHUP recibido: recargando config.json...")
                config = cargar_config()
                for nombre, valor in intervalos.items():
                    valor.value = config["intervalos"][nombre]["default"]

            elif signum == signal.SIGUSR1:
                ruta = dump_snapshot(snapshot)
                print(f"SIGUSR1 recibido: snapshot volcado en {ruta}")

            elif signum == signal.SIGUSR2:
                modo_verbose.value = 1 - modo_verbose.value
                estado = "ON" if modo_verbose.value else "OFF"
                print(f"SIGUSR2 recibido: modo verbose {estado}")

        if not corriendo:
            break

        if "sistema" in snapshot:
            datos = snapshot["sistema"]["datos"]
            linea = (
                f"--- sistema: cpu_user={datos['cpu_pct']['user']}% "
                f"procesos={datos['procesos_totales']} zombies={datos['zombies']} "
                f"threads={datos['threads_totales']} load={datos['loadavg']['load_1min']}"
            )
            if modo_verbose.value:
                linea += f" | por_estado={datos['por_estado']} top_cpu={datos['top_cpu']}"
            print(linea + " ---")

    print("Cerrando procesos hijos...")
    for p in procesos:
        p.terminate()
        p.join()


if __name__ == "__main__":
    main()
