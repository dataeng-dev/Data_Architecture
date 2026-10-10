# Documentación y Guía de Reproducibilidad (Setup)

Este documento ofrece una descripción profunda de la arquitectura de la aplicación, las decisiones de diseño tomadas y los pasos necesarios para recrear este entorno desde cero. Está pensado tanto para desarrolladores que desean extender el proyecto, como para analistas que desean consumirlo.

---

## 1. Visión General del Proyecto

Esta aplicación es una implementación local de un **Lakehouse** de última generación. En lugar de depender de grandes clústeres en la nube o complejas instalaciones de bases de datos tradicionales, este proyecto logra procesar y analizar volúmenes masivos de datos directamente en el disco duro local, combinando la velocidad analítica de **DuckDB** con el formato inmutable y estructurado del sistema de metadatos de **DuckLake**.

El caso de uso actual automatiza la ingesta de un ecosistema de datos de Retail (basado en el dataset *The Complete Journey* de Dunnhumby), estructurándolos mediante una **Arquitectura Medallón**.

### Componentes Clave
- **Motor SQL:** `DuckDB`. Procesamiento OLAP en memoria/disco extremadamente veloz.
- **Formato de Lakehouse:** `DuckLake`. Gestiona archivos Parquet en disco y utiliza un catálogo ligero en SQLite para gobernar las tablas, esquemas, estadísticas y el *Time Travel* (Versionamiento de datos).
- **Transformaciones:** `dbt-duckdb`. Orquesta y compila modelos lógicos SQL en la capa física de la base de datos, garantizando dependencias claras y tests de calidad.
- **Interfaz de Usuario (UI):** `Streamlit`. Un dashboard interactivo que rompe la barrera técnica de la terminal, permitiendo ejecutar el pipeline, explorar catálogos y navegar por los logs desde el navegador.

---

## 2. Diseño de la Arquitectura

### 2.1. Arquitectura Medallón

El proyecto divide el almacenamiento lógico y físico en capas de refinamiento:
- **Capa Bronce (Implementada):** Su propósito es almacenar una copia inmutable y fidedigna de los sistemas transaccionales. Aquí los datos se extraen de los archivos CSV originales de la carpeta `data/` y se inyectan tal cual en DuckLake a través de dbt. Una regla de negocio aplicada aquí es **garantizar que todos los campos lleguen como tipo `VARCHAR` (Texto)**, previniendo errores por colisión de tipos o inferencias erróneas en nulos o formatos de fechas mal formados.

### 2.2. Flujo de los Datos
1. Archivos crudos residen en `/data` en formato CSV.
2. El Orquestador (`pipeline/layers/bronze.py`) se inicializa.
3. El Orquestador levanta una instancia de `dbt run --select bronze`.
4. `dbt` lee los modelos definidos en `/models/bronze/` e instruye a DuckDB, vía un plugin adaptado para DuckLake (`dbt_plugin.py`), a cargar los CSV usando `read_csv_auto(..., all_varchar=true)`.
5. DuckLake encapsula el almacenamiento: divide la carga en archivos `.parquet` guardados en `database/lake_data` y guarda los metadatos en `database/metadata.sqlite`.
6. Al finalizar, el orquestador registra el volumen ingresado y los tiempos en una tabla de auditoría (`audit.ingestion_log`).

---

## 3. Prerrequisitos del Sistema

Para desplegar la aplicación en un entorno local aislado, asegúrate de contar con:
- **Python 3.11** o superior.
- **[uv](https://github.com/astral-sh/uv)**: Gestor de entornos virtuales y dependencias ultrarrápido para Python.
  - Instalación en Unix/macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Instalación en Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

---

## 4. Pasos para la Reproducibilidad

Sigue estos pasos para reproducir idénticamente el ecosistema en tu propia máquina.

### Paso 1: Clonar y Preparar Dependencias
1. Descarga los archivos del proyecto o clona el repositorio y navega hasta su raíz:
   ```bash
   cd Data_Architecture
   ```
2. Ejecuta la sincronización de `uv`. Esto creará automáticamente tu entorno virtual e instalará estrictamente las versiones definidas en el archivo `pyproject.toml` (Streamlit, dbt-core, duckdb, etc.):
   ```bash
   uv sync
   ```

### Paso 2: Inyectar la Fuente de Datos
Crea una carpeta llamada `data/` en la raíz del proyecto. El pipeline asume la existencia de los siguientes archivos CSV (Dunnhumby Complete Journey):
- `campaign_desc.csv`
- `campaign_table.csv`
- `causal_data.csv`
- `coupon.csv`
- `coupon_redempt.csv`
- `hh_demographic.csv`
- `product.csv`
- `transaction_data.csv`

*(Nota: Si omites algún archivo, los modelos dbt dependientes fallarán la validación de fuente).*

### Paso 3: Ejecutar la Orquestación de Ingesta

Construye y puebla el Lakehouse desde tu terminal ejecutando:
```bash
uv run python main.py run
```
Esta acción activará el motor y compilará la base de datos local en el directorio `database/`. 

### Paso 4: Levantar el Dashboard de Streamlit

Para evitar interactuar exclusivamente mediante SQL o comandos de terminal, el proyecto cuenta con un explorador interactivo. Inícialo ejecutando:
```bash
uv run streamlit run app.py
```
Accede desde tu navegador en `http://localhost:8501`. 

---

## 5. Descripción de la Aplicación Streamlit

La interfaz visual se construyó usando Streamlit aplicando refactorización por "Callbacks", permitiendo separar la interfaz gráfica de la lógica dura del Lakehouse. Ofrece tres pestañas:

1. **Ejecución (Run):** Permite disparar el comando `dbt` subyacente. Cuenta con manejo de estado asíncrono para bloquear la interfaz si SQLite (el motor de catálogo de DuckLake) se encuentra bloqueado, impidiendo errores de concurrencia. Una barra de progreso retroalimenta sobre la ejecución.
2. **Explorador (Catalog):** Lee los metadatos desde SQLite y DuckLake para listar tablas. Cuenta con un selector de "Time Travel", lo cual permite inyectar variables de *Macro* (`AT VERSION => x`) y consultar cómo se veía una tabla antes de su última carga.
3. **Historial (Logs):** Muestra de forma combinada la tabla de la bitácora `audit.ingestion_log` y el historial interno de commits o *snapshots* del sistema DuckLake.

---

## 6. Siguientes Pasos Evolutivos

Esta arquitectura está fuertemente estructurada para soportar las capas superiores:
- **Capa Plata (Silver):** Modelos de dbt posteriores deberán consumir el esquema `bronze`, casteando explícitamente los campos `VARCHAR` a tipos lógicos (`DATE`, `INTEGER`, `DECIMAL`), y aplicando reglas de limpieza (trim, lower) y deduplicación.
- **Capa Oro (Gold):** Construcción de vistas analíticas finales (`Fact` y `Dimension` tables) destinadas a ser la capa de consumo para las herramientas de Business Intelligence.
