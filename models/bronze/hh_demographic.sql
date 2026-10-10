{{ config(
    materialized='table',
    database='lake',
    schema='bronze'
) }}

select
    *,
    current_timestamp as ingested_at,
    'hh_demographic.csv' as file_name,
    '{{ invocation_id }}' as batch_id
from {{ source('lake_data', 'hh_demographic') }}
