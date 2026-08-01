import os
import pwd
import signal


def _extraer_comm_y_resto(linea):
    # compartida entre leer_stat y leer_stat_thread para no duplicar
    # la lógica sensible de parseo (bug de paréntesis anidados, ver (sd-pam))
    inicio_comm = linea.index("(")
    fin_comm = linea.rindex(")")
    comm = linea[inicio_comm + 1:fin_comm]
    resto = linea[fin_comm + 2:].split()
    return comm, resto


def leer_stat(pid):
    with open(f"/proc/{pid}/stat", "r") as f:
        linea = f.read()

    comm, resto = _extraer_comm_y_resto(linea)
    campos = [str(pid), comm] + resto

    return {
        "pid": int(campos[0]),          # campo 1
        "comm": campos[1],               # campo 2
        "state": campos[2],              # campo 3 (R/S/D/T/Z)
        "ppid": int(campos[3]),          # campo 4
        "pgrp": int(campos[4]),          # campo 5 (PGID)
        "session": int(campos[5]),       # campo 6 (SID)
        "minflt": int(campos[9]),        # campo 10
        "cminflt": int(campos[10]),      # campo 11
        "majflt": int(campos[11]),       # campo 12
        "cmajflt": int(campos[12]),      # campo 13
        "utime": int(campos[13]),        # campo 14 (jiffies en modo usuario)
        "stime": int(campos[14]),        # campo 15 (jiffies en modo kernel)
        "cutime": int(campos[15]),       # campo 16 (utime de hijos ya esperados)
        "cstime": int(campos[16]),       # campo 17 (stime de hijos ya esperados)
        "priority": int(campos[17]),     # campo 18
        "nice": int(campos[18]),         # campo 19
        "num_threads": int(campos[19]),  # campo 20
        "rt_priority": int(campos[39]),  # campo 40 (0 si no es RT)
        "policy": int(campos[40]),       # campo 41 (SCHED_OTHER=0, FIFO=1, RR=2...)
    }


def decodificar_mascara_senales(hex_str):
    mascara = int(hex_str, 16)
    nombres = []
    for n in range(1, 65):
        # bit (n-1) prendido == señal n bloqueada/ignorada/etc. según la máscara que se pase
        if mascara & (1 << (n - 1)):
            try:
                nombres.append(signal.Signals(n).name)
            except ValueError:
                # algunos números no tienen señal POSIX asignada en esta plataforma
                nombres.append(f"SIG{n}")
    return nombres


def _kb(datos, clave):
    # varios campos Vm* no existen para kernel threads (ej. kworker) -> default 0
    if clave not in datos:
        return 0
    return int(datos[clave].split()[0])


def leer_status(pid):
    datos = {}
    with open(f"/proc/{pid}/status", "r") as f:
        for linea in f:
            clave, _, valor = linea.partition(":")
            datos[clave.strip()] = valor.strip()

    uid = datos["Uid"].split()  # real, efectivo, guardado, filesystem
    gid = datos["Gid"].split()
    uid_real = int(uid[0])

    try:
        usuario = pwd.getpwuid(uid_real).pw_name
    except KeyError:
        # UID sin entrada en /etc/passwd (común en contenedores minimalistas)
        usuario = str(uid_real)

    return {
        "ppid": int(datos["PPid"]),
        "uid_real": uid_real,
        "uid_efectivo": int(uid[1]),
        "usuario": usuario,
        "gid_real": int(gid[0]),
        "threads": int(datos["Threads"]),
        "vm_size_kb": _kb(datos, "VmSize"),
        "vm_rss_kb": _kb(datos, "VmRSS"),
        "vm_hwm_kb": _kb(datos, "VmHWM"),
        "vm_data_kb": _kb(datos, "VmData"),
        "vm_stk_kb": _kb(datos, "VmStk"),
        "vm_exe_kb": _kb(datos, "VmExe"),
        "vm_lib_kb": _kb(datos, "VmLib"),
        "vm_swap_kb": _kb(datos, "VmSwap"),
        "cpus_allowed_list": datos.get("Cpus_allowed_list", ""),
        "voluntary_ctxt_switches": int(datos.get("voluntary_ctxt_switches", 0)),
        "nonvoluntary_ctxt_switches": int(datos.get("nonvoluntary_ctxt_switches", 0)),
        "sig_blk": decodificar_mascara_senales(datos.get("SigBlk", "0")),
        "sig_ign": decodificar_mascara_senales(datos.get("SigIgn", "0")),
        "sig_cgt": decodificar_mascara_senales(datos.get("SigCgt", "0")),
        "sig_pnd": decodificar_mascara_senales(datos.get("SigPnd", "0")),
        "shd_pnd": decodificar_mascara_senales(datos.get("ShdPnd", "0")),
    }


def leer_cmdline(pid):
    with open(f"/proc/{pid}/cmdline", "rb") as f:
        crudo = f.read()

    if not crudo:
        # proceso sin argv visible (ej. proceso kernel, o zombie): no hay nada que leer
        return ""

    # cmdline separa cada argumento con un byte nulo, no con espacios --
    # así "mi archivo.txt" pasado como UN solo argv no se confunde con dos
    partes = crudo.split(b"\x00")
    return " ".join(p.decode(errors="replace") for p in partes if p)


def leer_maps(pid):
    grupos = {"text": 0, "data": 0, "heap": 0, "stack": 0, "shared": 0}

    with open(f"/proc/{pid}/maps", "r") as f:
        for linea in f:
            # formato: "inicio-fin perms offset dev inode pathname"
            # split(None, 5) corta en máximo 6 pedazos -> el pathname (que puede
            # tener espacios, ej. "/ruta con espacios/lib.so") queda intacto entero
            partes = linea.split(None, 5)
            rango, perms = partes[0], partes[1]
            pathname = partes[5].strip() if len(partes) > 5 else ""

            inicio_hex, fin_hex = rango.split("-")
            tam_kb = (int(fin_hex, 16) - int(inicio_hex, 16)) // 1024

            if pathname == "[heap]":
                grupo = "heap"
            elif pathname.startswith("[stack"):
                grupo = "stack"
            elif "x" in perms:
                # segmento ejecutable mapeado desde un archivo -> código (text)
                grupo = "text"
            elif pathname == "":
                # mapeo anónimo sin nombre especial: memoria compartida/mmap privado
                grupo = "shared"
            else:
                # mapeo de archivo, no ejecutable, no heap/stack -> datos (globales, .bss)
                grupo = "data"

            grupos[grupo] += tam_kb

    return grupos


def listar_fds(pid):
    fds = []
    base = f"/proc/{pid}/fd"

    for nombre in os.listdir(base):
        ruta = f"{base}/{nombre}"
        try:
            destino = os.readlink(ruta)
        except OSError:
            # el FD se cerró entre el listdir() y el readlink(): es una race
            # condition real e inevitable contra el propio kernel, no un bug nuestro
            continue

        if destino.startswith("socket:"):
            tipo = "socket"
        elif destino.startswith("pipe:"):
            tipo = "pipe"
        elif destino.startswith("/dev/pts") or destino.startswith("/dev/tty"):
            tipo = "tty"
        elif destino.startswith("anon_inode:"):
            tipo = "anon_inode"
        else:
            tipo = "file"

        fds.append({"fd": int(nombre), "destino": destino, "tipo": tipo})

    return fds


def leer_stat_thread(pid, tid):
    with open(f"/proc/{pid}/task/{tid}/stat", "r") as f:
        linea = f.read()

    comm, resto = _extraer_comm_y_resto(linea)
    campos = [str(tid), comm] + resto

    return {
        "tid": tid,
        "comm": campos[1],
        "state": campos[2],
        "utime": int(campos[13]),
        "stime": int(campos[14]),
    }


def listar_threads(pid):
    threads = []
    base = f"/proc/{pid}/task"

    for tid_str in os.listdir(base):
        tid = int(tid_str)
        try:
            info = leer_stat_thread(pid, tid)
        except FileNotFoundError:
            # el thread murió entre el listdir() y la lectura de su /stat
            continue

        voluntary = nonvoluntary = 0
        try:
            with open(f"{base}/{tid}/status", "r") as f:
                for linea in f:
                    clave, _, valor = linea.partition(":")
                    clave = clave.strip()
                    if clave == "voluntary_ctxt_switches":
                        voluntary = int(valor.strip())
                    elif clave == "nonvoluntary_ctxt_switches":
                        nonvoluntary = int(valor.strip())
        except FileNotFoundError:
            pass

        info["voluntary_ctxt_switches"] = voluntary
        info["nonvoluntary_ctxt_switches"] = nonvoluntary
        threads.append(info)

    return threads


def leer_meminfo():
    datos = {}
    with open("/proc/meminfo", "r") as f:
        for linea in f:
            clave, _, valor = linea.partition(":")
            # todos los valores vienen como "12345 kB" -> nos quedamos con el número
            datos[clave.strip()] = int(valor.split()[0])

    return {
        "total_kb": datos.get("MemTotal", 0),
        "libre_kb": datos.get("MemFree", 0),
        "disponible_kb": datos.get("MemAvailable", 0),
        "buffers_kb": datos.get("Buffers", 0),
        "cached_kb": datos.get("Cached", 0),
        "swap_total_kb": datos.get("SwapTotal", 0),
        "swap_libre_kb": datos.get("SwapFree", 0),
    }


def leer_loadavg():
    with open("/proc/loadavg", "r") as f:
        partes = f.read().split()

    return {
        "load_1min": float(partes[0]),
        "load_5min": float(partes[1]),
        "load_15min": float(partes[2]),
        "en_ejecucion_total": partes[3],  # formato "N/M": N corriendo de M totales
    }


def leer_uptime():
    with open("/proc/uptime", "r") as f:
        segundos = f.read().split()[0]
    return float(segundos)


def leer_stat_sistema():
    cpu = {}
    btime = 0

    with open("/proc/stat", "r") as f:
        for linea in f:
            if linea.startswith("cpu "):
                # única línea agregada de todos los cores; las líneas "cpu0", "cpu1"...
                # son por-core y no las necesitamos para el total del sistema
                valores = linea.split()[1:]
                nombres = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal"]
                cpu = {n: int(v) for n, v in zip(nombres, valores)}
            elif linea.startswith("btime"):
                btime = int(linea.split()[1])

    return {"cpu": cpu, "btime": btime}
