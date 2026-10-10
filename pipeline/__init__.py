"""
Paquete principal del pipeline medallón (bronce -> plata -> oro).

Un "paquete" en Python es simplemente una carpeta con código que se puede
importar desde otros archivos. Este archivo `__init__.py` es el que le indica
a Python que la carpeta `pipeline/` es un paquete.

Organización:
    config/          -> configuración central (rutas, fuentes, opciones).
    core/            -> piezas comunes: conexión al lakehouse y molde de capas.
    layers/          -> una capa por archivo (por ahora solo bronze.py).
    orchestrator.py  -> decide qué capas se ejecutan y en qué orden.
"""
