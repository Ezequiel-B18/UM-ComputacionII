import time

import procfs
from senales import ignorar_senales_en_hijo


def correr_fds(snapshot, pids_compartidos, intervalo):
    ignorar_senales_en_hijo()

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
