{{ config(
    materialized='table',
    database='lake',
    schema='bronze'
) }}

select
    *,
    current_timestamp as ingested_at,
    'coupon_redempt.csv' as file_name,
    '{{ invocation_id }}' as batch_id
from {{ source('lake_data', 'coupon_redempt') }}
