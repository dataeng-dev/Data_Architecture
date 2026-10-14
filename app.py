"""
===============================================================================
 APLICACIÓN WEB STREAMLIT
===============================================================================

Esta es la interfaz gráfica del lakehouse. Permite ejecutar el pipeline,
ver los datos y revisar el historial, todo desde el navegador, sin usar
la terminal.
"""

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from pipeline.config import settings
from pipeline.core import catalog
from pipeline.core.base import StepResult
from pipeline.orchestrator import LAYERS, Pipeline

# -----------------------------------------------------------------------------
# Configuración inicial de la página
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Arquitectura de Datos: Ducklake",
    page_icon="🦆",
    layout="wide",
)

# -----------------------------------------------------------------------------
# Funciones auxiliares de la interfaz
# -----------------------------------------------------------------------------

def initialize_session_state():
    """Prepara las variables que sobreviven cuando el usuario hace clic.
    Streamlit borra todo y vuelve a ejecutar el código de arriba a abajo en
    cada clic. Si queremos que algo "se recuerde", hay que guardarlo en
    `st.session_state`.
    """
    if "is_running" not in st.session_state:
        # Candado: True significa que el pipeline se está ejecutando,
        # así evitamos que el usuario haga múltiples clics.
        st.session_state.is_running = False

def render_sidebar() -> str:
    """Dibuja el menú lateral y devuelve el nombre de la página seleccionada."""
    with st.sidebar:
        st.title("🦆 Arquitectura de Datos: Ducklake")
        st.markdown("### Arquitectura Medallón")
        
        # Pestañas de navegación
        page = st.radio(
            "Navegación",
            ["▶️ Ejecución (Run)", "🔎 Explorador (Catalog)", "🕰️ Historial (Logs)"],
            label_visibility="collapsed",
        )
        
        st.markdown("---")
        st.caption("Curso: Inteligencia de Negocios")
        return page

# -----------------------------------------------------------------------------
# Vistas (Páginas)
# -----------------------------------------------------------------------------

def view_run_pipeline():
    """Pestaña 1: Ejecución. Aquí el usuario pulsa 'Start' para cargar datos."""
    st.header("Ejecutar Pipeline")
    st.write("Inicia el proceso de ingesta y transformación de datos.")

    # --- Controles (Formulario) ---
    col1, col2 = st.columns(2)
    with col1:
        # Opciones: o todas ("all") o las registradas (ej. "bronze").
        layer_option = st.selectbox("Capa a ejecutar:", ["all", *LAYERS])
    
    with col2:
        # Campo opcional para escribir las tablas (ej: product coupon)
        tables_input = st.text_input("Tablas específicas (vacío = todas):", placeholder="Ej: product coupon")

    st.warning("⚠️ **Atención:** El pipeline bloquea la base de datos (SQLite). No navegues a otras pestañas hasta que termine.")

    # --- Botón de Ejecutar ---
    # Si `is_running` es True, el botón se desactiva (disabled).
    if st.button("🚀 Iniciar Ejecución", type="primary", disabled=st.session_state.is_running):
        st.session_state.is_running = True
        
        # Le decimos a Streamlit que "recargue" la pantalla ahora mismo
        # para que el botón aparezca apagado.
        st.rerun()

    # --- Lógica de Ejecución (cuando el botón fue pulsado) ---
    if st.session_state.is_running:
        st.markdown("### Progreso")
        
        # Elementos de la pantalla que iremos actualizando en vivo
        progress_text = st.empty()
        progress_bar = st.progress(0)
        logs_container = st.container()
        
        # Convierte el texto "product coupon" en una lista ["product", "coupon"]
        tables_list = tables_input.split() if tables_input.strip() else None
        layers_to_run = None if layer_option == "all" else [layer_option]

        # Variable mutable para rastrear el progreso. Cada tabla terminada
        # avanza la barra en la misma proporción (hasta 90%; el 100% se
        # marca al final).
        expected_tables = len(tables_list) if tables_list else len(settings.SOURCES)
        step_size = max(1, 90 // max(1, expected_tables))
        state = {"progress": 0}

        # Estos callbacks (`on_start`, `on_step`) se enviarán al Pipeline.
        # Sirven para que el pipeline le avise a Streamlit cómo va, sin que el
        # pipeline necesite saber nada sobre Streamlit.
        
        def handle_start(table_name: str):
            """Se llama justo antes de iniciar la carga."""
            progress_text.text(f"⏳ Cargando {table_name}... (las tablas grandes pueden tardar varios minutos)")
        
        def handle_step(result: StepResult):
            """Se llama justo después de cargar (o fallar) una tabla."""
            # Avanzamos la barra (hasta max 90%)
            state["progress"] = min(state["progress"] + step_size, 90)
            progress_bar.progress(state["progress"])

            # Escribimos en el registro visual
            with logs_container:
                if result.status == "SUCCESS":
                    st.success(f"✅ **{result.layer}.{result.table}** cargada en {result.seconds:.2f}s ({result.rows} filas).")
                elif result.status == "SKIPPED":
                    st.info(f"⏭️ **{result.layer}.{result.table}** saltada (sin cambios).")
                else:
                    st.error(f"❌ **{result.layer}.{result.table}** falló: {result.error}")

        try:
            # Ejecuta el pipeline de verdad
            start_time = time.time()
            pipeline = Pipeline(layers_to_run)
            results = pipeline.run(tables=tables_list, on_start=handle_start, on_step=handle_step)
            end_time = time.time()

            # Finalizamos la barra
            progress_bar.progress(100)
            progress_text.text(f"🎉 Proceso completado en {end_time - start_time:.2f} segundos.")
            
            # Resumen de errores
            errores = [r for r in results if r.status == "FAILED"]
            if errores:
                st.error(f"⚠️ El pipeline terminó con errores: {len(errores)} tabla(s) fallaron.")
            else:
                st.success(f"✅ Pipeline completado: {len(results)} tabla(s) cargadas sin errores.")
                
        except Exception as e:
            # Si se rompe algo muy grave en el orquestador
            st.error(f"💥 Error fatal ejecutando el pipeline: {str(e)}")
            
        finally:
            # Muy importante: quitar el candado y mostrar un botón de recarga
            st.session_state.is_running = False
            if st.button("Volver a iniciar"):
                st.rerun()


def view_catalog():
    """Pestaña 2: Explorador. Muestra las tablas y permite ver sus datos."""
    st.header("Explorador de Tablas")
    
    try:
        # Usa el catálogo compartido (ver `pipeline/core/catalog.py`)
        df_tables = catalog.list_tables()
    except Exception as e:
        st.error(f"No se pudo leer el catálogo. ¿El pipeline está corriendo?: {e}")
        return

    if df_tables.empty:
        st.info("No hay tablas registradas. Ejecuta el pipeline primero.")
        return

    # Muestra el resumen de tablas
    st.dataframe(df_tables, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Vista Previa de Datos")
    
    # Selectores para elegir qué tabla mirar
    col1, col2 = st.columns(2)
    with col1:
        # La lista desplegable se llena con los nombres que devolvió la consulta
        esquemas_disponibles = df_tables["Esquema"].unique()
        schema_sel = st.selectbox("Esquema", esquemas_disponibles)
    with col2:
        tablas_esquema = df_tables[df_tables["Esquema"] == schema_sel]["Tabla"].unique()
        table_sel = st.selectbox("Tabla", tablas_esquema)
        
    # Selector de Time Travel (Versión)
    st.markdown("##### Viaje en el tiempo (Time Travel)")
    # Traemos las versiones para dejar elegir
    df_snaps = catalog.list_snapshots()
    if not df_snaps.empty:
        # Lista de opciones: "18 - bronze: full refresh product", etc.
        snap_options = ["Última (Actual)"] + [
            f"{row['Versión']} - {row['Mensaje']} ({row['Fecha']})"
            for _, row in df_snaps.iterrows()
        ]
        version_sel = st.selectbox("Ver los datos como estaban en la versión:", snap_options)
        
        # Si no eligió "Última", extraemos el número (ej: "18") de la cadena
        version_id = None
        if version_sel != "Última (Actual)":
            version_id = int(version_sel.split(" - ")[0])
    else:
        st.info("No hay historial de versiones aún.")
        version_id = None

    if st.button("Cargar vista previa"):
        with st.spinner("Leyendo datos..."):
            try:
                # Cols y preview
                cols = catalog.table_columns(schema_sel, table_sel)
                st.write("**Estructura:**")
                # Las mostramos de forma horizontal con pills
                st.write(", ".join([f"`{row['Columna']} ({row['Tipo']})`" for _, row in cols.iterrows()]))
                
                df_preview = catalog.preview_table(schema_sel, table_sel, version=version_id, limit=50)
                st.write("**Muestra (hasta 50 filas):**")
                st.dataframe(df_preview, use_container_width=True)
            except Exception as e:
                st.error(f"Error al leer la tabla: {e}")


def view_history():
    """Pestaña 3: Historial. Muestra bitácoras y versiones guardadas."""
    st.header("Historial y Auditoría")

    tab1, tab2 = st.tabs(["Bitácora de Cargas", "Versiones del Lakehouse"])

    with tab1:
        st.markdown("Registro detallado de cada ejecución por tabla.")
        try:
            df_log = catalog.ingestion_log()
            if df_log.empty:
                st.info("No hay registros en la bitácora.")
            else:
                # Convertimos 'Fecha' para que se vea más amigable en Pandas
                if "Fecha" in df_log.columns:
                    df_log["Fecha"] = pd.to_datetime(df_log["Fecha"]).dt.strftime('%Y-%m-%d %H:%M:%S')
                
                # Función para pintar de verde o rojo según el estado
                def color_status(val):
                    color = 'green' if val == 'SUCCESS' else 'red'
                    return f'color: {color}'
                
                st.dataframe(
                    df_log.style.map(color_status, subset=['Estado']),
                    use_container_width=True, 
                    hide_index=True
                )
        except Exception as e:
             st.error(f"Error leyendo bitácora: {e}")

    with tab2:
        st.markdown("Cada *commit* en el catálogo, equivalente a Git pero para datos.")
        try:
            df_snaps = catalog.list_snapshots()
            if df_snaps.empty:
                st.info("No hay snapshots.")
            else:
                 if "Fecha" in df_snaps.columns:
                    df_snaps["Fecha"] = pd.to_datetime(df_snaps["Fecha"]).dt.strftime('%Y-%m-%d %H:%M:%S')
                 st.dataframe(df_snaps, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error leyendo snapshots: {e}")

# -----------------------------------------------------------------------------
# Arranque de la aplicación
# -----------------------------------------------------------------------------
def main():
    initialize_session_state()
    selected_page = render_sidebar()

    # Como el pipeline usa SQLite, no podemos consultar el catálogo
    # mientras SQLite está "ocupado" escribiendo datos, porque daría error de
    # "database is locked".
    # Por eso, si el pipeline se está ejecutando, ocultamos las demás páginas.
    if st.session_state.is_running and "Ejecución" not in selected_page:
        st.warning("⏳ El pipeline se está ejecutando. Por favor, espera a que termine para explorar los datos.")
        return

    # Dependiendo del menú, llama a la función de la página correspondiente
    if "Ejecución" in selected_page:
        view_run_pipeline()
    elif "Explorador" in selected_page:
        view_catalog()
    elif "Historial" in selected_page:
        view_history()

if __name__ == "__main__":
    main()
