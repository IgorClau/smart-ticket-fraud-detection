select card_id, nome
from {{ source('silver', 'cards') }}
