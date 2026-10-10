import os
from dbt.adapters.duckdb.plugins import BasePlugin

class Plugin(BasePlugin):
    def configure_connection(self, conn):
        base_dir = os.getcwd()
        sqlite_path = os.path.join(base_dir, 'database', 'metadata.sqlite')
        data_path = os.path.join(base_dir, 'database', 'lake_data/')
        
        conn.execute("INSTALL ducklake")
        conn.execute("LOAD ducklake")
        conn.execute(f"ATTACH 'ducklake:sqlite:{sqlite_path}' AS lake (DATA_PATH '{data_path}')")
