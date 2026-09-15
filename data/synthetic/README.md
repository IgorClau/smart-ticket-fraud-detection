# data/synthetic — bases de referência do gerador e da silver

`bases/` contém os 19 arquivos oficiais usados para gerar e validar os extratos:

- `trajetos_e_tarifas_<operadora>.xlsx` — trajetos e tarifas (6 operadoras);
- `codigos_linhas_<operadora>.xlsx` — código de itinerário e tipo (municipal/intermunicipal);
- `Matricula_dos_carros_DETRAN_<operadora>.xlsx` — frota ativa por tipo de rota;
- `Lista_150_empresas_organizadas.txt` — empregadoras por setor (define o perfil de data da recarga).

Usos:

1. **Gerador** (`src/data_generator`): linhas, tarifas, carros e empresas de cada extrato vêm só daqui.
2. **Silver** (`src/data_pipeline/reference.py`): vira `dim_linha`, `dim_veiculo` e `dim_empresa`, que
   enriquecem as transações (tarifa de tabela, veículo na frota) e alimentam checagens de qualidade.
