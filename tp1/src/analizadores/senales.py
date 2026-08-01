import time

import procfs
# ojo: este módulo es "analizadores.senales" (la VISTA de señales de los
# procesos monitoreados); "senales" a secas es src/senales.py, el manejo de
# señales del propio monitor. Son cosas distintas con nombre parecido.
from senales import ignorar_senales_en_hijo


def correr_senales(snapshot, pids_compartidos, intervalo):
    ignorar_senales_en_hijo()

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
