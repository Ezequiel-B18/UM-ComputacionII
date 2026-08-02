# Dudas / cosas que quedaron sin resolver del todo

## `docker compose up --build` no es interactivo en foreground

La consigna pide un comando único (`docker compose up --build`) que levante
todo sin pasos extra, y que el contenedor sea interactivo (`tty: true`,
`stdin_open: true`) para la TUI. Investigamos bastante y no logramos que
`docker compose up` (sin `-d`) sea plenamente interactivo:

- Con `up` en foreground, Compose multiplexa la salida y le agrega un
  prefijo de log por línea (`monitor-1  |`), que rompe visualmente el
  posicionamiento absoluto de cursor que usa `curses`.
- Probamos desactivar el menú interactivo nuevo de Compose
  (`COMPOSE_MENU=0` en `.env`) por si estaba compitiendo por el teclado —
  saca el warning de "could not start menu", pero el problema de fondo
  sigue: el teclado no le llega limpio al proceso, y lo que se ve es algo
  parecido a "local echo" mezclado con el redibujado constante de la
  pantalla.
- Con `docker attach` (después de `up -d`) sí funciona bien, pero es un
  segundo comando, y la consigna pide uno solo.

**No encontramos una forma de que la TUI sea interactiva con exactamente
`docker compose up --build` sola, en primer plano, sin pasos adicionales.**
Documentamos en el README que `docker compose run --rm monitor` es la forma
confiable de usarla interactivamente. Si hay una forma de lograr esto que se
nos escapó (algún flag de Compose, alguna configuración del servicio), nos
interesaría mucho saberlo.
