"""
Tests unitarios del parseo de /proc (bonus #6 de la consigna).

Usan archivos de muestra en tests/fixtures/ en vez de leer el /proc real,
para que los tests sean deterministas y no dependan de qué esté corriendo
en la máquina que los ejecuta.
"""

import os
import sys
import unittest
from unittest.mock import mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import procfs  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _leer_fixture(nombre):
    with open(os.path.join(FIXTURES, nombre), "r") as f:
        return f.read()


class TestLeerStat(unittest.TestCase):
    def test_comm_con_parentesis_anidados(self):
        # el caso real de "(sd-pam)" -- el comm en sí tiene paréntesis,
        # por eso hay que buscar el ÚLTIMO ")" de la línea, no el primero
        contenido = _leer_fixture("stat_sd_pam")
        with patch("builtins.open", mock_open(read_data=contenido)):
            resultado = procfs.leer_stat(1212)

        self.assertEqual(resultado["comm"], "(sd-pam)")
        self.assertEqual(resultado["state"], "S")
        self.assertEqual(resultado["ppid"], 1210)

    def test_comm_con_espacio(self):
        # un comm con espacio (sin paréntesis anidados) rompería un parser
        # ingenuo que hace linea.split(" ") asumiendo que el campo 2 es
        # siempre el segundo elemento
        contenido = _leer_fixture("stat_con_espacios")
        with patch("builtins.open", mock_open(read_data=contenido)):
            resultado = procfs.leer_stat(999)

        self.assertEqual(resultado["comm"], "mi proceso")
        self.assertEqual(resultado["ppid"], 1)
        self.assertEqual(resultado["pgrp"], 999)
        self.assertEqual(resultado["session"], 999)
        self.assertEqual(resultado["minflt"], 10)
        self.assertEqual(resultado["majflt"], 2)
        self.assertEqual(resultado["utime"], 100)
        self.assertEqual(resultado["stime"], 50)
        self.assertEqual(resultado["priority"], 20)
        self.assertEqual(resultado["nice"], 0)
        self.assertEqual(resultado["num_threads"], 4)
        self.assertEqual(resultado["rt_priority"], 0)
        self.assertEqual(resultado["policy"], 0)


class TestDecodificarMascaraSenales(unittest.TestCase):
    def test_mascara_vacia(self):
        self.assertEqual(procfs.decodificar_mascara_senales("0"), [])

    def test_una_senal(self):
        # 0x2 = binario 10 -> bit 1 prendido -> señal número 2 -> SIGINT
        self.assertEqual(procfs.decodificar_mascara_senales("0000000000000002"), ["SIGINT"])

    def test_dos_senales(self):
        # 0x6 = binario 110 -> bits 1 y 2 prendidos -> señales 2 y 3
        nombres = procfs.decodificar_mascara_senales("0000000000000006")
        self.assertEqual(set(nombres), {"SIGINT", "SIGQUIT"})


class TestLeerStatus(unittest.TestCase):
    def test_campos_basicos_y_memoria(self):
        contenido = _leer_fixture("status_ejemplo")
        with patch("builtins.open", mock_open(read_data=contenido)), \
             patch("procfs.pwd.getpwuid") as mock_getpwuid:
            mock_getpwuid.return_value.pw_name = "usuario_de_prueba"
            resultado = procfs.leer_status(999)

        self.assertEqual(resultado["ppid"], 42)
        self.assertEqual(resultado["uid_real"], 1000)
        self.assertEqual(resultado["usuario"], "usuario_de_prueba")
        self.assertEqual(resultado["threads"], 3)
        self.assertEqual(resultado["vm_rss_kb"], 2048)
        self.assertEqual(resultado["vm_size_kb"], 10240)
        self.assertEqual(resultado["cpus_allowed_list"], "0-3")
        self.assertEqual(resultado["voluntary_ctxt_switches"], 5)
        self.assertEqual(resultado["nonvoluntary_ctxt_switches"], 2)

    def test_mascaras_de_senales_decodificadas(self):
        contenido = _leer_fixture("status_ejemplo")
        with patch("builtins.open", mock_open(read_data=contenido)), \
             patch("procfs.pwd.getpwuid") as mock_getpwuid:
            mock_getpwuid.return_value.pw_name = "usuario_de_prueba"
            resultado = procfs.leer_status(999)

        self.assertEqual(resultado["sig_blk"], [])
        self.assertEqual(set(resultado["sig_ign"]), {"SIGINT", "SIGQUIT"})
        self.assertEqual(resultado["sig_cgt"], ["SIGHUP"])

    def test_usuario_sin_entrada_en_passwd(self):
        # UID sin entrada en /etc/passwd (típico en contenedores minimalistas)
        # no debe crashear -- usa el UID como string de fallback
        contenido = _leer_fixture("status_ejemplo")
        with patch("builtins.open", mock_open(read_data=contenido)), \
             patch("procfs.pwd.getpwuid", side_effect=KeyError):
            resultado = procfs.leer_status(999)

        self.assertEqual(resultado["usuario"], "1000")


class TestLeerCmdline(unittest.TestCase):
    def test_argumentos_separados_por_null(self):
        crudo = b"python3\x00-c\x00print(1)\x00"
        with patch("builtins.open", mock_open(read_data=crudo)):
            resultado = procfs.leer_cmdline(1)

        self.assertEqual(resultado, "python3 -c print(1)")

    def test_proceso_sin_cmdline(self):
        # procesos kernel (ej. kworker) o zombies: cmdline vacío
        with patch("builtins.open", mock_open(read_data=b"")):
            resultado = procfs.leer_cmdline(2)

        self.assertEqual(resultado, "")

    def test_argumento_con_espacios_no_se_confunde_con_dos(self):
        # "un archivo.txt" pasado como UN solo argv no debe partirse en dos
        crudo = b"cat\x00un archivo.txt\x00"
        with patch("builtins.open", mock_open(read_data=crudo)):
            resultado = procfs.leer_cmdline(3)

        self.assertEqual(resultado, "cat un archivo.txt")


class TestLeerMaps(unittest.TestCase):
    def test_agrupa_segmentos_correctamente(self):
        contenido = _leer_fixture("maps_ejemplo")
        with patch("builtins.open", mock_open(read_data=contenido)):
            resultado = procfs.leer_maps(123)

        # tamaños elegidos en la fixture para que la aritmética sea trivial
        self.assertEqual(resultado["text"], 4)     # segmento r-xp con archivo
        self.assertEqual(resultado["data"], 4)     # segmento rw-p con archivo
        self.assertEqual(resultado["heap"], 8)     # [heap]
        self.assertEqual(resultado["stack"], 4)    # [stack]
        self.assertEqual(resultado["shared"], 12)  # anónimo sin nombre especial


class TestLeerMeminfo(unittest.TestCase):
    def test_parseo_de_meminfo(self):
        contenido = _leer_fixture("meminfo_ejemplo")
        with patch("builtins.open", mock_open(read_data=contenido)):
            resultado = procfs.leer_meminfo()

        self.assertEqual(resultado["total_kb"], 16384000)
        self.assertEqual(resultado["libre_kb"], 2048000)
        self.assertEqual(resultado["disponible_kb"], 8192000)
        self.assertEqual(resultado["cached_kb"], 4096000)
        self.assertEqual(resultado["swap_total_kb"], 2048000)


class TestLeerLoadavg(unittest.TestCase):
    def test_parseo_de_loadavg(self):
        contenido = "0.50 0.75 1.00 2/300 12345\n"
        with patch("builtins.open", mock_open(read_data=contenido)):
            resultado = procfs.leer_loadavg()

        self.assertEqual(resultado["load_1min"], 0.50)
        self.assertEqual(resultado["load_5min"], 0.75)
        self.assertEqual(resultado["load_15min"], 1.00)
        self.assertEqual(resultado["en_ejecucion_total"], "2/300")


if __name__ == "__main__":
    unittest.main()
