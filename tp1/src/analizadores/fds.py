import signal
import time

import procfs


def correr_fds(snapshot, pids_compartidos, intervalo):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while True:
        ahora = time.time()
        datos = {}

        for pid in list(pids_compartidos):
            try:
                fds = procfs.listar_fds(pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue

            datos[pid] = fds

        snapshot["fds"] = {"datos": datos, "ts": ahora}
        time.sleep(intervalo.value)
