"""
===============================================================================
 PUNTO DE ENTRADA DEL LAKEHOUSE (main.py)
===============================================================================

¿Qué es este archivo?
---------------------
Es la "puerta principal" del proyecto: el archivo que se ejecuta desde la
terminal. Ofrece dos comandos:

  * run   -> ejecuta el pipeline (carga y transforma los datos).
  * info  -> muestra el estado del lakehouse (tablas, tamaños y versiones).

Ejemplos de uso (escribir en la terminal, dentro de la carpeta del proyecto):

    uv run main.py run                          # todas las capas disponibles
    uv run main.py run --layer bronze           # solo la capa bronce
    uv run main.py run --tables product coupon  # solo algunas tablas
    uv run main.py info                         # tablas, filas y versiones
    uv run main.py --help                       # ayuda con todas las opciones

`uv run` usa el entorno de Python del proyecto, que ya tiene instaladas las
librerías necesarias (DuckDB).
"""

from __future__ import annotations

# `argparse` es la herramienta estándar de Python para leer las opciones que
# se escriben en la terminal (como `run`, `--layer bronze`, etc.).
import argparse

# `sys` da acceso a funciones del sistema; aquí se usa para devolver un
# "código de salida" al terminar (0 = todo bien, 1 = hubo errores).
import sys

from pipeline.config import settings
from pipeline.core.catalog import list_snapshots, list_tables
from pipeline.orchestrator import LAYERS, Pipeline


def cmd_run(args: argparse.Namespace) -> int:
    """Comando `run`: ejecuta el pipeline con las opciones elegidas.

    * `--layer`  indica qué capa ejecutar ("all" = todas).
    * `--tables` limita la ejecución a ciertas tablas.

    Devuelve 0 si todas las tablas se cargaron bien y 1 si alguna falló.
    Ese número le sirve a otros programas (por ejemplo, un programador de
    tareas automático) para saber si la ejecución tuvo éxito.
    """
    # Si se pidió "all" pasamos None, que el Pipeline interpreta como
    # "todas las capas"; si no, una lista con la capa pedida.
    layers = None if args.layer == "all" else [args.layer]
    results = Pipeline(layers).run(tables=args.tables)

    # `any(...)` responde: "¿hay AL MENOS UNA tabla que falló?"
    return 1 if any(r.status == "FAILED" for r in results) else 0


def cmd_info(_: argparse.Namespace) -> int:
    """Comando `info`: muestra un panorama del lakehouse.

    Imprime:
      1. Dónde están el catálogo (SQLite) y los datos (Parquet).
      2. Una tabla con cada tabla del lakehouse: filas, cantidad de archivos
         Parquet y tamaño en MB.
      3. Las últimas versiones (snapshots) guardadas, con su autor y mensaje.

    (El parámetro se llama `_` porque este comando no usa opciones extra;
    en Python el guion bajo significa "valor que no se utiliza".)
    """
    print(f"Catálogo (metadatos): {settings.CATALOG_PATH}")
    print(f"Datos (Parquet):      {settings.LAKE_DATA_PATH}\n")

    # --- Tablas del lakehouse -------------------------------------------
    print("Tablas:")
    # Usamos la función compartida del catálogo (devuelve un DataFrame de Pandas)
    df_tables = list_tables()
    if df_tables.empty:
        print("No hay tablas.")
    else:
        # to_string() imprime el DataFrame bonito en la terminal
        print(df_tables.to_string(index=False))

    print("\nÚltimos snapshots:")
    # --- Historial de versiones -----------------------------------------
    df_snapshots = list_snapshots(limit=15)
    if df_snapshots.empty:
        print("No hay versiones.")
    else:
        print(df_snapshots.to_string(index=False))

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Define qué comandos y opciones acepta el programa en la terminal.

    También genera automáticamente la ayuda que aparece con `--help`.
    """
    parser = argparse.ArgumentParser(description="Lakehouse DuckLake - pipeline medallón")

    # "Subcomandos": palabras como `run` o `info` que van justo después de
    # `main.py`. `required=True` obliga a escribir uno de ellos.
    sub = parser.add_subparsers(dest="command", required=True)

    # --- Comando `run` ---------------------------------------------------
    run = sub.add_parser("run", help="Ejecuta el pipeline")
    # `choices` limita los valores válidos: "all" o el nombre de una capa
    # registrada (hoy solo "bronze"). Si no se indica, se usa "all".
    run.add_argument("--layer", choices=["all", *LAYERS], default="all")
    # `nargs="+"` permite escribir uno o varios nombres seguidos:
    #   --tables product coupon
    run.add_argument("--tables", nargs="+", help="Limitar a estas tablas")
    # Asocia el comando `run` con la función que lo ejecuta.
    run.set_defaults(func=cmd_run)

    # --- Comando `info` --------------------------------------------------
    info = sub.add_parser("info", help="Muestra el estado del lakehouse")
    info.set_defaults(func=cmd_info)
    return parser


def main() -> int:
    """Lee lo que se escribió en la terminal y llama al comando correspondiente."""
    args = build_parser().parse_args()
    # `args.func` es `cmd_run` o `cmd_info`, según el comando elegido.
    return args.func(args)


# Este bloque solo se ejecuta cuando el archivo se corre directamente
# (`uv run main.py ...`), y no cuando otro archivo lo importa.
# `sys.exit(...)` termina el programa devolviendo el código de salida.
if __name__ == "__main__":
    sys.exit(main())
