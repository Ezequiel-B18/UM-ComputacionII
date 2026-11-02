# Dudas / cosas que quedaron sin resolver del todo

## ¿Se puede frenar de verdad un `hashear` en curso?

Cuando se cancela (o vence el timeout de) un `hashear` que ya está corriendo
en el `ProcessPoolExecutor`, la tarea pasa a `cancelada`/`fallida` en el acto,
pero el proceso sigue calculando hasta terminar: `cancel()` sobre un `Future`
de `concurrent.futures` que ya arrancó devuelve `False`. Consideramos tres
alternativas:

- **Matar el proceso del pool**: el `ProcessPoolExecutor` lo detecta y queda
  roto entero (`BrokenProcessPool`); habría que recrearlo, y se perderían las
  otras tareas que estuvieran en él.
- **Un flag compartido** (por ejemplo un `multiprocessing.Event` o un
  `Manager`) que `hashear` consulte cada K iteraciones y le permita cortar
  sola. Funciona, pero complica la función y hay que pasarle el flag a cada
  proceso.
- **Un proceso por tarea** (`multiprocessing.Process`) que sí se puede
  terminar con `terminate()`, a cambio de pagar la creación de un proceso cada
  vez.

Elegimos aceptar la limitación y documentarla. Nos interesaría saber cuál de
las tres sería la preferida en el curso.

## ¿Alcanza con los handlers de señales de uvicorn?

La consigna pide que `SIGTERM` y `SIGINT` provoquen un apagado ordenado. No
instalamos handlers propios con `loop.add_signal_handler` (como en
`eco_async.py` de la clase 20) porque reemplazarían los de uvicorn y romperían
su propio cierre. En cambio, uvicorn recibe la señal y ejecuta el shutdown del
`lifespan`, que es donde está nuestro apagado. Funciona (lo probamos con
`docker compose stop`), pero no sabemos si se considera suficiente o si se
esperaba ver el handler explícito.

## ¿Hay que recargar el volcado previo al arrancar?

Hoy, al arrancar, solo informamos por log el último volcado y cuántas tareas
tenía, que es lo que dice la consigna ("reportarlo por log"). No lo recargamos
en el `Registro`. Si se esperaba que las tareas volvieran a aparecer en
`GET /tareas` (y qué hacer con las que quedaron pendientes), nos gustaría
saberlo.
