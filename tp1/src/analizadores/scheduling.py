import time

import procfs
from senales import ignorar_senales_en_hijo

# valores de sched_setscheduler(2) -- no hay enum estándar en la stdlib para esto
NOMBRES_POLICY = {0: "OTHER", 1: "FIFO", 2: "RR", 3: "BATCH", 5: "IDLE"}


def correr_scheduling(snapshot, pids_compartidos, intervalo):
    ignorar_senales_en_hijo()

    while True:
        ahora = time.time()
        datos = {}

        for pid in list(pids_compartidos):
            try:
                stat = procfs.leer_stat(pid)
                status = procfs.leer_status(pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue

            datos[pid] = {
                "nice": stat["nice"],
                "priority": stat["priority"],
                "policy": NOMBRES_POLICY.get(stat["policy"], f"POLICY_{stat['policy']}"),
                "rt_priority": stat["rt_priority"],
                "cpus_allowed_list": status["cpus_allowed_list"],
                "voluntary_ctxt_switches": status["voluntary_ctxt_switches"],
                "nonvoluntary_ctxt_switches": status["nonvoluntary_ctxt_switches"],
                "utime": stat["utime"],
                "stime": stat["stime"],
                "session": stat["session"],
                "pgrp": stat["pgrp"],
            }

        snapshot["scheduling"] = {"datos": datos, "ts": ahora}
        time.sleep(intervalo.value)
