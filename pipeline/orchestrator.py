"""
===============================================================================
 ORQUESTADOR DEL PIPELINE MEDALLÓN
===============================================================================

¿Qué es un orquestador?
-----------------------
Así como el director de una orquesta indica a cada grupo de músicos cuándo
tocar, el orquestador decide QUÉ capas se ejecutan y EN QUÉ ORDEN.

Sus responsabilidades:
  1. Generar un identificador único para la ejecución (batch_id).
  2. Abrir la conexión al lakehouse.
  3. Ejecutar las capas en orden medallón: bronce -> plata -> oro.
  4. Cerrar la conexión, pase lo que pase.
  5. Mostrar un resumen final.

¿Cómo agregar nuevas capas?
---------------------------
Cuando existan las capas de plata y oro, basta con:
  1. Crear su archivo (p. ej. pipeline/layers/silver.py) con una clase que
     herede de `Layer` (ver core/base.py).
  2. Importarla aquí y agregarla al diccionario `LAYERS`.
"""

from __future__ import annotations

import time

# `uuid` genera códigos aleatorios prácticamente imposibles de repetir.
import uuid

# `datetime` permite trabajar con fechas y horas.
from datetime import datetime

from pipeline.core.base import Layer, StepResult, get_logger
from pipeline.core.lakehouse import get_connection
from pipeline.layers.bronze import BronzeLayer
from typing import Callable

# -----------------------------------------------------------------------------
# Registro de capas
# -----------------------------------------------------------------------------
# Diccionario {nombre: clase de la capa}. El ORDEN en que se escriben aquí es
# el orden en que se ejecutan. Las líneas que empiezan con "#" están
# "comentadas" (desactivadas) hasta que esas capas existan.
LAYERS: dict[str, type[Layer]] = {
    "bronze": BronzeLayer,
    # "silver": SilverLayer,  # pendiente
    # "gold": GoldLayer,      # pendiente
}

# Narrador de mensajes del orquestador.
log = get_logger("pipeline")


def new_batch_id() -> str:
    """Crea un identificador único para cada ejecución del pipeline.

    Formato: <fecha y hora>-<6 caracteres aleatorios>
    Ejemplo: 20261009T174702-26be92
             (9 de octubre de 2026, 17:47:02, código aleatorio 26be92)

    La fecha lo hace fácil de leer y ordenar; la parte aleatoria garantiza
    que dos ejecuciones en el mismo segundo no tengan el mismo identificador.
    """
    return f"{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


class Pipeline:
    """Representa una ejecución del pipeline con las capas elegidas.

    Uso típico:
        Pipeline(["bronze"]).run()               # solo la capa bronce
        Pipeline().run(tables=["product"])       # todas las capas, una tabla
    """

    def __init__(self, layers: list[str] | None = None) -> None:
        """Prepara el pipeline con las capas solicitadas.

        Parámetros:
            layers: nombres de las capas a ejecutar (p. ej. ["bronze"]).
                    Si no se indica, se usan todas las registradas.
        """
        # `layers or list(LAYERS)` = "usa las capas pedidas; si no se pidió
        # ninguna, usa todas las del registro".
        names = layers or list(LAYERS)

        # Validar que todas las capas pedidas existan.
        unknown = [n for n in names if n not in LAYERS]
        if unknown:
            raise ValueError(f"Capas desconocidas: {unknown}. Disponibles: {list(LAYERS)}")

        # Crear las capas respetando SIEMPRE el orden medallón del registro,
        # aunque el usuario las pida en otro orden (p. ej. "gold, bronze").
        # Así nunca se procesa oro antes que bronce.
        self.layers = [LAYERS[n]() for n in LAYERS if n in names]

    def run(
        self,
        tables: list[str] | None = None,
        on_start: Callable[[str], None] | None = None,
        on_step: Callable[[StepResult], None] | None = None,
    ) -> list[StepResult]:
        """Ejecuta las capas una tras otra y devuelve los resultados.

        Parámetros:
            tables: lista opcional para procesar solo algunas tablas.
            on_start: callback al iniciar la tabla.
            on_step: callback al terminar la tabla.

        Devuelve:
            Todas las fichas de resultado (`StepResult`) de todas las capas.
        """
        batch_id = new_batch_id()
        start = time.perf_counter()   # cronómetro de la ejecución completa
        log.info("=== Pipeline iniciado | batch=%s ===", batch_id)

        results: list[StepResult] = []
        con = get_connection()

        # `try` / `finally`: el bloque `finally` se ejecuta SIEMPRE, incluso
        # si ocurre un error. Así garantizamos que la conexión se cierre y
        # no quede el lakehouse "ocupado".
        try:
            for layer in self.layers:
                # `extend` agrega a la lista todas las fichas de esta capa.
                results.extend(layer.run(con, batch_id, tables, on_start=on_start, on_step=on_step))
        finally:
            con.close()

        self._summary(results, time.perf_counter() - start)
        return results

    @staticmethod
    def _summary(results: list[StepResult], seconds: float) -> None:
        """Muestra en pantalla una tabla resumen de la ejecución.

        Ejemplo de salida:
            bronze  product            SUCCESS          92,353 filas     0.2s
            ...
            Total: 8 tabla(s), 0 fallida(s), 5.1s
        """
        log.info("=== Resumen ===")
        for r in results:
            # Los números como `%-7s` o `%14s` solo sirven para alinear las
            # columnas del texto y que el resumen se vea ordenado.
            log.info(
                "%-7s %-18s %-8s %14s filas %7.1fs",
                r.layer, r.table, r.status, f"{r.rows:,}", r.seconds,
            )
        # Cuenta cuántas tablas fallaron.
        failed = sum(r.status == "FAILED" for r in results)
        log.info("Total: %d tabla(s), %d fallida(s), %.1fs", len(results), failed, seconds)
