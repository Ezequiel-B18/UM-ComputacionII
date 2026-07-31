import os
import signal
import time


def listar_pids():
    return [int(nombre) for nombre in os.listdir("/proc") if nombre.isdigit()]


def correr_recolector(pids_compartidos, intervalo=1.0):
    # solo el proceso principal decide el shutdown; este hijo ignora SIGINT
    # para no correr su propio manejador si la señal llega a todo el grupo
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while True:
        # asignación de slice (no "=") para mutar la Manager.list() in-place
        # y que los analizadores vean siempre la lista actualizada
        pids_compartidos[:] = listar_pids()
        time.sleep(intervalo)
