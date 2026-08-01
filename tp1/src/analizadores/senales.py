import signal
import time

import procfs


def correr_senales(snapshot, pids_compartidos, intervalo):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while True:
        ahora = time.time()
        datos = {}

        for pid in list(pids_compartidos):
            try:
                status = procfs.leer_status(pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue

            datos[pid] = {
                "sig_blk": status["sig_blk"],
                "sig_ign": status["sig_ign"],
                "sig_cgt": status["sig_cgt"],
                "sig_pnd": status["sig_pnd"],
                "shd_pnd": status["shd_pnd"],
            }

        snapshot["senales"] = {"datos": datos, "ts": ahora}
        time.sleep(intervalo.value)
