import os
import signal
import time

import procfs

HZ = os.sysconf("SC_CLK_TCK")  # jiffies por segundo -- NO es un 100 fijo en todas las máquinas


def correr_resumen(snapshot, pids_compartidos, intervalo):
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # el padre maneja el shutdown, no este hijo

    anteriores = {}  # pid -> (utime+stime, timestamp de esa lectura)
    # este dict vive en la memoria PRIVADA de este proceso: ningún otro
    # analizador necesita la lectura anterior de "resumen", así que no
    # hace falta compartirlo -- evita un lock innecesario

    while True:
        ahora = time.time()
        resumen = {}

        for pid in list(pids_compartidos):
            try:
                stat = procfs.leer_stat(pid)
                status = procfs.leer_status(pid)
                cmdline = procfs.leer_cmdline(pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                # el proceso murió entre que el recolector lo listó y que lo leemos,
                # o es de otro usuario y no tenemos permiso -- ambos casos normales
                continue

            jiffies_totales = stat["utime"] + stat["stime"]
            cpu_pct = 0.0

            if pid in anteriores:
                jiffies_prev, ts_prev = anteriores[pid]
                delta_jiffies = jiffies_totales - jiffies_prev
                delta_tiempo = ahora - ts_prev
                if delta_tiempo > 0:
                    cpu_pct = (delta_jiffies / HZ) / delta_tiempo * 100

            anteriores[pid] = (jiffies_totales, ahora)

            resumen[pid] = {
                "ppid": stat["ppid"],
                "state": stat["state"],
                "usuario": status["usuario"],
                "cmd": cmdline or f"[{stat['comm']}]",
                "cpu_pct": round(cpu_pct, 1),
                "rss_kb": status["vm_rss_kb"],
                "threads": status["threads"],
            }

        # limpiar de "anteriores" los pids que ya no existen, si no la memoria
        # de este proceso crece sin límite a medida que el sistema crea/mata procesos
        vivos = set(resumen.keys())
        for pid_viejo in list(anteriores.keys()):
            if pid_viejo not in vivos:
                del anteriores[pid_viejo]

        snapshot["resumen"] = {"datos": resumen, "ts": ahora}
        time.sleep(intervalo.value)
