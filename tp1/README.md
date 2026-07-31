# TP1 — Monitor de Procesos y Threads

Computación II — Universidad de Mendoza — 2026

Ezequiel Blajevitch

## Estado actual

En construcción. Completo: Docker/estructura del repo, `procfs.py` (parseo de
`/proc`), recolector + 7 analizadores multiproceso con snapshot compartido.
Falta: TUI (Fase 4) y manejo completo de señales más allá de SIGINT (Fase 5).

## Descripción general

Monitor de procesos y threads de Linux, estilo `htop` pero con foco en mostrar
la anatomía interna de cada proceso (memoria, FDs, threads, señales,
scheduling), leyendo `/proc` directamente. Arquitectura multiproceso: un
recolector lista los PIDs vivos, 7 analizadores independientes extraen cada
uno una dimensión distinta en paralelo, y todos escriben a un snapshot
compartido en memoria (`Manager().dict()`). Por ahora, sin TUI, `main.py`
imprime un resumen del snapshot por consola cada 2 segundos.

## Diagrama de arquitectura

```
                    ┌──────────────────────────────────────┐
                    │           SNAPSHOT GLOBAL             │
                    │      (Manager().dict() compartido)    │
                    │  cada analizador escribe SU clave:     │
                    │  resumen / memoria / fds / threads /   │
                    │  senales / scheduling / sistema        │
                    └───────▲────────────────────────▲───────┘
                            │ escriben (7 procesos)   │ lee (main.py, luego TUI)
   ┌────────┐   ┌───────────┼──────┬─────────┬───────┴──────┬───────────┐
   │Recolec-│   │           │      │         │              │           │
   │tor     │   ▼           ▼      ▼         ▼              ▼           ▼
   │(1 proc)│ Resumen   Memoria  FDs     Threads       Senales    Scheduling  Sistema
   └───┬────┘  (2s)      (3s)   (5s)      (2s)          (10s)       (10s)     (2s)
       │
       ▼
  pids_compartidos (Manager().list())
  leído por los 7 analizadores en cada vuelta de su loop
```

Cada analizador es un `Process` independiente (no un thread) con su propio
intervalo, guardado en un `multiprocessing.Value` para poder ajustarlo en
runtime (pensado para cuando la TUI implemente `+`/`-`).

## Decisiones de diseño

### `pid: "host"` en `docker-compose.yml`

El contenedor comparte el namespace de PID con el sistema anfitrión. `/proc`
no es un filesystem que se monta por copia, sino una vista generada por el
kernel *según el namespace de PID del proceso que lo lee*. Sin esta opción,
el monitor solo vería los procesos internos del propio contenedor (2-3),
en vez de los procesos reales de la máquina.

Lo verifiqué: con `pid: host`, `main.py` reportó 504 procesos
visibles en `/proc` al correr `docker compose up --build`, muy por encima de
lo que tendría un contenedor aislado.

### `Manager().dict()` / `Manager().list()` para el estado compartido, no `Value`/`Array`

`Value` y `Array` de `multiprocessing` solo sirven para tipos C simples de
tamaño fijo (un `double`, un array de `int`) porque están respaldados
directamente por memoria compartida (`mmap`). Nuestro snapshot es una
estructura arbitraria y variable (`dict` de `dict`s de `dict`s/`list`s), así
que no entra en ese molde. `Manager()` en cambio levanta un proceso servidor
aparte que mantiene el objeto real; lo que recibe cada analizador es un
*proxy* que se ve como un dict/list normal pero por debajo hace llamadas al
servidor. Es más lento que `Value`/`Array`, pero es la única opción de la
librería estándar para datos con forma arbitraria.

Donde sí usamos `Value`: el intervalo de refresco de cada analizador es un
solo `double` — ahí `Value("d", ...)` es exactamente el caso de uso correcto,
y más liviano que meterlo en el `Manager`.

### Cómo evitamos race conditions sin usar `Lock` explícito

Cada analizador escribe **una sola clave propia** del `snapshot` (por ejemplo,
`resumen.py` solo toca `snapshot["resumen"]`). Como ningún otro proceso
escribe esa misma clave, no hay dos escritores compitiendo por el mismo dato
— el particionamiento por clave es la estrategia de sincronización en sí
misma, no hace falta un `Lock` manual encima. `Manager().dict()` además ya
serializa internamente cada operación individual (`__setitem__`), así que una
escritura de clave nunca queda a medio hacer.

Donde sí hay una fuente potencial de race condition real: el recolector
reemplaza `pids_compartidos[:] = listar_pids()` mientras los 7 analizadores
podrían estar iterando esa misma lista al mismo tiempo. La mitigamos
copiando con `list(pids_compartidos)` al principio de cada vuelta del loop
de cada analizador, antes de iterar — así cada analizador trabaja sobre una
"foto" estable de esa vuelta, en vez de iterar directo sobre un proxy que
otro proceso puede estar mutando.

### Bug real encontrado: herencia de handlers de señal en `fork()`

Al testear `Ctrl+C`, los procesos hijos (recolector y analizadores)
explotaban con su propio `KeyboardInterrupt` en vez de dejar que el proceso
principal coordinara el shutdown. La causa: `multiprocessing` en Linux usa
`fork()` por default, y el hijo hereda el handler de señal que tenía el
padre **en el momento exacto del fork**. Yo instalaba mi handler de SIGINT en
el padre *después* de `p.start()`, así que los hijos se forkeaban con el
handler default de Python (que lanza `KeyboardInterrupt`).

Fix: cada función de analizador llama
`signal.signal(signal.SIGINT, signal.SIG_IGN)` como primera línea, ignorando
la señal explícitamente. Así, sin importar cómo se propague la señal, **solo
el proceso principal reacciona** y decide el shutdown, cerrando a los hijos
ordenadamente con `terminate()` + `join()`. Esta es la versión mínima —
la Fase 5 va a reemplazar el handler del padre por un patrón self-pipe
completo, y sumar el resto de las señales (SIGHUP, SIGUSR1, SIGUSR2).

### Por qué estos intervalos por defecto

Los valores (`resumen`/`sistema`/`threads` cada 2s, `memoria` 3s, `fds` 5s,
`senales`/`scheduling` 10s) son los que pide la consigna, elegidos ahí en
función de qué tan caro es de leer cada dato y qué tan rápido cambia:
`fd` implica un `readlink` por cada file descriptor abierto (potencialmente
caro con muchos FDs), y señales/scheduling cambian con mucha menos
frecuencia que el estado de CPU o memoria de un proceso.

## Conceptos del curso aplicados

- **Namespaces de PID** (Clase 3/4, fork y jerarquía de procesos): por qué
  `/proc` dentro de un contenedor normalmente solo muestra un puñado de
  procesos, y por qué `pid: host` lo resuelve.
- **Jiffies y `HZ` del scheduler** (Clase 3): el CPU% de cada proceso se
  calcula con el delta de `utime + stime` (campos 14-15 de `/proc/<pid>/stat`)
  entre dos lecturas, convertido a segundos con `os.sysconf("SC_CLK_TCK")` —
  no asumimos que un jiffie sea "1/100 de segundo" fijo.
- **`fork()` y herencia de estado del proceso** (Clase 4): la razón exacta
  del bug de SIGINT descripto arriba — el hijo es una copia de la memoria del
  padre en el instante del fork, incluyendo la tabla de disposición de
  señales.
- **Máscaras de señales como bitmask de 64 bits** (Clase 6): `SigBlk`,
  `SigIgn`, `SigCgt` de `/proc/<pid>/status` son hex de 64 bits donde el bit
  `n-1` representa la señal POSIX número `n`. Decodificado con
  `mascara & (1 << (n - 1))` en `decodificar_mascara_senales()`.
- **Multiprocessing: `Process`, `Manager`, `Value`** (Clase 8-9): toda la
  arquitectura del recolector + analizadores + snapshot está construida
  sobre estas tres primitivas, con el criterio de elección justificado
  arriba.

## Limitaciones conocidas

- Todavía no hay TUI: `main.py` imprime el snapshot por consola en vez de
  renderizar las 7 vistas interactivas.
- El manejo de señales actual es solo SIGINT, con un handler simple (no
  async-signal-safe con patrón self-pipe todavía) que ignora la señal en los
  hijos y la maneja en el padre. Faltan SIGTERM/SIGHUP/SIGUSR1/SIGUSR2.
- Procesos de otros usuarios (o del propio contenedor sin privilegios)
  generan `PermissionError` al leer su `/status`/`/maps`/`/fd` — se
  descartan silenciosamente en vez de mostrarse con datos parciales.

## Cómo correr y testear

```bash
cd tp1
docker compose up --build
```

Por ahora imprime cada 2 segundos un resumen del snapshot (CPU/memoria/carga
del sistema y qué vistas ya tienen datos) y corre indefinidamente hasta
`Ctrl+C`, que dispara un shutdown ordenado de los 8 procesos (recolector +
7 analizadores). Todavía no hay TUI interactiva.
