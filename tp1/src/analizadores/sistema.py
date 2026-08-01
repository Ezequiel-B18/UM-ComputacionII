import time

import procfs
from senales import ignorar_senales_en_hijo


def correr_sistema(snapshot, pids_compartidos, intervalo):
    ignorar_senales_en_hijo()

    anterior_cpu = None  # (dict de jiffies globales, timestamp) para el delta de CPU%

    while True:
        ahora = time.time()
        meminfo = procfs.leer_meminfo()
        loadavg = procfs.leer_loadavg()
        uptime = procfs.leer_uptime()
        stat_sistema = procfs.leer_stat_sistema()

        cpu_actual = stat_sistema["cpu"]
        cpu_pct = {"user": 0.0, "system": 0.0, "idle": 0.0, "iowait": 0.0}

        if anterior_cpu is not None:
            cpu_prev, _ = anterior_cpu
            delta_total = sum(cpu_actual.values()) - sum(cpu_prev.values())
            if delta_total > 0:
                for clave in cpu_pct:
                    delta = cpu_actual[clave] - cpu_prev[clave]
                    cpu_pct[clave] = round(delta / delta_total * 100, 1)

        anterior_cpu = (dict(cpu_actual), ahora)

        por_estado = {}
        threads_totales = 0
        zombies = 0

        for pid in list(pids_compartidos):
            try:
                stat = procfs.leer_stat(pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue

            estado = stat["state"]
            por_estado[estado] = por_estado.get(estado, 0) + 1
            threads_totales += stat["num_threads"]
            if estado == "Z":
                zombies += 1

        # top-3 por cpu/mem: se apoya en lo que ya calculó el analizador "resumen"
        # en vez de recalcular CPU% acá también -- evita duplicar el estado de deltas
        top_cpu, top_mem = [], []
        resumen = snapshot.get("resumen")
        if resumen:
            items = list(resumen["datos"].items())
            top_cpu = sorted(items, key=lambda kv: kv[1]["cpu_pct"], reverse=True)[:3]
            top_mem = sorted(items, key=lambda kv: kv[1]["rss_kb"], reverse=True)[:3]

        snapshot["sistema"] = {
            "datos": {
                "meminfo": meminfo,
                "loadavg": loadavg,
                "uptime": uptime,
                "btime": stat_sistema["btime"],
                "cpu_pct": cpu_pct,
                "procesos_totales": sum(por_estado.values()),
                "por_estado": por_estado,
                "threads_totales": threads_totales,
                "zombies": zombies,
                "top_cpu": top_cpu,
                "top_mem": top_mem,
            },
            "ts": ahora,
        }
        time.sleep(intervalo.value)
