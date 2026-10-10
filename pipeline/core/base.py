"""
===============================================================================
 PIEZAS COMUNES PARA TODAS LAS CAPAS DEL PIPELINE
===============================================================================

¿Qué es un pipeline?
--------------------
Un pipeline (o "tubería") de datos es una secuencia de pasos por la que
pasan los datos, como una línea de ensamblaje: entra materia prima (los CSV)
y en cada estación se transforma un poco más hasta quedar lista para usar.

En la arquitectura medallón las estaciones son las capas:
    bronce (crudo)  ->  plata (limpio)  ->  oro (listo para el negocio)

¿Qué contiene este archivo?
---------------------------
1. Configuración de los mensajes que el programa muestra en pantalla (logs).
2. `StepResult`: una "ficha de resultado" para cada tabla procesada.
3. `Layer`: el "molde" o contrato que toda capa debe respetar.

¿Por qué un molde común?
------------------------
Si todas las capas se usan de la misma forma (todas tienen un nombre y un
método `run`), el orquestador puede ejecutarlas una tras otra sin conocer
sus detalles internos. Es como los enchufes: cualquier aparato con el
enchufe estándar funciona en cualquier toma de corriente.
"""

from __future__ import annotations

# `logging` es la herramienta estándar de Python para mostrar mensajes de
# seguimiento (qué está haciendo el programa, advertencias, errores).
import logging

# `ABC` y `abstractmethod` permiten definir "moldes" (clases abstractas):
# describen QUÉ debe hacer una clase sin decir CÓMO. Ver la clase `Layer`.
from abc import ABC, abstractmethod

# `dataclass` crea "fichas" con campos sin escribir mucho código.
from dataclasses import dataclass
from typing import Callable

import duckdb

# -----------------------------------------------------------------------------
# Formato de los mensajes en pantalla
# -----------------------------------------------------------------------------
# Cada mensaje se verá así:
#     17:47:03 | INFO    | pipeline.bronze | -> lake.bronze.product <= product.csv
#     (hora)    (nivel)   (quién lo dice)    (mensaje)
#
# Niveles más comunes: INFO (informativo), WARNING (advertencia), ERROR (fallo).
# `level=logging.INFO` indica que se muestren los mensajes INFO o más graves.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    """Devuelve un "narrador" con nombre propio para escribir mensajes.

    El nombre (p. ej. "pipeline.bronze") aparece en cada mensaje, así se
    sabe qué parte del programa lo escribió.
    """
    return logging.getLogger(name)


@dataclass
class StepResult:
    """Ficha con el resultado de procesar UNA tabla dentro de una capa.

    Es como el comprobante que entrega cada estación de la línea de
    ensamblaje. Al final, el orquestador junta todas las fichas para
    mostrar un resumen.

    Campos:
        layer:   capa que hizo el trabajo (p. ej. "bronze").
        table:   tabla procesada (p. ej. "product").
        status:  "SUCCESS" si salió bien, "FAILED" si hubo un error.
        rows:    cantidad de filas cargadas.
        seconds: tiempo que tardó, en segundos.
        error:   descripción del error si lo hubo; vacío (None) si no.
    """

    layer: str
    table: str
    status: str  # "SUCCESS" | "FAILED" | "SKIPPED"
    rows: int = 0
    seconds: float = 0.0
    error: str | None = None


class Layer(ABC):
    """Molde (clase abstracta) que deben seguir todas las capas del medallón.

    Una clase abstracta no se usa directamente: sirve de plantilla. Cada
    capa concreta (BronzeLayer, y más adelante SilverLayer y GoldLayer)
    "hereda" de este molde y completa lo que falta, en particular el método
    `run`. Si una capa olvida definir `run`, Python avisará con un error.
    """

    # Nombre de la capa. Cada capa concreta lo reemplaza (p. ej. "bronze").
    name: str = "layer"

    def __init__(self) -> None:
        # `__init__` se ejecuta automáticamente al crear la capa.
        # Aquí le damos a cada capa su propio narrador de mensajes,
        # por ejemplo "pipeline.bronze".
        self.log = get_logger(f"pipeline.{self.name}")

    # `@abstractmethod` marca este método como OBLIGATORIO para las capas
    # concretas: aquí solo se declara qué recibe y qué devuelve.
    @abstractmethod
    def run(
        self,
        con: duckdb.DuckDBPyConnection,
        batch_id: str,
        tables: list[str] | None = None,
        on_start: Callable[[str], None] | None = None,
        on_step: Callable[[StepResult], None] | None = None,
    ) -> list[StepResult]:
        """Ejecuta el trabajo de la capa.

        Parámetros:
            con:      conexión abierta al lakehouse (ver lakehouse.py).
            batch_id: identificador único de esta ejecución del pipeline.
                      Todas las tablas cargadas en una misma corrida
                      comparten el mismo batch_id, así se puede rastrear
                      qué se cargó junto.
            tables:   lista opcional para procesar solo algunas tablas.
                      Si no se indica, se procesan todas.
            on_start: función opcional que se llama al iniciar cada tabla,
                      útil para mostrar un mensaje "Cargando X...".
            on_step:  función opcional que se llama al terminar cada tabla,
                      útil para mostrar el progreso en vivo (ej. en la app).

        Devuelve:
            Una lista de `StepResult`, una ficha por cada tabla procesada.
        """
