# Como contribuir

Contribuições são bem-vindas por [issues](https://github.com/martinlofranodeoliveira/sqlite-catalog-report/issues) e pull requests. Ao relatar um problema, informe a versão do pacote, do Python e do SQLite, o comando usado e o comportamento esperado. Reproduza o problema com um esquema sintético: não anexe bancos de clientes, registros reais, caminhos pessoais ou SQL confidencial.

Para suspeitas de vulnerabilidade, siga [SECURITY.md](SECURITY.md).

## Ambiente local

Use Python 3.11 ou superior com SQLite 3.37 ou superior. Em um ambiente virtual ativado, na raiz do repositório:

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m build
python scripts/check_installed.py --wheel dist/sqlite_catalog_report-1.0.0-py3-none-any.whl
```

O runtime usa apenas a biblioteca padrão. As ferramentas de desenvolvimento são fixadas no `pyproject.toml`, incluindo `build==1.6.1` e `setuptools==84.2.1`. A verificação do wheel deve exercitar o pacote instalado fora da árvore de fontes, para detectar módulos ou recursos ausentes na distribuição.

## Prepare a alteração

Leia [SPEC.md](SPEC.md) antes de alterar captura, resolução de relações ou formato de saída. Mantenha a separação entre a leitura de metadados, a análise do grafo e a apresentação. A análise de relações não deve abrir bancos; os renderizadores não devem executar SQL.

Preserve estas propriedades:

- Nenhuma consulta às linhas das tabelas de negócio, execução de views, SQL fornecido pelo usuário ou DDL armazenado.
- Captura na mesma conexão e transação de leitura, com fechamento também em caso de erro.
- Nomes usados como parâmetros dos PRAGMAs; diagnósticos operacionais sem ecoar SQL, mensagens SQLite ou caminhos absolutos.
- Resultados ordenados e determinísticos, sem relógio, caminhos absolutos ou dependência do locale.
- Limites explícitos e sinalização `partial` quando o conjunto capturado está incompleto.
- Saídas Markdown/Mermaid escapadas e publicação de arquivo novo sem sobrescrita.

Adicione testes que demonstrem o comportamento corrigido ou a propriedade introduzida. Para captura, use bancos temporários e conteúdo canário; para grafos, prefira estruturas de metadados em memória. Inclua casos de nomes incomuns, Unicode, FKs compostas, destinos ausentes ou ciclos quando forem pertinentes à mudança. Não altere um snapshot apenas para fazê-lo coincidir com uma regressão.

O campo `not_null_declared` deve preservar o que o PRAGMA informa; não o transforme em uma inferência geral sobre nulabilidade. Não trate o fingerprint como equivalência semântica de SQL, nem grupos de dependência como um plano de carga garantido.

## Exemplos e documentação

Os arquivos em `examples/` devem continuar inteiramente sintéticos. Para gerar um banco de trabalho:

```bash
python scripts/make_sample.py --output .samples/exemplo.sqlite
```

Ao mudar o contrato público, atualize o README, [docs/FORMATO.md](docs/FORMATO.md), os exemplos afetados e os testes. Qualquer mudança de compatibilidade do formato deve ser discutida explicitamente, incluindo o efeito sobre `schema_version`, `profile` e consumidores existentes.

## Envie o pull request

Descreva o problema concreto, a mudança de comportamento e a validação realizada. Informe limitações conhecidas e os comandos efetivamente executados. Não declare testes ou plataformas como verificados sem execução correspondente.

Ao contribuir, você concorda que o código e a documentação enviados sejam distribuídos sob a [licença MIT](LICENSE) do projeto. Inclua os avisos aplicáveis quando introduzir material de terceiros.
