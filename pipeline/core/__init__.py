"""
Piezas comunes que usan todas las capas:
    lakehouse.py -> abre la conexión al lakehouse DuckLake (SQLite + Parquet).
    base.py      -> molde (`Layer`) y ficha de resultado (`StepResult`) de las capas.
    catalog.py   -> consultas de metadatos (tablas, versiones, bitácora) para CLI y app.
"""
