import curses
import json
import multiprocessing as mp
import sys
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
from display import correr_tui, EstadoTUI, _procesar_senal
from exportador import correr_exportador

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


def modo_daemon(snapshot, intervalos, config, modo_verbose, manejador, dump_fn, cargar_config, ruta_log="monitor.log"):
    # bonus #3: correr sin TUI, sólo loggeando a archivo -- reusa
    # EstadoTUI/_procesar_senal de display.py para no duplicar el manejo de
    # señales (nada de eso depende de curses en sí, son solo datos)
    estado = EstadoTUI(config)
    corriendo = True

    with open(ruta_log, "a") as log:
        while corriendo:
            for signum in manejador.esperar(timeout=2.0):
                corriendo = (
                    _procesar_senal(signum, snapshot, intervalos, config, modo_verbose, dump_fn, estado, cargar_config)
                    and corriendo
                )

            if not corriendo:
                break

            if "sistema" in snapshot:
                d = snapshot["sistema"]["datos"]
                marca = time.strftime("%Y-%m-%d %H:%M:%S")
                log.write(
                    f"{marca} cpu_user={d['cpu_pct']['user']}% procesos={d['procesos_totales']} "
                    f"zombies={d['zombies']} threads={d['threads_totales']} "
                    f"load={d['loadavg']['load_1min']}\n"
                )
                log.flush()


def main(usar_tui=True):
    config = cargar_config()

    manager = mp.Manager()
    snapshot = manager.dict()
    pids_compartidos = manager.list()
    modo_verbose = mp.Value("i", 0)

    intervalos = {
        nombre: mp.Value("d", config["intervalos"][nombre]["default"])
        for nombre in ANALIZADORES
    }

    exportacion_cfg = config.get("exportacion", {"intervalo_seg": 30.0, "directorio": "exports"})

    procesos = [
        mp.Process(target=correr_recolector, args=(pids_compartidos, 1.0), daemon=True),
        mp.Process(
            target=correr_exportador,
            args=(snapshot, exportacion_cfg["intervalo_seg"], exportacion_cfg["directorio"]),
            daemon=True,
        ),
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
    # estas señales apenas arranca (ignorar_senales_en_hijo), así que el
    # orden de instalación acá ya no importa como importó con el bug de SIGINT
    manejador = ManejadorSenales()

    try:
        if usar_tui:
            # curses.wrapper se encarga de dejar la terminal en modo raw y,
            # pase lo que pase adentro (excepción incluida), restaurarla al salir
            curses.wrapper(
                correr_tui, snapshot, pids_compartidos, intervalos, config, modo_verbose, manejador, dump_snapshot,
                cargar_config,
            )
        else:
            modo_daemon(snapshot, intervalos, config, modo_verbose, manejador, dump_snapshot, cargar_config)
    finally:
        for p in procesos:
            p.terminate()
            p.join()


if __name__ == "__main__":
    main(usar_tui="--daemon" not in sys.argv)
