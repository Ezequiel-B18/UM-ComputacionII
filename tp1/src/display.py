import collections
import curses
import os
import signal
import time

VISTAS = ["resumen", "memoria", "fds", "threads", "senales", "scheduling", "sistema"]

TECLAS_VISTA = {
    "1": "resumen", "r": "resumen",
    "2": "memoria", "m": "memoria",
    "3": "fds", "f": "fds",
    "4": "threads", "t": "threads",
    "5": "senales", "s": "senales",
    "6": "scheduling", "p": "scheduling",
    "7": "sistema", "g": "sistema",
}

AYUDA = [
    "1-7 o r/m/f/t/s/p/g: cambiar de vista",
    "Flechas arriba/abajo: navegar procesos",
    "Enter: pin/unpin del proceso seleccionado",
    "/: filtrar por comando   u: filtrar por usuario",
    "c: ciclar orden (cpu -> rss -> pid)",
    "+/-: ajustar intervalo de la vista activa",
    "v: togglear modo verbose (se manda SIGUSR2 a si mismo)",
    "j: vista de jerarquia de procesos (tipo pstree)",
    "x: marcar/desmarcar proceso para comparar (hasta 3)",
    "k: vista comparativa de los procesos marcados",
    "q: salir   h/?: esta ayuda",
]


class EstadoTUI:
    def __init__(self, config=None):
        self.vista = "resumen"
        self.seleccion = 0
        self.pid_pineado = None
        self.aplicar_filtro_default(config)
        self.orden = "cpu"  # cpu | rss | pid
        self.modo_captura = None  # None | "comando" | "usuario"
        self.buffer_captura = ""
        self.mostrar_ayuda = False
        self.ultima_senal = None      # nombre de la última señal recibida (bonus #7)
        self.ultima_senal_ts = 0.0
        self.mostrar_jerarquia = False  # bonus #5: vista de árbol tipo pstree
        self.zombies_vistos = set()     # bonus #2: detección de anomalías
        self.anomalias_alertadas = {}   # pid -> timestamp de la última alerta (cooldown)
        self.historico_cpu = {}         # bonus #1: pid -> deque de cpu_pct reciente
        self.historico_rss = {}         # pid -> deque de rss_kb reciente
        self.marcados_comparar = []     # bonus #8: hasta 3 pids para comparar lado a lado
        self.mostrar_comparativa = False

    def aplicar_filtro_default(self, config):
        # se llama al arrancar y de nuevo en cada SIGHUP (la consigna pide
        # que SIGHUP recargue "intervalos por vista, filtros default")
        filtros = (config or {}).get("filtro_default", {})
        self.filtro_cmd = filtros.get("comando")
        self.filtro_usuario = filtros.get("usuario")


def lista_procesos(snapshot, estado):
    """Aplica filtro + orden + pin sobre los datos de la vista 'resumen'.
    Separada de curses a propósito para poder testearla sin terminal real."""
    resumen = snapshot.get("resumen")
    if not resumen:
        return []

    items = list(resumen["datos"].items())

    if estado.filtro_cmd:
        items = [(pid, d) for pid, d in items if estado.filtro_cmd.lower() in d["cmd"].lower()]
    if estado.filtro_usuario:
        items = [(pid, d) for pid, d in items if estado.filtro_usuario.lower() in d["usuario"].lower()]

    if estado.orden == "cpu":
        items.sort(key=lambda kv: kv[1]["cpu_pct"], reverse=True)
    elif estado.orden == "rss":
        items.sort(key=lambda kv: kv[1]["rss_kb"], reverse=True)
    else:
        items.sort(key=lambda kv: kv[0])

    if estado.pid_pineado is not None:
        # el pineado va siempre primero, sin importar el orden elegido,
        # para que "no cambie aunque cambie el orden" (pedido de la consigna)
        pineado = [(pid, d) for pid, d in items if pid == estado.pid_pineado]
        resto = [(pid, d) for pid, d in items if pid != estado.pid_pineado]
        items = pineado + resto

    return items


def construir_arbol(datos_resumen):
    """Bonus #5: jerarquía de procesos tipo `pstree`, a partir del PPID que
    ya leemos para la vista Resumen. Devuelve una lista de (pid, profundidad,
    cmd) en orden de recorrido DFS -- separada de curses para poder
    testearla con un dict de ejemplo, sin terminal real."""
    hijos = {}
    for pid, info in datos_resumen.items():
        hijos.setdefault(info["ppid"], []).append(pid)

    # raíz = cualquier proceso cuyo padre no está en nuestro propio snapshot
    # (o sea, el padre de verdad no lo estamos monitoreando como tal, p. ej. init)
    raices = sorted(pid for pid, info in datos_resumen.items() if info["ppid"] not in datos_resumen)

    lineas = []
    visitados = set()

    def recorrer(pid, profundidad):
        if pid in visitados or pid not in datos_resumen:
            return
        visitados.add(pid)
        lineas.append((pid, profundidad, datos_resumen[pid]["cmd"]))
        for hijo in sorted(hijos.get(pid, [])):
            recorrer(hijo, profundidad + 1)

    for raiz in raices:
        recorrer(raiz, 0)

    return lineas


HISTORICO_MAXLEN = 30
NIVELES_ASCII = " .:-=+*#%@"  # de "casi nada" a "al máximo", 10 niveles


def actualizar_historico(estado, resumen_datos):
    """Bonus #1: guarda una serie temporal corta de CPU%/RSS por pid, del
    lado de la TUI (no hace falta que los analizadores sepan de esto)."""
    for pid, info in resumen_datos.items():
        if pid not in estado.historico_cpu:
            estado.historico_cpu[pid] = collections.deque(maxlen=HISTORICO_MAXLEN)
            estado.historico_rss[pid] = collections.deque(maxlen=HISTORICO_MAXLEN)
        estado.historico_cpu[pid].append(info["cpu_pct"])
        estado.historico_rss[pid].append(info["rss_kb"])

    # poda de pids que ya no existen, mismo motivo que en los analizadores
    vivos = set(resumen_datos.keys())
    for pid_viejo in list(estado.historico_cpu.keys()):
        if pid_viejo not in vivos:
            del estado.historico_cpu[pid_viejo]
            del estado.historico_rss[pid_viejo]


def mini_grafico_ascii(valores, escala_max=None):
    """Sparkline ASCII (no Unicode, a propósito -- ver decisión de diseño
    sobre evitar caracteres multi-byte en curses) mapeando cada valor a uno
    de 10 niveles de intensidad según su magnitud relativa."""
    if not valores:
        return ""

    tope = escala_max if escala_max is not None else (max(valores) or 1)
    grafico = []
    for v in valores:
        idx = int((v / tope) * (len(NIVELES_ASCII) - 1)) if tope else 0
        idx = max(0, min(len(NIVELES_ASCII) - 1, idx))
        grafico.append(NIVELES_ASCII[idx])

    return "".join(grafico)


UMBRAL_CPU_ALERTA = 90.0
COOLDOWN_ALERTA_SEG = 10.0


def detectar_anomalias(estado, resumen_datos, ahora):
    """Bonus #2: zombies nuevos y picos de CPU. Escribe en estado.ultima_senal
    (mismo mecanismo que las notificaciones de señales) si encuentra algo.
    Con cooldown por pid para no spamear el mismo proceso cada 200ms."""
    zombies_actuales = {pid for pid, info in resumen_datos.items() if info["state"] == "Z"}
    nuevos_zombies = zombies_actuales - estado.zombies_vistos
    estado.zombies_vistos = zombies_actuales

    if nuevos_zombies:
        pid = min(nuevos_zombies)
        estado.ultima_senal = f"ALERTA: nuevo zombie detectado (pid {pid})"
        estado.ultima_senal_ts = ahora
        return

    for pid, info in resumen_datos.items():
        if info["cpu_pct"] < UMBRAL_CPU_ALERTA:
            continue
        ultima_vez = estado.anomalias_alertadas.get(pid, 0)
        if ahora - ultima_vez > COOLDOWN_ALERTA_SEG:
            estado.anomalias_alertadas[pid] = ahora
            estado.ultima_senal = f"ALERTA: pid {pid} ({info['cmd'][:30]}) usa {info['cpu_pct']}% CPU"
            estado.ultima_senal_ts = ahora
            return


def pid_seleccionado(estado, procesos):
    if estado.pid_pineado is not None:
        return estado.pid_pineado
    if not procesos:
        return None
    idx = max(0, min(estado.seleccion, len(procesos) - 1))
    return procesos[idx][0]


def _procesar_senal(signum, snapshot, intervalos, config, modo_verbose, dump_fn, estado, cargar_config):
    if signum in (signal.SIGINT, signal.SIGTERM):
        return False  # corta el loop principal -> dispara shutdown

    if signum == signal.SIGHUP:
        # relee config.json de VERDAD del disco -- mutamos el mismo dict in-place
        # (config.clear()+update, no "config = ...") para que todo lo que ya
        # tiene una referencia a este objeto (los +/- de intervalo) vea lo nuevo
        config.clear()
        config.update(cargar_config())
        for nombre, valor in intervalos.items():
            valor.value = config["intervalos"][nombre]["default"]
        estado.aplicar_filtro_default(config)
        estado.ultima_senal = "SIGHUP recibido: config.json recargado"
    elif signum == signal.SIGUSR1:
        ruta = dump_fn(snapshot)
        estado.ultima_senal = f"SIGUSR1 recibido: snapshot volcado en {ruta}"
    elif signum == signal.SIGUSR2:
        modo_verbose.value = 1 - modo_verbose.value
        estado_verbose = "ON" if modo_verbose.value else "OFF"
        estado.ultima_senal = f"SIGUSR2 recibido: modo verbose {estado_verbose}"

    estado.ultima_senal_ts = time.time()
    return True


def _togglear_pin(estado, procesos):
    # si ya hay algo pineado, Enter SIEMPRE lo despinea -- sin mirar
    # estado.seleccion, porque ese índice puede apuntar a un proceso
    # distinto en el frame siguiente (la lista se reordena en vivo cada
    # vez que cambia el CPU%, así que un índice de fila no identifica de
    # forma estable al mismo proceso entre dos frames)
    if estado.pid_pineado is not None:
        estado.pid_pineado = None
        return
    if procesos:
        idx = max(0, min(estado.seleccion, len(procesos) - 1))
        estado.pid_pineado = procesos[idx][0]


def _procesar_tecla(tecla, estado, intervalos, config, procesos):
    if estado.modo_captura:
        if tecla in (10, 13):
            valor = estado.buffer_captura or None
            if estado.modo_captura == "comando":
                estado.filtro_cmd = valor
            else:
                estado.filtro_usuario = valor
            estado.modo_captura = None
            estado.buffer_captura = ""
        elif tecla == 27:  # Esc: cancela sin aplicar
            estado.modo_captura = None
            estado.buffer_captura = ""
        elif tecla in (curses.KEY_BACKSPACE, 127, 8):
            estado.buffer_captura = estado.buffer_captura[:-1]
        elif 32 <= tecla <= 126:
            estado.buffer_captura += chr(tecla)
        return True

    ch = chr(tecla) if 0 <= tecla < 256 else ""

    if ch in TECLAS_VISTA:
        estado.vista = TECLAS_VISTA[ch]
        estado.mostrar_ayuda = False
    elif tecla == curses.KEY_UP:
        estado.seleccion = max(0, estado.seleccion - 1)
        estado.mostrar_ayuda = False
    elif tecla == curses.KEY_DOWN:
        # clampeado contra la lista actual -- si no, filtrar/ordenar podía
        # dejar la selección apuntando fuera de rango (sin marcador visible)
        tope = max(0, len(procesos) - 1)
        estado.seleccion = min(tope, estado.seleccion + 1)
        estado.mostrar_ayuda = False
    elif tecla in (10, 13):
        _togglear_pin(estado, procesos)
    elif ch == "/":
        estado.modo_captura = "comando"
        estado.buffer_captura = ""
    elif ch == "u":
        estado.modo_captura = "usuario"
        estado.buffer_captura = ""
    elif ch == "c":
        estado.orden = {"cpu": "rss", "rss": "pid", "pid": "cpu"}[estado.orden]
    elif ch == "+":
        v = intervalos[estado.vista]
        minimo = config["intervalos"][estado.vista]["minimo"]
        v.value = round(max(minimo, v.value - 0.5), 2)
    elif ch == "-":
        v = intervalos[estado.vista]
        v.value = round(min(30.0, v.value + 0.5), 2)
    elif ch == "v":
        # se manda SIGUSR2 a sí mismo -- pasa por el self-pipe real, mismo
        # código que si la señal viniera de "docker kill --signal=USR2".
        # Comodidad de UI, no un atajo que evite el mecanismo de señales.
        os.kill(os.getpid(), signal.SIGUSR2)
    elif ch == "j":
        estado.mostrar_jerarquia = not estado.mostrar_jerarquia
        estado.mostrar_ayuda = False
        estado.mostrar_comparativa = False
    elif ch == "x":
        if procesos:
            idx = max(0, min(estado.seleccion, len(procesos) - 1))
            pid_actual = procesos[idx][0]
            if pid_actual in estado.marcados_comparar:
                estado.marcados_comparar.remove(pid_actual)
            elif len(estado.marcados_comparar) < 3:
                estado.marcados_comparar.append(pid_actual)
    elif ch == "k":
        estado.mostrar_comparativa = not estado.mostrar_comparativa
        estado.mostrar_ayuda = False
        estado.mostrar_jerarquia = False
    elif ch == "q":
        return False
    elif ch in ("h", "?"):
        estado.mostrar_ayuda = not estado.mostrar_ayuda
        estado.mostrar_jerarquia = False
        estado.mostrar_comparativa = False

    return True


def _addstr_seguro(win, y, x, texto, attr=0):
    # curses tira excepción si escribís justo en la última celda de la pantalla;
    # es un detalle molesto de la librería, no un bug nuestro
    alto, ancho = win.getmaxyx()
    if y < 0 or y >= alto:
        return
    try:
        win.addstr(y, x, texto[: max(0, ancho - x - 1)], attr)
    except curses.error:
        pass


def filas_visibles(seleccion, total, max_filas):
    """Calcula qué ventana [inicio, inicio+max_filas) mostrar para que la
    fila seleccionada siempre esté visible -- scroll estilo 'less'/htop.
    Separada de curses para poder testearla con enteros simples."""
    if total <= max_filas:
        return 0

    inicio = 0
    if seleccion >= max_filas:
        inicio = seleccion - max_filas + 1

    return max(0, min(inicio, total - max_filas))


def _dibujar_lista(win, ancho, alto, procesos, estado):
    encabezado = f"{'':1}{'PID':>7} {'USR':<10} S {'CPU%':>6} {'RSS(kB)':>10} CMD"
    _addstr_seguro(win, 0, 0, encabezado, curses.A_BOLD)

    # la lista se lleva hasta la mitad de la pantalla (mínimo 5 filas),
    # el resto queda para el panel de detalle de abajo
    max_filas = max(5, alto // 2 - 2)
    inicio = filas_visibles(estado.seleccion, len(procesos), max_filas)

    for i, (pid, d) in enumerate(procesos[inicio:inicio + max_filas]):
        idx_real = inicio + i
        # el marcador de selección (">") se muestra SIEMPRE, incluso con algo
        # pineado -- si no, no hay forma de ver a qué fila apunta el cursor
        # para poder pinear un proceso distinto más adelante
        es_sel = (idx_real == estado.seleccion)
        es_pineado = (pid == estado.pid_pineado)
        if es_pineado:
            marcador = "*"
        elif es_sel:
            marcador = ">"
        elif pid in estado.marcados_comparar:
            marcador = str(estado.marcados_comparar.index(pid) + 1)  # bonus #8
        else:
            marcador = " "
        linea = (
            f"{marcador}{pid:>7} {d['usuario']:<10} {d['state']:1} "
            f"{d['cpu_pct']:>6.1f} {d['rss_kb']:>10} {d['cmd']}"
        )
        atributo = curses.A_REVERSE if es_sel else curses.A_NORMAL
        _addstr_seguro(win, 1 + i, 0, linea, atributo)

    if len(procesos) > max_filas:
        _addstr_seguro(win, 1 + max_filas, 0, f"[{inicio + 1}-{min(inicio + max_filas, len(procesos))} de {len(procesos)}]")

    return 1 + max_filas + 1  # próxima fila libre, con un renglón en blanco


def _dibujar_comparativa(win, ancho, alto, snapshot, marcados):
    """Bonus #8: hasta 3 procesos marcados con 'x', lado a lado en columnas."""
    _addstr_seguro(win, 0, 0, "--- Comparativa cross-proceso -- 'k' para volver ---", curses.A_BOLD)

    if not marcados:
        _addstr_seguro(win, 2, 0, "Marcá procesos con 'x' desde la vista Resumen (hasta 3) y volvé a apretar 'k'.")
        return

    resumen = snapshot.get("resumen")
    scheduling = snapshot.get("scheduling")
    if not resumen:
        _addstr_seguro(win, 2, 0, "(sin datos todavía)")
        return

    col_ancho = max(20, ancho // len(marcados))

    for col, pid in enumerate(marcados):
        x = col * col_ancho
        info = resumen["datos"].get(pid)
        if info is None:
            _addstr_seguro(win, 2, x, f"pid {pid}: (ya no existe)")
            continue

        sched = (scheduling["datos"].get(pid) if scheduling else None) or {}

        _addstr_seguro(win, 2, x, f"PID {pid}", curses.A_BOLD)
        _addstr_seguro(win, 3, x, f"cmd:     {info['cmd'][: col_ancho - 10]}")
        _addstr_seguro(win, 4, x, f"usuario: {info['usuario']}")
        _addstr_seguro(win, 5, x, f"estado:  {info['state']}")
        _addstr_seguro(win, 6, x, f"cpu%:    {info['cpu_pct']}")
        _addstr_seguro(win, 7, x, f"rss:     {info['rss_kb']}kB")
        _addstr_seguro(win, 8, x, f"threads: {info['threads']}")
        if sched:
            _addstr_seguro(win, 9, x, f"nice:    {sched.get('nice', '?')}")
            _addstr_seguro(win, 10, x, f"policy:  {sched.get('policy', '?')}")


def _dibujar_detalle(win, y, ancho, alto_restante, snapshot, estado, pid_sel, verbose):
    etiqueta_verbose = " [verbose]" if verbose else ""
    _addstr_seguro(
        win, y, 0,
        f"--- Vista: {estado.vista} (pid seleccionado: {pid_sel}){etiqueta_verbose} ---",
        curses.A_BOLD,
    )
    y += 1

    bloque = snapshot.get(estado.vista)
    if not bloque:
        _addstr_seguro(win, y, 0, "(sin datos todavía)")
        return

    datos = bloque["datos"]

    if estado.vista == "sistema":
        d = datos
        lineas = [
            f"CPU: user={d['cpu_pct']['user']}% system={d['cpu_pct']['system']}% "
            f"idle={d['cpu_pct']['idle']}% iowait={d['cpu_pct']['iowait']}%",
            f"Load avg: {d['loadavg']['load_1min']} / {d['loadavg']['load_5min']} / {d['loadavg']['load_15min']}",
            f"Memoria: total={d['meminfo']['total_kb']}kB libre={d['meminfo']['libre_kb']}kB "
            f"cached={d['meminfo']['cached_kb']}kB swap_libre={d['meminfo']['swap_libre_kb']}kB",
            f"Procesos: {d['procesos_totales']} totales | zombies={d['zombies']} | "
            f"threads={d['threads_totales']}",
            f"Por estado: {d['por_estado']}",
            "Top CPU: " + ", ".join(f"{pid}:{i['cpu_pct']}%" for pid, i in d["top_cpu"]),
            "Top MEM: " + ", ".join(f"{pid}:{i['rss_kb']}kB" for pid, i in d["top_mem"]),
            f"Uptime: {int(d['uptime'])}s | Boot: "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(d['btime']))}",
        ]
        for i, linea in enumerate(lineas[:alto_restante]):
            _addstr_seguro(win, y + i, 0, linea)
        return

    info = datos.get(pid_sel)
    if info is None:
        _addstr_seguro(win, y, 0, "(el proceso seleccionado no tiene datos en esta vista)")
        return

    if estado.vista == "resumen":
        hist_cpu = list(estado.historico_cpu.get(pid_sel, []))
        hist_rss = list(estado.historico_rss.get(pid_sel, []))
        lineas = [
            f"PID={pid_sel} PPID={info['ppid']} UID={info['uid']} GID={info['gid']} "
            f"usuario={info['usuario']}",
            f"Estado={info['state']} CPU%={info['cpu_pct']} RSS={info['rss_kb']}kB "
            f"Threads={info['threads']}",
            f"Comando completo: {info['cmd']}",
            f"Historico CPU%  [{mini_grafico_ascii(hist_cpu, escala_max=100.0)}]",
            f"Historico RSS   [{mini_grafico_ascii(hist_rss)}]",
        ]
    elif estado.vista == "memoria":
        lineas = [
            f"VmSize={info['vm_size_kb']}kB VmRSS={info['vm_rss_kb']}kB "
            f"VmHWM={info['vm_hwm_kb']}kB VmSwap={info['vm_swap_kb']}kB",
            f"VmData={info['vm_data_kb']}kB VmStk={info['vm_stk_kb']}kB "
            f"VmExe={info['vm_exe_kb']}kB VmLib={info['vm_lib_kb']}kB",
            f"minflt={info['minflt']} majflt={info['majflt']}",
            f"Segmentos (kB): {info['segmentos']}",
        ]
    elif estado.vista == "fds":
        # SIGUSR2 (verbose) = mostrar todos los FDs; sin verbose, recorta la
        # lista -- ejemplo textual de la consigna ("más FDs visibles")
        limite = None if verbose else 12
        recortado = info if limite is None else info[:limite]
        lineas = [f"fd {f['fd']:>3} [{f['tipo']:<10}] -> {f['destino']}" for f in recortado]
        if limite is not None and len(info) > limite:
            lineas.append(f"... +{len(info) - limite} más (SIGUSR2 = modo verbose)")
    elif estado.vista == "threads":
        limite = None if verbose else 12
        recortado = info if limite is None else info[:limite]
        lineas = [
            f"tid {t['tid']:>7} {t['state']} cpu={t['cpu_pct']:>5.1f}% "
            f"vol={t['voluntary_ctxt_switches']} invol={t['nonvoluntary_ctxt_switches']} {t['comm']}"
            for t in recortado
        ]
        if limite is not None and len(info) > limite:
            lineas.append(f"... +{len(info) - limite} más (SIGUSR2 = modo verbose)")
    elif estado.vista == "senales":
        lineas = [
            f"Bloqueadas (SigBlk): {info['sig_blk']}",
            f"Ignoradas (SigIgn): {info['sig_ign']}",
            f"Con handler (SigCgt): {info['sig_cgt']}",
            f"Pendientes proceso (SigPnd): {info['sig_pnd']}",
            f"Pendientes grupo (ShdPnd): {info['shd_pnd']}",
        ]
    elif estado.vista == "scheduling":
        lineas = [
            f"nice={info['nice']} priority={info['priority']} "
            f"policy={info['policy']} rt_priority={info['rt_priority']}",
            f"cpus_allowed_list={info['cpus_allowed_list']}",
            f"ctxt switches: voluntarios={info['voluntary_ctxt_switches']} "
            f"involuntarios={info['nonvoluntary_ctxt_switches']}",
            f"session={info['session']} pgrp={info['pgrp']} "
            f"utime={info['utime']} stime={info['stime']}",
        ]
    else:
        lineas = [str(info)]

    for i, linea in enumerate(lineas[:alto_restante]):
        _addstr_seguro(win, y + i, 0, linea)


def correr_tui(stdscr, snapshot, pids_compartidos, intervalos, config, modo_verbose, manejador, dump_fn, cargar_config):
    curses.curs_set(0)      # oculta el cursor
    stdscr.nodelay(True)    # getch() no bloquea si no hay tecla
    stdscr.timeout(200)     # pero espera hasta 200ms antes de devolver -1

    estado = EstadoTUI(config)
    corriendo = True

    while corriendo:
        # las señales del monitor se chequean sin bloquear (timeout=0):
        # la TUI no puede darse el lujo de esperar a select() para redibujar
        for signum in manejador.esperar(timeout=0):
            corriendo = (
                _procesar_senal(signum, snapshot, intervalos, config, modo_verbose, dump_fn, estado, cargar_config)
                and corriendo
            )

        try:
            # si el Manager (u otro proceso) muere de golpe (kill -9, timeout
            # matando al grupo entero, etc.), el proxy de snapshot/pids_compartidos
            # explota con estos errores de conexión -- lo tratamos como "hay que
            # cerrar", no como un traceback crudo que deja la terminal rota
            procesos = lista_procesos(snapshot, estado)

            resumen_actual = snapshot.get("resumen")
            if resumen_actual:
                detectar_anomalias(estado, resumen_actual["datos"], time.time())
                actualizar_historico(estado, resumen_actual["datos"])

            tecla = stdscr.getch()
            if tecla != -1:
                corriendo = _procesar_tecla(tecla, estado, intervalos, config, procesos) and corriendo

            stdscr.erase()
            alto, ancho = stdscr.getmaxyx()

            if estado.mostrar_ayuda:
                for i, linea in enumerate(AYUDA):
                    _addstr_seguro(stdscr, i, 0, linea)
            elif estado.mostrar_jerarquia:
                resumen = snapshot.get("resumen")
                _addstr_seguro(stdscr, 0, 0, "--- Jerarquía de procesos (tipo pstree) -- 'j' para volver ---", curses.A_BOLD)
                if resumen:
                    arbol = construir_arbol(resumen["datos"])
                    for i, (pid, profundidad, cmd) in enumerate(arbol[: alto - 2]):
                        sangria = "  " * profundidad
                        _addstr_seguro(stdscr, 1 + i, 0, f"{sangria}{pid} {cmd}")
            elif estado.mostrar_comparativa:
                _dibujar_comparativa(stdscr, ancho, alto, snapshot, estado.marcados_comparar)
            else:
                y = _dibujar_lista(stdscr, ancho, alto, procesos, estado)
                if estado.modo_captura:
                    _addstr_seguro(stdscr, y, 0, f"Filtrar por {estado.modo_captura}: {estado.buffer_captura}_")
                else:
                    pid_sel = pid_seleccionado(estado, procesos)
                    _dibujar_detalle(stdscr, y, ancho, alto - y - 1, snapshot, estado, pid_sel, bool(modo_verbose.value))

            # bonus: mostrar en pantalla la última señal recibida, por 4s
            if estado.ultima_senal and time.time() - estado.ultima_senal_ts < 4.0:
                _addstr_seguro(stdscr, alto - 1, 0, f">> {estado.ultima_senal}", curses.A_REVERSE)

            stdscr.refresh()
        except (ConnectionResetError, BrokenPipeError, EOFError, OSError):
            corriendo = False
