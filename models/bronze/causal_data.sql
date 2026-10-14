{{ config(
    materialized='table',
    database='lake',
    schema='bronze'
) }}

-- Capa bronce: copia fiel del CSV (todo VARCHAR) + columnas de auditoría.
-- `batch_id` lo envía el pipeline (--vars); si dbt se ejecuta a mano, se usa
-- el invocation_id de dbt.
select
    *,
    '{{ var("batch_id", invocation_id) }}' as _batch_id,
    'causal_data.csv' as _source_file,
    current_timestamp as _ingested_at
from {{ source('lake_data', 'causal_data') }}
