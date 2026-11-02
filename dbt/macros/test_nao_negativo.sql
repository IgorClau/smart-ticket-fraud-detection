{# Teste genérico: nenhuma linha com valor negativo. #}
{% test nao_negativo(model, column_name) %}
select * from {{ model }} where {{ column_name }} < 0
{% endtest %}
