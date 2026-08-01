import os
import select
import signal

SENALES_MONITOR = (
    signal.SIGINT,
    signal.SIGTERM,
    signal.SIGHUP,
    signal.SIGUSR1,
    signal.SIGUSR2,
)

# SIGTERM queda afuera a propósito: es el mecanismo que usa Process.terminate()
# del padre para matar puntualmente a este hijo. Si lo ignorara como a las
# demás, terminate() no podría cerrarlo nunca (bug real que encontramos:
# los hijos quedaban vivos para siempre después del shutdown).
SENALES_A_IGNORAR_EN_HIJO = (
    signal.SIGINT,
    signal.SIGHUP,
    signal.SIGUSR1,
    signal.SIGUSR2,
)


def ignorar_senales_en_hijo():
    # recolector y analizadores llaman esto al arrancar: la decisión de
    # qué hacer con cada señal del monitor vive SOLO en el proceso principal
    for sig in SENALES_A_IGNORAR_EN_HIJO:
        signal.signal(sig, signal.SIG_IGN)


class ManejadorSenales:
    """Patrón self-pipe (Clase 6): el handler real de cada señal solo
    escribe 1 byte a un pipe -- la única operación que necesitamos y que
    es garantizada async-signal-safe. El loop principal reacciona leyendo
    ese byte FUERA del contexto de señal, con libertad total de Python."""

    def __init__(self):
        self._r, self._w = os.pipe()
        os.set_blocking(self._r, False)

        for sig in SENALES_MONITOR:
            signal.signal(sig, self._escribir_byte)

    def _escribir_byte(self, signum, frame):
        try:
            os.write(self._w, bytes([signum]))
        except OSError:
            # pipe llena: ya hay una señal de este tipo pendiente de procesar,
            # no perdemos información relevante por descartar el byte extra
            pass

    def esperar(self, timeout):
        """Bloquea hasta `timeout` segundos o hasta que llegue una señal.
        Devuelve la lista de números de señal recibidos (puede ser vacía)."""
        listos, _, _ = select.select([self._r], [], [], timeout)
        if not listos:
            return []
        return list(os.read(self._r, 4096))
