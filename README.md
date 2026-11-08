# SQLite Catalog Report

Documente o esquema de um arquivo SQLite em **JSON, Markdown ou Mermaid**, sem consultar as linhas das tabelas de negócio. A biblioteca e a CLI registram tabelas, colunas, índices, chaves estrangeiras e definições de outros objetos do esquema `main`.

Útil para entregar documentação junto de um banco, revisar um esquema recebido ou visualizar suas relações declaradas. O catálogo inclui um fingerprint para identificar alterações nos metadados capturados. Não realiza migrações nem valida os dados do banco.

Projeto da [LOFRANO TECNOLOGIA](https://lofranotecnologia.com.br), com licença [MIT](LICENSE).

## Instalação

Requer **Python 3.11 ou superior** e **SQLite 3.37 ou superior** no módulo `sqlite3` desse Python. Não há dependências de execução externas à biblioteca padrão.

Os comandos abaixo usam `python`. Se o seu sistema disponibiliza apenas `python3`, use esse nome até ativar o ambiente virtual.

Confira o runtime disponível:

```bash
python --version
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

Instale a partir do código:

```bash
git clone https://github.com/martinlofranodeoliveira/sqlite-catalog-report.git
cd sqlite-catalog-report
python -m venv .venv
```

Ative o ambiente com `source .venv/bin/activate` no Linux/macOS ou `.venv\Scripts\Activate.ps1` no PowerShell e execute:

```bash
python -m pip install .
sqlite-catalog-report --version
```

Também é possível instalar um wheel obtido em [Releases](https://github.com/martinlofranodeoliveira/sqlite-catalog-report/releases):

```bash
python -m pip install ./sqlite_catalog_report-1.0.0-py3-none-any.whl
```

O projeto não é distribuído pelo PyPI.

## Uso

O formato padrão é JSON, escrito na saída padrão:

```bash
sqlite-catalog-report arquivo.sqlite
sqlite-catalog-report arquivo.sqlite --format markdown --output catalogo.md
sqlite-catalog-report arquivo.sqlite --format mermaid --output relacoes.mmd
```

`python -m sqlite_catalog_report` aceita os mesmos argumentos. `--output` exige um destino novo e um diretório pai existente. Um arquivo existente, inclusive criado por outro processo durante a publicação, não é sobrescrito. Sem `--output`, você pode redirecionar a saída com os recursos do seu shell; nesse caso, valem as regras de sobrescrita do shell.

Por padrão, o relatório contém nomes, propriedades e hashes das definições, mas omite o texto de DDL e das expressões de valores padrão. Para incluí-los:

```bash
sqlite-catalog-report arquivo.sqlite --include-sql --format markdown --output catalogo-com-ddl.md
```

**Os relatórios não são anônimos.** Nomes de tabelas, colunas e arquivos podem ser sensíveis. O SQL e os valores padrão também podem conter dados sensíveis; revise a saída antes de compartilhá-la. `--include-sql` controla a apresentação desses textos e não altera o fingerprint do catálogo.

### Experimente com um banco sintético

Na cópia do repositório:

```bash
python scripts/make_sample.py --output .samples/exemplo.sqlite
sqlite-catalog-report .samples/exemplo.sqlite --format json
sqlite-catalog-report .samples/exemplo.sqlite --format markdown
sqlite-catalog-report .samples/exemplo.sqlite --format mermaid
```

O gerador cria os diretórios pais necessários e exige um arquivo de banco novo. Consulte o [esquema de exemplo](examples/schema.sql) e as saídas em [JSON](examples/catalogo.json), [Markdown](examples/catalogo.md) e [Mermaid](examples/relacoes.mmd). Todos usam nomes e definições sintéticos.

### Opções e limites

```text
sqlite-catalog-report ARQUIVO
  --format json|markdown|mermaid
  --include-sql
  --include-internal
  --output NOVO_ARQUIVO
  --max-objects N
  --max-detail-rows N
  --max-text-bytes N
  --max-total-text-bytes N
  --max-vm-steps N
  --max-issues N
  --busy-timeout-ms N
  --max-diagram-nodes N
```

`--include-internal` acrescenta objetos SQLite com prefixo `sqlite_`. Índices automáticos das tabelas incluídas já aparecem sem essa opção. `--help` mostra os argumentos disponíveis.

| Limite | Padrão | O que controla |
| --- | ---: | --- |
| `--max-objects` | 5.000 | Objetos do inventário |
| `--max-detail-rows` | 100.000 | Soma de colunas, índices, termos de índices e linhas de FKs |
| `--max-text-bytes` | 262.144 | Bytes UTF-8 por campo textual |
| `--max-total-text-bytes` | 16.777.216 | Bytes de texto observados na captura |
| `--max-vm-steps` | 2.000.000 | Estimativa conservadora de trabalho da máquina virtual SQLite |
| `--max-issues` | 1.000 | Achados registrados |
| `--busy-timeout-ms` | 1.000 | Espera por bloqueios do SQLite, em milissegundos |
| `--max-diagram-nodes` | 200 | Tabelas comuns permitidas na saída Mermaid |

Ao atingir um limite de captura, o programa sinaliza um catálogo `partial` com os metadados já disponíveis. Um diagrama acima do limite de nós falha explicitamente, sem cortar o grafo. O orçamento de VM inclui uma reserva por consulta e pode interromper a captura antes de consumir esse número de instruções efetivas. Esses limites não são um teto rígido de memória nem um prazo máximo de execução; o SQLite pode preparar estruturas nativas antes de os resultados serem contados.

| Código de saída | Significado |
| --- | --- |
| `0` | Catálogo completo; também usado por `--help` e `--version` |
| `2` | Catálogo parcial: houve limite ou falha na captura de parte dos metadados |
| `3` | Erro de uso, abertura, runtime, formato ou publicação da saída |

Uma relação não resolvida é um achado do esquema e, por si só, não torna a captura parcial. Verifique `complete`, `issues` e `graph.unresolved_count` ao automatizar o consumo.

## Biblioteca Python

```python
from sqlite_catalog_report import CatalogLimits, inspect_database, to_json

catalogo = inspect_database(
    "arquivo.sqlite",
    include_sql=False,
    limits=CatalogLimits(max_objects=10_000),
)
print(to_json(catalogo))
```

A API também exporta `CatalogError`, `to_markdown` e `to_mermaid`. Falhas operacionais levantam `CatalogError`, com um atributo `code`; argumentos inválidos levantam `ValueError`. Uma captura parcialmente concluída retorna um relatório parcial. Veja o [contrato dos formatos](docs/FORMATO.md) para interpretar os campos e o fingerprint.

## O que o catálogo representa

- Tabelas comuns têm detalhes de colunas, índices e FKs, incluindo flags `STRICT`, `WITHOUT ROWID` e colunas geradas.
- Views, triggers, tabelas virtuais e shadow aparecem no inventário de definições. Não são consultados para obter linhas nem recebem a introspecção detalhada das tabelas comuns.
- O grafo usa exclusivamente FKs declaradas de tabelas comuns. Seus grupos identificam ciclos e suas camadas colocam dependências antes das tabelas que as referenciam. Isso descreve metadados; não garante uma ordem suficiente para carga ou migração.
- O fingerprint é do catálogo capturado, não do arquivo SQLite ou dos registros. Diferenças de espaços no DDL podem alterá-lo; ele não faz comparação semântica de SQL. Capturas parciais recebem `catalog_sha256: null`.

O programa abre o banco com `mode=ro`, ativa `query_only` e desativa `trusted_schema`. Toda a captura usa uma única transação de leitura. Não executa o SQL armazenado, consultas a views, contagens de registros, `integrity_check` ou `foreign_key_check`.

O próprio motor SQLite interpreta estruturas do esquema para fornecer metadados. Ele pode gerenciar arquivos auxiliares WAL/SHM; o projeto não promete ausência absoluta de alterações auxiliares no diretório, nem fornece sandbox para o motor nativo. Consulte [SECURITY.md](SECURITY.md) antes de processar arquivos sem procedência conhecida.

## Desenvolvimento

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m build
python scripts/check_installed.py --wheel dist/sqlite_catalog_report-1.0.0-py3-none-any.whl
```

O último comando verifica a distribuição instalada fora da árvore de fontes. Os requisitos de desenvolvimento incluem `build==1.6.1` e `setuptools==84.2.1`. Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para preparar alterações, [SPEC.md](SPEC.md) para o contrato técnico e [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) para os componentes do runtime.
