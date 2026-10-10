{{ config(
    materialized='table',
    database='lake',
    schema='bronze'
) }}

select
    *,
    current_timestamp as ingested_at,
    'causal_data.csv' as file_name,
    '{{ invocation_id }}' as batch_id
from {{ source('lake_data', 'causal_data') }}
