import os
import time

from senales import ignorar_senales_en_hijo


def listar_pids():
    return [int(nombre) for nombre in os.listdir("/proc") if nombre.isdigit()]


def correr_recolector(pids_compartidos, intervalo=1.0):
    ignorar_senales_en_hijo()  # solo el proceso principal decide qué hacer con cada señal

    while True:
        # asignación de slice (no "=") para mutar la Manager.list() in-place
        # y que los analizadores vean siempre la lista actualizada
        pids_compartidos[:] = listar_pids()
        time.sleep(intervalo)
