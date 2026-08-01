# TP1 — Monitor de Procesos y Threads

Computación II — Universidad de Mendoza — 2026

Ezequiel Blajevitch

## Estado actual

En construcción. Fase 0 completada: estructura del Docker y estructura del repo.

## Descripción general



## Diagrama de arquitectura

En construcción. La arquitectura planificada (según consigna):

```
       ┌──────────────────────────────────────┐
       │           SNAPSHOT GLOBAL            │
       │      (Manager dict compartido)       │
       └────────▲─────────────────────▲───────┘
                │ escriben            │ lee
   ┌────────────┼─────────┬──────────┴────────┐
┌──▼──────┐ ┌───▼─────┐ ┌─▼──────┐  ...  ┌────▼─────┐
│Resumen  │ │Memoria  │ │FDs     │       │ Display  │
└─────────┘ └─────────┘ └────────┘       │ (TUI)    │
                                          └──────────┘
```

Todavía no existe el recolector ni los analizadores — por ahora solo hay
un `main.py` mínimo para validar el entorno de ejecución.

## Decisiones de diseño

### `pid: "host"` en `docker-compose.yml`

El contenedor comparte el namespace de PID con el sistema anfitrión. `/proc`
no es un filesystem que se monta por copia, sino una vista generada por el
kernel *según el namespace de PID del proceso que lo lee*. Sin esta opción,
el monitor solo vería los procesos internos del propio contenedor (2-3),
en vez de los procesos reales de la máquina.

Lo verifique: con `pid: host`, `main.py` reportó 504 procesos
visibles en `/proc` al correr `docker compose up --build`, muy por encima de
lo que tendría un contenedor aislado.

## Conceptos del curso aplicados

- **Namespaces de PID** (relacionado con Clase 3/4, fork y jerarquía de
  procesos): la razón por la que `/proc` dentro de un contenedor normalmente
  solo muestra un puñado de procesos, y por qué `pid: host` lo resuelve.

## Limitaciones conocidas

*(a completar cuando haya funcionalidad real que pueda fallar)*

## Cómo correr y testear

```bash
cd tp1
docker compose up --build
```

Por ahora esto solo imprime la cantidad de procesos visibles en `/proc` y
termina — todavía no hay TUI ni recolección real.
