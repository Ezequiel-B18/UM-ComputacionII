import signal
import time

import procfs


def correr_memoria(snapshot, pids_compartidos, intervalo):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while True:
        ahora = time.time()
        datos = {}

        for pid in list(pids_compartidos):
            try:
                status = procfs.leer_status(pid)
                stat = procfs.leer_stat(pid)
                segmentos = procfs.leer_maps(pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue

            datos[pid] = {
                "vm_size_kb": status["vm_size_kb"],
                "vm_rss_kb": status["vm_rss_kb"],
                "vm_hwm_kb": status["vm_hwm_kb"],
                "vm_data_kb": status["vm_data_kb"],
                "vm_stk_kb": status["vm_stk_kb"],
                "vm_exe_kb": status["vm_exe_kb"],
                "vm_lib_kb": status["vm_lib_kb"],
                "vm_swap_kb": status["vm_swap_kb"],
                "minflt": stat["minflt"],
                "majflt": stat["majflt"],
                "segmentos": segmentos,
            }

        snapshot["memoria"] = {"datos": datos, "ts": ahora}
        time.sleep(intervalo.value)
