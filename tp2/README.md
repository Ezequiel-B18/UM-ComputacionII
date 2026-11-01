# TP2 — Plataforma de Tareas Distribuidas

Computación II — Universidad de Mendoza — 2026

Ezequiel Blajevitch

Servicio HTTP que recibe trabajos, los ejecuta de forma concurrente con
`asyncio` y permite consultar su estado y resultado.

## Estado actual

Completo: los cinco endpoints, los tres tipos de tarea, pool de workers sobre
`asyncio.Queue` con executor de procesos para lo CPU-bound, cancelación y
timeouts, apagado ordenado con volcado a JSON, Docker, y las tres mediciones.
Como extensión opcional, tests con `pytest-asyncio`.

## Descripción general

La API (FastAPI) recibe una tarea por `POST /tareas`, la registra, la pone en
una `asyncio.Queue` y responde `202` en el acto con el `id`. Un pool de N
corrutinas (workers) consume la cola y ejecuta cada tarea. El cliente consulta
el estado con `GET /tareas/{id}`, puede cancelarla con `DELETE`, y ver totales
en `/estadisticas`.

| Tarea | Naturaleza | Qué ejercita | Parámetros |
|-------|-----------|--------------|------------|
| `descargar` | I/O-bound | Concurrencia asíncrona real | `urls` (1 a 100) |
| `hashear` | CPU-bound | Que asyncio NO sirve para esto | `texto`, `iteraciones` (1 a 50.000.000), `bloqueante` (por defecto `false`) |
| `esperar` | I/O simulado | Cancelación y timeouts | `segundos` (0 a 3600) |

Las tres aceptan además `timeout` (segundos, mayor a 0). Si no se manda, se usa
`TIMEOUT_DEFECTO`.

- **`descargar`** baja todas las URLs a la vez y devuelve, por cada una,
  `estado` (código HTTP), `bytes` y `segundos`; si una URL falla, esa entrada
  trae `error` en vez de `estado`, y las demás siguen.
- **`hashear`** aplica SHA-256 `iteraciones` veces y devuelve el hash final.
- **`esperar`** duerme `segundos`.

Estados posibles: `pendiente`, `ejecutando`, `completada`, `fallida`,
`cancelada`.

### Estructura

```
tp2/
  Dockerfile  docker-compose.yml  requirements.txt  pytest.ini
  src/
    main.py          # FastAPI: endpoints y ciclo de vida (lifespan)
    modelos.py       # Estado, modelos de entrada (pydantic), dataclass Tarea
    registro.py      # Registro: todas las tareas en memoria + estadísticas
    pool.py          # Pool: cola, workers, ejecución, cancelación, apagado
    tareas.py        # esperar, descargar, hashear
    persistencia.py  # volcado a JSON
  tests/             # pytest-asyncio
  mediciones/        # medir_io.py, medir_bloqueo.py, medir_techo.py
```

## Cómo correr y probar

```bash
cd tp2
docker compose up --build
```

La API queda en `http://localhost:8000` y la documentación automática en
`http://localhost:8000/docs`.

### Ejemplos con `curl`

Encolar una tarea de cada tipo (responden `202` con `{"id": ..., "estado": "pendiente"}`):

```bash
curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' \
     -d '{"tipo": "esperar", "segundos": 5}'

curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' \
     -d '{"tipo": "descargar", "urls": ["https://www.python.org/", "http://localhost:8000/demo/lento?segundos=1"]}'

curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' \
     -d '{"tipo": "hashear", "texto": "hola", "iteraciones": 3000000}'

# con timeout propio: termina "fallida" con "timeout: superó 1.0s"
curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' \
     -d '{"tipo": "esperar", "segundos": 10, "timeout": 1}'
```

Consultar, filtrar y cancelar (`<id>` es el que devolvió el `POST`):

```bash
curl localhost:8000/tareas                    # todas
curl 'localhost:8000/tareas?estado=ejecutando' # filtradas por estado
curl localhost:8000/tareas/<id>               # una: estado, resultado, error, duracion
curl -X DELETE localhost:8000/tareas/<id>     # cancela (pendiente o ejecutando)
curl localhost:8000/estadisticas              # totales por estado, tiempo promedio, workers ocupados
curl 'localhost:8000/demo/lento?segundos=0.5&bytes=1000'  # endpoint lento local para las mediciones
```

Respuestas de error:

| Código | Cuándo |
|--------|--------|
| `404` | `GET`/`DELETE` de un `id` que no existe |
| `409` | `DELETE` de una tarea que ya terminó |
| `422` | cuerpo inválido (tipo desconocido, `segundos` negativo, etc.); lo valida pydantic |
| `503` | cola llena, o el servidor se está apagando |

### Variables de entorno

Definidas en `docker-compose.yml`, se leen en `src/main.py`:

| Variable | Defecto | Qué controla |
|----------|---------|--------------|
| `WORKERS` | 4 | Cantidad de corrutinas worker |
| `PROCESOS` | 2 | Procesos del `ProcessPoolExecutor` para `hashear` |
| `TAMANO_COLA` | 1000 | `maxsize` de la `asyncio.Queue` (más allá, `503`) |
| `TIMEOUT_DEFECTO` | 60 | Timeout en segundos si la tarea no trae uno |
| `GRACIA_APAGADO` | 10 | Segundos que se espera a las tareas en curso al apagar |
| `DIRECTORIO_DATOS` | `datos` | Dónde se escriben los volcados (en `src/persistencia.py`) |

### Tests

```bash
docker compose run --rm api pytest -q
```

### Mediciones

Con el servidor levantado (`docker compose up -d --build`):

```bash
docker compose exec api python mediciones/medir_io.py
docker compose exec api python mediciones/medir_io.py --externa https://www.python.org/
docker compose exec api python mediciones/medir_bloqueo.py
docker compose exec api python mediciones/medir_techo.py            # --solo io | --solo cpu
```

Para cambiar `WORKERS`, `PROCESOS` o `TAMANO_COLA` en una medición usamos un
archivo de override de Compose (`docker compose -f docker-compose.yml -f otro.yml up -d`).

### Ver el apagado ordenado

```bash
docker compose up -d
curl -X POST localhost:8000/tareas -H 'Content-Type: application/json' -d '{"tipo": "esperar", "segundos": 30}'
docker compose stop          # SIGTERM: espera hasta GRACIA_APAGADO y cancela lo que quede
ls datos/                    # estado_<YYYYmmdd_HHMMSS>.json
docker compose up -d
docker compose logs api | grep 'volcado previo'
# ... INFO tp2: volcado previo encontrado: datos/estado_20261101_100249.json (3 tareas)
```

Nota: en Linux, Docker crea `datos/` como `root` la primera vez que monta el
volumen; para borrar los volcados desde el host hace falta `sudo`.

## Diagrama de arquitectura

```
   Cliente HTTP
        │  POST /tareas  (responde 202 en el acto)
        ▼
 ┌─────────────────────┐   agregar(t)   ┌──────────────────────────┐
 │  FastAPI (main.py)  │───────────────>│  Registro (registro.py)  │
 │  pydantic valida    │<───────────────│  dict id -> Tarea        │
 └──────────┬──────────┘  GET / DELETE  └──────────────────────────┘
            │ put_nowait(t)                        ▲ los workers mutan
            ▼                                      │ estado/resultado
 ┌────────────────────────────┐                    │
 │ asyncio.Queue(maxsize)     │  llena -> 503      │
 └──────────┬─────────────────┘                    │
            │ await get()                          │
            ▼                                      │
 ┌────────────────────────────────────────────────┴──┐
 │  N workers (corrutinas, pool.py: Pool._worker)     │
 │    └─ por tarea: asyncio.Task interna (t.task)     │
 │         └─ async with asyncio.timeout(t.timeout):  │
 └───────┬───────────────────┬────────────────────┬───┘
         ▼                   ▼                    ▼
     esperar             descargar             hashear
  asyncio.sleep     asyncio.gather de      run_in_executor
                    cliente.get(url)        ┌────────────────────┐
                    (httpx.AsyncClient      │ ProcessPoolExecutor│
                     compartido)            │ (PROCESOS procesos)│
                                            └────────────────────┘
```

Todo lo que está arriba del executor corre en **un solo thread**, el del
event loop. Los únicos otros procesos son los del `ProcessPoolExecutor`.

Ciclo de vida de una tarea:

```
                  POST /tareas
                       │
                       ▼
                 ┌───────────┐   DELETE (en la cola)   ┌───────────┐
                 │ pendiente │────────────────────────>│           │
                 └─────┬─────┘   apagado del servidor  │           │
                       │ un worker la saca de la cola  │           │
                       ▼                               │ cancelada │
                 ┌────────────┐  DELETE (en curso)     │           │
                 │ ejecutando │───────────────────────>│           │
                 └──┬──────┬──┘  apagado (pasada la    └───────────┘
                    │      │      gracia)
      terminó bien  │      │  vence el timeout, o
                    ▼      ▼  lanza una excepción
           ┌────────────┐ ┌─────────┐
           │ completada │ │ fallida │
           └────────────┘ └─────────┘
```

`completada`, `fallida` y `cancelada` son terminales (`TERMINALES` en
`modelos.py`); un `DELETE` sobre ellas devuelve `409`.

## Decisiones de diseño

### ¿Por qué `asyncio.Queue` y no `queue.Queue`?

`queue.Queue.get()` bloquea el **thread** que la llama hasta que hay un ítem.
En asyncio hay un solo thread, el del event loop, así que un `get()` bloqueante
congelaría toda la API. `asyncio.Queue.get()` es una corrutina: si la cola está
vacía, suspende solo a ese worker y el loop sigue atendiendo pedidos.

Es el productor-consumidor de la clase 11, pero con corrutinas: el endpoint
`POST` produce y los workers de `Pool._worker` consumen. El `maxsize`
(`TAMANO_COLA`) es la contrapresión de la clase 21; la diferencia es que el
`POST` no hace `await cola.put()` (que esperaría a que haya lugar), sino
`put_nowait()`: si la cola está llena salta `asyncio.QueueFull` y respondemos
`503 cola llena`. Así el `POST` es siempre inmediato, que es lo que pide la
consigna.

### ¿Por qué no hace falta `Lock`?

Todo corre en un solo thread y el event loop solo cambia de corrutina en un
`await`. La regla de las clases 20 y 21: hace falta lock solo si la sección
crítica contiene un `await`. En `Registro` y en `Pool` ninguna mutación de
estado tiene un `await` en el medio: `self.ocupados += 1`, `t.estado = ...`,
`self.tareas[t.id] = t` se ejecutan enteras sin que nadie las interrumpa. Por
eso `registro.py` no tiene ningún lock, y lo dice en su docstring.

### ¿Cómo evitamos que una tarea CPU-bound congele la API?

`hashear` no tiene ningún `await` adentro: es un `for` de SHA-256. Si corriera
en una corrutina, el loop no recuperaría el control hasta terminar (eso es
justamente lo que mide la medición 2). Por eso `Pool._ejecutar` la manda a otro
proceso con
`await loop.run_in_executor(self.ejecutor, tareas.hashear, texto, n)`.

- **Procesos y no threads**: por el GIL (clase 10), dos threads no ejecutan
  bytecode Python a la vez. En la clase 21 medimos 4 tareas CPU-bound: 11.53 s
  con `asyncio.to_thread` contra 3.42 s con `ProcessPoolExecutor`.
- **Un solo pool**: el `ProcessPoolExecutor` se crea una vez, en el
  constructor de `Pool`, que se llama desde el `lifespan` (`ciclo` en
  `main.py`). Crear procesos es caro (clase 21), no se hace por tarea.
- **`hashear` está a nivel de módulo** en `tareas.py`: la función y sus
  argumentos viajan al otro proceso serializados con pickle, y una lambda o una
  función anidada no se pueden picklear.
- **`bloqueante=true`** hace lo contrario a propósito (llama a `hashear`
  directo dentro del loop). Existe solo para reproducir la medición 2 y está
  comentado así en `pool.py`.

### Cancelación, y qué pasa con los recursos a medio usar

Cada ejecución corre en una `asyncio.Task` **interna**, distinta del worker:
`Pool._correr` hace `t.task = asyncio.create_task(self._ejecutar(t))` y la
espera. `DELETE` cancela esa tarea interna (`t.task.cancel()` en
`Pool.cancelar`), no al worker, así que el worker sobrevive y sigue consumiendo
la cola. Lo verifica un test: después de cancelar, una tarea nueva se completa.

`cancel()` no mata nada en el momento: inyecta un `CancelledError` en el
próximo `await` de esa tarea (clase 20). Según dónde esté:

- **`esperar`**: el `asyncio.sleep` se interrumpe.
- **`descargar`**: la tarea está esperando el `asyncio.gather`; cancelarlo
  cancela cada `cliente.get` en vuelo, y httpx cierra o devuelve esas
  conexiones a su pool. `tareas.py` captura `httpx.HTTPError` pero nunca
  `CancelledError`, así que la cancelación no se traga.
- **Tarea pendiente**: todavía no tiene `t.task`. `Pool.cancelar` la marca
  `cancelada` y el worker, cuando la saca de la cola, la descarta sin
  ejecutarla.

En `_correr`, `except asyncio.CancelledError` distingue dos casos con
`asyncio.current_task().cancelling()`: si es `0`, cancelaron la tarea interna
(un `DELETE`): marcamos `cancelada` con `"cancelada por el usuario"` y el
worker sigue. Si es mayor que `0`, están cancelando **al worker mismo** (el
apagado): marcamos `cancelada` con `"apagado del servidor"` y relanzamos la
excepción para que el worker termine.

**Limitación:** un `hashear` que ya corre en un proceso del pool no se puede
interrumpir. La tarea pasa a `cancelada` en el acto y el resultado se descarta,
pero el proceso sigue calculando hasta terminar: `cancel()` sobre un `Future`
de `concurrent.futures` que ya arrancó devuelve `False` (clase 22).

### Timeouts

`Pool._ejecutar` envuelve toda la ejecución en
`async with asyncio.timeout(t.timeout):` (clase 20). Al vencer, el bloque
cancela lo que esté adentro y levanta `TimeoutError`, que `_correr` convierte
en `fallida` con el error `"timeout: superó 1.0s"`. Usa el mismo mecanismo de
cancelación de arriba, así que vale lo mismo para los recursos.

### ¿Qué pasa si un worker lanza una excepción no capturada?

Hay dos capas:

1. `Pool._correr` captura `Exception` por tarea: la tarea pasa a `fallida` con
   `"Tipo: mensaje"` en `error` y el worker sigue.
2. `Pool._worker` tiene un `except Exception` de último recurso con
   `log.exception(...)`, para errores en el propio código del pool, y el
   `cola.task_done()` va siempre en un `finally` (clase 21: si falta, un
   `join()` espera para siempre).

Sin esto, una excepción no capturada mataría la `Task` del worker en
silencio: el pool se achicaría sin que nadie se entere, y lo único visible
sería un `Task exception was never retrieved` en el log al final.

### Apagado ordenado

uvicorn ya instala los handlers de `SIGINT` y `SIGTERM` y, al recibirlos,
ejecuta el shutdown del `lifespan`. Si instaláramos los nuestros con
`loop.add_signal_handler` (como en `eco_async.py` de la clase 20)
reemplazaríamos los de uvicorn y romperíamos su propio cierre. Por eso nos
colgamos del `lifespan`: el código después del `yield` en `ciclo` es el
apagado.

`Pool.apagar(GRACIA_APAGADO)` hace, en orden:

1. `aceptando = False`: los `POST` siguientes reciben `503`.
2. Las tareas `pendiente` pasan a `cancelada` (`"apagado del servidor"`).
3. `await asyncio.wait(en_curso, timeout=gracia)`: espera a las que están
   ejecutando, con límite.
4. Cancela las que siguen corriendo.
5. Cancela los workers y espera con `gather(..., return_exceptions=True)`.
6. `ejecutor.shutdown(wait=False, cancel_futures=True)`.

Después, `ciclo` cierra el cliente (`await cliente.aclose()`) y vuelca todas
las tareas con `volcar(...)` a `datos/estado_<timestamp>.json`. Al arrancar, si
hay un volcado previo, lo informa por log con la cantidad de tareas (si el
archivo está corrupto, avisa con un warning y sigue).

En Docker: el `CMD` está en forma exec (`["python", "src/main.py"]`), así que
`python` es el PID 1 y recibe el `SIGTERM` directamente, sin un shell en el
medio. `stop_grace_period: 20s` es mayor que `GRACIA_APAGADO=10`, para que
Docker no mande `SIGKILL` antes de que terminemos.

### ¿Por qué `httpx` y no `aiohttp`?

Ya lo usamos en el curso (`medir.py` de la clase 19, `descargas.py` de la
clase 20), y su API es la de `requests` pero asíncrona. Usamos un solo
`httpx.AsyncClient`, creado en el `lifespan` y compartido por todas las
descargas: eso da pool de conexiones y keep-alive. `aiohttp` habría funcionado
igual de bien.

### `/demo/lento`

Endpoint local que duerme `segundos` y devuelve `bytes` caracteres. Sirve para
que la medición 1 no dependa de la variación de internet: la API se descarga a
sí misma.

### Sin `TaskGroup` en `descargar`

Queremos resultados parciales: una URL mala no debe cancelar a las demás.
`TaskGroup` (`grupos.py` de la clase 21) cancela a las hermanas ante la primera
excepción. Por eso cada URL captura su propio `httpx.HTTPError` en
`_bajar_una` y usamos `asyncio.gather`.

## Mediciones

Máquina: AMD Ryzen 7 5700G (8 núcleos / 16 threads), 31 GiB de RAM. Todo
corrido dentro de Docker con los scripts de `mediciones/`.

### 1. Concurrencia I/O (20 descargas)

| URL | secuencial (s) | concurrente (s) | speedup |
|---|---|---|---|
| local `/demo/lento?segundos=0.5` | 10.08 | 0.59 (tarea: 0.54) | 17.0x |
| `https://www.python.org/` | 0.86 | 0.17 (tarea: 0.16) | 5.1x |

"Secuencial" es un `for` con `await cliente.get(url)` del lado del cliente;
"concurrente" es una sola tarea `descargar` con las 20 URLs, medida de punta a
punta (y entre paréntesis, la `duracion` que reporta la propia tarea).

Secuencial tarda la suma (20 × 0.5 s ≈ 10 s); concurrente tarda lo que la más
lenta (0.5 s más overhead). El speedup ideal sería 20x; perdemos un poco en el
overhead HTTP y en el sondeo del estado. Con python.org cada respuesta ya es
rápida (unos 43 ms), así que los costos fijos (TLS, abrir la conexión) pesan
más y el speedup es menor. Es la diferencia entre `for` con `await` y
`gather`: el `for` espera cada una antes de lanzar la siguiente; `gather` las
lanza todas y espera una sola vez.

### 2. El event loop bloqueado

`hashear` de 15.000.000 iteraciones, sondeando `GET /tareas` cada 50 ms:

| modo | duración tarea (s) | sondeos | media (ms) | p95 (ms) | máx (ms) |
|---|---|---|---|---|---|
| sin executor (`bloqueante=true`) | 4.83 | 5 | 967.0 | 3851.2 | 4808.9 |
| con `ProcessPoolExecutor` | 4.80 | 97 | 1.6 | 1.9 | 2.5 |

El cálculo tarda lo mismo en los dos casos (≈4.8 s): el executor no lo
acelera. Sin executor, un `GET` esperó 4.8 s, o sea el cálculo entero: el loop
está congelado y nada avanza (ni pedidos, ni timeouts, ni los otros workers).
En ese lapso solo se completaron 5 sondeos, contra 97 con executor, donde el
máximo fue 2.5 ms. Coincide con lo que medimos en la clase 21 (4807 ms contra
6.3 ms). Ese es el punto de la materia: asyncio resuelve la espera de I/O, no
el cálculo.

### 3. Techo del pool

**(a) I/O**: N tareas `esperar(1 s)` enviadas a la vez. "ideal" es
`ceil(N / W)` segundos; "peor POST" es la latencia del `POST` más lento.

Con `WORKERS=4`, `TAMANO_COLA=1000`:

| N | total (s) | ideal ceil(N/W) (s) | tareas/s | peor POST (ms) | aceptadas | 503 |
|---|---|---|---|---|---|---|
| 10 | 3.03 | 3 | 3.3 | 12 | 10 | 0 |
| 50 | 13.04 | 13 | 3.8 | 66 | 50 | 0 |
| 100 | 25.08 | 25 | 4.0 | 162 | 100 | 0 |
| 500 | 125.24 | 125 | 4.0 | 971 | 500 | 0 |
| 1000 | 250.45 | 250 | 4.0 | 2205 | 1000 | 0 |
| 2000 | 255.76 | 255 | 4.0 | 4874 | 1020 | 980 |

Con `WORKERS=200`, `TAMANO_COLA=5000`:

| N | total (s) | ideal ceil(N/W) (s) | tareas/s | peor POST (ms) | aceptadas | 503 |
|---|---|---|---|---|---|---|
| 10 | 1.06 | 1 | 9.5 | 13 | 10 | 0 |
| 50 | 1.11 | 1 | 45.1 | 64 | 50 | 0 |
| 100 | 1.20 | 1 | 83.4 | 153 | 100 | 0 |
| 500 | 3.28 | 3 | 152.2 | 808 | 500 | 0 |
| 1000 | 5.63 | 5 | 177.5 | 1799 | 1000 | 0 |
| 2000 | 11.09 | 10 | 180.4 | 3940 | 2000 | 0 |

**(b) CPU**: N tareas `hashear(3.000.000)` a la vez, tiempo total en segundos:

| N | W=4, P=2 | W=4, P=16 | W=16, P=16 |
|---|---|---|---|
| 1 | 0.99 | 1.00 | 1.05 |
| 2 | 0.99 | 0.99 | 1.04 |
| 4 | 1.97 | 0.99 | 1.10 |
| 8 | 3.95 | 1.98 | 1.10 |

Interpretación:

- Con 4 workers el throughput es exactamente W / duración = 4 tareas/s: el
  límite es el tamaño del pool, no la CPU ni la red. Los totales medidos
  coinciden con `ceil(N/W)` con un margen de alrededor del 1 %, y la espera
  crece linealmente con la cola.
- Con N=2000 y `TAMANO_COLA=1000`, 980 `POST` recibieron `503`: la cola se
  llenó. Se aceptaron 1020: las 1000 que entran en la cola más unas 20 que los
  workers fueron sacando mientras llegaban los `POST`. Es la contrapresión
  funcionando: rechazamos en vez de crecer en memoria sin límite.
- Con 200 workers el pool deja de ser el límite, y el throughput se estanca
  cerca de 180 tareas/s en vez de llegar a 200: ahora el cuello de botella es
  el propio event loop, que tiene que parsear y responder miles de pedidos HTTP
  (los `POST` más el sondeo) en un solo thread. El "peor POST" crece
  linealmente con N por lo mismo: los pedidos hacen fila en el loop (además, el
  cliente de la medición limita a 100 conexiones simultáneas).
- CPU: el límite es el mínimo entre `WORKERS`, `PROCESOS` y núcleos. Con P=2,
  4 hashes tardan el doble. Con P=16 pero W=4, 8 hashes siguen tardando el
  doble, porque solo 4 workers pueden estar esperando al executor a la vez.
  Con W=16 y P=16, 8 hashes corren en 1.1 s: paralelismo real, hasta que se
  acaben los 8 núcleos físicos.
- **"Si te mando 10.000 tareas de golpe, ¿qué se rompe primero?"** Se llena la
  cola (`maxsize`) y empiezan los `503`. Antes de eso, crece la latencia de los
  `POST`. Y el `Registro` crece sin límite, porque las tareas terminadas nunca
  se purgan (ver limitaciones).

## Conceptos del curso aplicados

| Dónde en el código | Concepto | Clase |
|--------------------|----------|-------|
| `Pool._worker` consume de una `asyncio.Queue` compartida | Productor-consumidor, pero con corrutinas: sin lock porque el loop no interrumpe entre `await`s | 11 |
| `hashear` va a un `ProcessPoolExecutor`, no a threads | GIL: los threads no ejecutan bytecode en paralelo | 10 |
| uvicorn y httpx esperan sockets sin bloquear | El event loop usa `select`/`epoll` por debajo para saber qué socket está listo | 17 |
| Todo `async def`; cada `await` es un punto de suspensión | Corrutinas y event loop | 18 |
| `main.py`: pydantic valida el cuerpo, `HTTPException` para 404/409/503, endpoints `async def` | FastAPI; `async def` corre en el loop, `def` en un threadpool | 19 |
| `descargar` con `gather`, `asyncio.timeout`, `task.cancel()` y `CancelledError` | Concurrencia, timeouts y cancelación en asyncio | 20 |
| `Queue(maxsize)`, `task_done()` en `finally`, `run_in_executor`, `lifespan` | Asyncio avanzado | 21 |
| Un `hashear` en curso no se puede cancelar | `Future.cancel()` sobre un future que ya arrancó devuelve `False` | 22 |
| `CMD` en forma exec, `SIGTERM` al PID 1, apagado ordenado | Señales (también en el TP1) | 6 |

Dos preguntas de la consigna, en corto:

- **`gather` contra un `for` con `await`:** el `for` espera cada corrutina
  antes de crear la siguiente, así que el tiempo es la suma. `gather` las
  lanza todas como tareas y espera una sola vez, así que el tiempo es el de la
  más lenta. Es la medición 1.
- **`time.sleep()` en una corrutina es un bug:** bloquea el thread, y el thread
  es el del event loop, así que todo se detiene (es lo que muestra la
  medición 2 con `bloqueante=true`). `asyncio.sleep()` suspende solo esa
  corrutina y le devuelve el control al loop, que mientras tanto atiende a las
  demás.

## Limitaciones conocidas

- **Un `hashear` en curso no se puede interrumpir**: con `DELETE` o timeout la
  tarea queda `cancelada`/`fallida` al instante, pero el proceso sigue
  calculando y ocupa un lugar del pool hasta terminar (ver `dudas.md`).
- **El `Registro` crece sin límite**: las tareas terminadas no se purgan (no
  hay TTL).
- **El estado solo vive en memoria**: el volcado al arrancar se informa por
  log pero no se recarga, que es lo que pide la consigna.
- **`DELETE` puede responder `ejecutando`** por un instante: la cancelación se
  aplica en el próximo `await` de la tarea, no en el momento del pedido.
- **Un solo proceso de uvicorn**: el event loop es el techo (medimos unas 180
  tareas/s). Con varios procesos de uvicorn, cada uno tendría su propio
  `Registro`.
- **Sin autenticación ni rate limit.**
- **`descargar` guarda el cuerpo entero en memoria** (`r.content`) para
  contarlo; un archivo enorme usaría esa cantidad de RAM. Tampoco hay un tope
  de URLs simultáneas más allá del máximo de 100 por tarea del modelo.
- **`datos/` queda con dueño `root`** en Linux (lo crea Docker al montar el
  volumen).

## Extensiones opcionales implementadas (bonus)

**Tests con `pytest-asyncio`** (`docker compose run --rm api pytest -q`, 9
tests, menos de un segundo). Prueban el `Pool` directamente, sin HTTP, con un
`httpx.AsyncClient` real:

| Test | Qué verifica |
|------|--------------|
| `test_esperar_completa` | `esperar` termina `completada`, con `resultado` y `duracion` |
| `test_timeout_falla` | al vencer el timeout queda `fallida` con `"timeout"` en el error |
| `test_cancelar_en_curso_y_el_worker_sobrevive` | cancelar una tarea en ejecución la deja `cancelada`, `ocupados` vuelve a 0, y una tarea posterior se completa |
| `test_cancelar_pendiente_nunca_corre` | una tarea cancelada en la cola queda `cancelada` con `iniciada` en `None` |
| `test_cancelar_terminada_devuelve_false` | `cancelar` sobre una tarea terminada devuelve `False` |
| `test_hashear_en_el_ejecutor` | el hash calculado en el executor coincide con `hashlib` calculado directamente |
| `test_apagar_cancela_las_encoladas` | `apagar` cancela las encoladas con `"apagado del servidor"` y después `encolar` lanza `RuntimeError` |
| `test_cola_llena` | con la cola llena, `encolar` lanza `asyncio.QueueFull` |
| `test_volcar_y_ultimo_volcado` | el volcado a JSON y `ultimo_volcado` (en un directorio temporal) |

## Lo que aprendimos

"No bloquees el event loop" era una frase que sabíamos repetir, pero medirlo
la volvió concreta: un `GET /tareas` que tarda casi 5 segundos en responder
porque una tarea está calculando un hash, contra 2 ms cuando ese mismo
cálculo se va a otro proceso. El cálculo tarda lo mismo en los dos casos; lo
que cambia es si el resto del servidor puede seguir viviendo mientras tanto.

También entendimos que la cancelación en asyncio es cooperativa: `cancel()`
solo pide, y el `CancelledError` aparece en el próximo `await`. Eso explica a
la vez por qué cancelar una descarga es limpio (está casi siempre en un
`await`) y por qué un hash que corre en otro proceso no se puede cancelar: ahí
no hay ningún `await` donde inyectar nada.

Por último, nos sorprendió ver moverse el techo. Con pocos workers el límite
era el pool, y los números coincidían con la cuenta `ceil(N/W)` casi al
milisegundo; al subir a 200 workers el límite pasó a ser el propio event loop,
que con un solo thread tiene que atender todos los pedidos HTTP.
