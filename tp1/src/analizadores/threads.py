import os
import time

import procfs
from senales import ignorar_senales_en_hijo

HZ = os.sysconf("SC_CLK_TCK")


def correr_threads(snapshot, pids_compartidos, intervalo):
    ignorar_senales_en_hijo()

    anteriores = {}  # (pid, tid) -> (utime+stime, timestamp) para CPU% por thread

    while True:
        ahora = time.time()
        datos = {}

        for pid in list(pids_compartidos):
            try:
                lista = procfs.listar_threads(pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue

            for th in lista:
                clave = (pid, th["tid"])
                jiffies_totales = th["utime"] + th["stime"]
                cpu_pct = 0.0

                if clave in anteriores:
                    jiffies_prev, ts_prev = anteriores[clave]
                    delta_t = ahora - ts_prev
                    if delta_t > 0:
                        cpu_pct = ((jiffies_totales - jiffies_prev) / HZ) / delta_t * 100

                anteriores[clave] = (jiffies_totales, ahora)
                th["cpu_pct"] = round(cpu_pct, 1)

            datos[pid] = lista

        # poda de threads que ya no existen (mismo motivo que en resumen.py)
        vivos = {(pid, th["tid"]) for pid, lista in datos.items() for th in lista}
        for clave_vieja in list(anteriores.keys()):
            if clave_vieja not in vivos:
                del anteriores[clave_vieja]

        snapshot["threads"] = {"datos": datos, "ts": ahora}
        time.sleep(intervalo.value)
