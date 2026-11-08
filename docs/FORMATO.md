# Formato do catálogo

O formato público inicial usa `schema_version: 1` e `profile: "sqlite-catalog-report-v1"`. A API retorna um dicionário; a CLI pode serializá-lo em JSON, Markdown ou Mermaid. JSON é o formato indicado para integração. O escopo é o esquema SQLite `main` de um único arquivo local.

Consulte as saídas sintéticas completas em [JSON](../examples/catalogo.json), [Markdown](../examples/catalogo.md) e [Mermaid](../examples/relacoes.mmd). [SPEC.md](../SPEC.md) contém o contrato técnico detalhado.

## Envelope JSON

| Campo | Significado |
| --- | --- |
| `schema_version` | Versão do formato deste relatório, distinta da versão de esquema interna do SQLite |
| `profile` | Perfil de captura e interpretação |
| `filename` | Nome do arquivo de origem, sem o caminho absoluto |
| `sqlite_version` | Versão do motor que realizou a captura |
| `options` | Valores de `include_sql` e `include_internal` |
| `limits` | Orçamentos usados na captura e na apresentação |
| `status` | `complete` ou `partial` |
| `complete` | `true` exatamente quando `status` é `complete` |
| `schema` | `schema_version`, `user_version`, `application_id` e `encoding` informados pelo SQLite |
| `summary` | Contagens de objetos incluídos e de detalhes observados |
| `objects` | Inventário de definições |
| `tables` | Detalhes das tabelas comuns |
| `issues` | Achados da captura; relações não resolvidas são descritas em `graph` |
| `graph` | Relações declaradas, grupos e camadas de dependência |
| `catalog_sha256` | Fingerprint do catálogo completo; `null` quando parcial |

`summary` contém `objects`, `ordinary_tables`, `views`, `virtual_tables`, `shadow_tables`, `indexes`, `triggers` e `detail_rows`. São contagens de metadados, não de registros do banco. Em um catálogo parcial, descrevem somente a parcela disponível.

Não são incluídos horário de geração, caminho absoluto, amostras, contagens de linhas ou hash do arquivo de banco. Os nomes são preservados; a ausência do caminho absoluto não constitui anonimização.

## Inventário de objetos

Cada entrada de `objects` contém:

- `type`: `table`, `view`, `virtual`, `shadow`, `index` ou `trigger`.
- `sqlite_type`: tipo registrado pelo SQLite em `sqlite_schema`.
- `name` e `table_name`: nomes preservados da origem.
- `sql_sha256`: SHA-256 do texto SQL armazenado, codificado em UTF-8; `null` quando esse texto é nulo, como em índices automáticos.
- `column_count`, `without_rowid` e `strict`: propriedades observadas; `null` quando não se aplicam ou não puderam ser obtidas.

Com `include_sql=true`, cada objeto também possui `sql`, com o texto original ou `null`. Sem essa opção, a chave é omitida. O SQL é lido como metadado e nunca executado pelo programa.

`include_internal=false` omite objetos cujo nome começa por `sqlite_`, exceto índices automáticos associados a tabelas não internas incluídas. Ativar a opção amplia o inventário; tabelas shadow continuam sem detalhes de tabela comum.

Uma definição inválida de view pode ser inventariada sem tornar a captura parcial, porque sua execução e seu detalhamento estão fora do escopo. Um módulo virtual indisponível pode impedir a observação dos metadados necessários ou a classificação das tabelas shadow. Uma tabela virtual identificada com zero colunas informadas gera captura parcial e o achado `virtual_metadata_unavailable`; o programa não adivinha a classificação de tabelas shadow pelo texto SQL.

Nesse caso, a fase de detalhes de todas as tabelas é omitida: sem o módulo, o motor pode apresentar antigas shadow como tabelas comuns. O inventário parcial preserva os tipos efetivamente informados pelo SQLite, sem promover essa classificação a uma conclusão completa.

## Detalhes de tabelas

Cada entrada de `tables` possui `name`, `details_complete`, `columns`, `indexes` e `foreign_keys`. Views, triggers, tabelas virtuais e shadow ficam no inventário e não recebem esse detalhamento.

### Colunas

| Campo | Interpretação |
| --- | --- |
| `cid` | Posição informada pelo SQLite |
| `name` | Nome da coluna |
| `declared_type` | Tipo declarado, sem inferência sobre valores armazenados |
| `not_null_declared` | Flag `notnull` fornecido pelo PRAGMA |
| `primary_key_position` | Posição na PK composta; `0` se não participa |
| `hidden_code` | Código informado pelo SQLite |
| `kind` | `ordinary`, `hidden`, `generated_virtual` ou `generated_stored` |
| `default_present` | Presença de expressão de valor padrão |
| `default_sha256` | SHA-256 UTF-8 da expressão de valor padrão, ou `null` |

Os códigos conhecidos de `hidden_code` são `0`, `1`, `2` e `3`, nessa ordem de `kind`. Código desconhecido torna os detalhes incompletos. `include_sql=true` acrescenta `default_sql`, com o texto original ou `null`; sem a opção, a chave é omitida.

`not_null_declared` preserva o flag observado e não é uma análise geral de nulabilidade. Não deduza seu valor a partir da participação na PK, nem deduza que toda coluna de PK SQLite se comporta da mesma maneira.

### Índices

Cada índice informa `name`, `unique`, `origin`, `partial`, `complete` e `terms`. `origin` preserva `c`, `u` ou `pk` conforme o SQLite. `partial` indica declaração de índice parcial, sem avaliar sua condição.

O inventário e `summary.indexes` contam entradas de `sqlite_schema`. A lista de índices de uma tabela pode conter também uma PK de tabela `WITHOUT ROWID` sem entrada correspondente nesse inventário. `complete` só é verdadeiro depois da captura válida e integral dos termos daquele índice.

Os termos possuem `seqno`, `cid`, `name`, `kind`, `descending`, `collation` e `key`. `cid >= 0` corresponde a coluna; `-1`, a `rowid`; `-2`, a expressão. `kind` distingue `column`, `rowid` e `expression`. O catálogo não inventa o texto de uma expressão a partir desses metadados. `key=false` identifica um termo auxiliar.

Essas propriedades não provam que o índice é usado em consultas nem que as linhas satisfazem uma restrição.

### Chaves estrangeiras

Cada FK contém `id`, `target_table`, `on_update`, `on_delete`, `match` e `columns`. Cada elemento de `columns` contém `seq`, `from` e `to`. `to: null` representa coluna de destino omitida na declaração, sem inventar um nome antes da resolução à PK do pai.

O catálogo preserva ações e nomes declarados. Não executa `foreign_key_check`, não verifica registros órfãos e não infere propriedades de adiamento de restrições a partir do texto SQL.

## Relações e grupos

`graph` contém `complete`, `relations`, `groups`, `layers` e `unresolved_count`. Cada relação fornece `source`, `foreign_key_id`, `target_declared`, `target`, `source_columns`, `target_columns`, `resolution`, `on_update`, `on_delete` e `match`.

Os identificadores são resolvidos segundo a equivalência ASCII sem distinção entre maiúsculas e minúsculas usada pelo SQLite, preservando a grafia declarada e a real. Não se aplica `casefold` Unicode. Destinos sem colunas explícitas são resolvidos à PK do pai em sua ordem, exigindo aridade exata.

| `resolution` | Significado |
| --- | --- |
| `resolved` | Tabelas e colunas necessárias foram resolvidas nos metadados |
| `target_missing` | O destino não está presente no inventário observado |
| `target_not_table` | O destino observado não é uma tabela comum |
| `target_not_captured` | O destino consta como tabela comum no inventário, mas está ausente do conjunto de tabelas detalhadas |
| `source_columns_missing` | Colunas da origem não puderam ser resolvidas |
| `target_columns_missing` | Colunas explícitas do destino não puderam ser resolvidas |
| `pk_arity_mismatch` | A referência implícita não corresponde à aridade da PK do pai |
| `metadata_inconsistent` | Os metadados não permitem interpretar a FK de forma consistente |

`target` pode ser `null` quando a resolução falha. `target_columns` preserva nomes explícitos disponíveis e valores nulos para destinos omitidos sem resolução. Em captura parcial, uma ausência no conjunto observado não prova ausência no arquivo completo.

Somente relações `resolved` formam o grafo de dependência. Cada grupo tem `id`, `members`, `cyclic` e `depends_on`. Grupos são componentes fortemente conexos: mais de um membro em ciclo, ou uma autorreferência, marca `cyclic=true`. Uma tabela sem ciclo também forma seu próprio grupo.

Os grupos recebem IDs `g0`, `g1`, etc. em ordem de dependências, com pais antes das tabelas que os referenciam e desempate lexicográfico dos membros. `layers` contém ondas de grupos cujas dependências já foram atendidas. São informações estruturais do esquema, não um plano garantido de importação, exclusão ou migração.

`graph.complete` acompanha a completude da captura: indica que a parcela observada foi analisada. Pode ser `true` mesmo com relações não resolvidas. Não certifica integridade referencial dos dados.

## Fingerprint

`catalog_sha256` é o SHA-256 de uma projeção canônica de `objects` e `tables`, com JSON `ensure_ascii=True`, chaves ordenadas e separadores compactos. Os campos `sql` e `default_sql` são removidos recursivamente, mas seus hashes permanecem.

Ficam fora do fingerprint: nome do arquivo, versão do SQLite, opções, limites, contadores de esquema, resumo, achados e grafo. Portanto, ativar `include_sql` não o modifica. `include_internal` pode modificar o conjunto capturado e seu hash.

O hash identifica o catálogo segundo esse perfil. Não é hash do banco, dos registros ou de um esquema normalizado semanticamente. Alterações de espaços no DDL armazenado podem mudar `sql_sha256` e o fingerprint. Se `complete` ou `graph.complete` for `false`, `catalog_sha256` é `null`.

## Completude, achados e limites

Achados têm `severity`, `code`, `message` e `object`. `severity` diferencia `incomplete` e `warning`; `object` pode ser nulo. Falhas de introspecção ou orçamento excedido tornam o catálogo parcial. Relações não resolvidas, por si sós, são avisos sobre o conjunto observado.

Os limites incluem todo texto observado, mesmo o SQL e os valores padrão omitidos da apresentação. `max_detail_rows` é global: soma colunas, índices, termos e linhas das FKs. `max_issues` também tem orçamento; um marcador de limite evita truncamento silencioso dos achados.

O orçamento `max_vm_steps` é uma estimativa superior conservadora: cada statement reserva 99 unidades e cada callback do progress handler, instalado com intervalo de 100 instruções, acrescenta outras 100. A reserva contabiliza também consultas curtas que terminam antes do primeiro callback. A captura pode ser interrompida antes de atingir esse número de instruções efetivas; o campo não é um contador exato de instruções executadas. Esse mecanismo não limita rigidamente a memória nem o trabalho nativo de preparação do SQLite. `busy_timeout_ms` controla espera por bloqueios, não o tempo total de captura.

## Apresentação

O JSON usa serialização determinística com escapes ASCII. Objetos seguem ordem `(type, name)` de strings Python Unicode; colunas seguem `cid`, índices seguem nome, termos seguem `seqno` e FKs seguem `(id, seq)`. A ordenação não depende do locale.

Markdown escapa nomes e células de tabelas. Quando solicitado, o SQL aparece em blocos de código cuja cerca tem mais backticks do que qualquer sequência no texto armazenado, impedindo seu fechamento pelo conteúdo. Controles ficam visíveis; HTML literal permanece dentro do código. Mermaid usa IDs sintéticos e labels escapados. O diagrama é baseado em FKs declaradas de tabelas comuns; se a captura for parcial, essa condição é indicada no texto do grafo.

Mermaid com mais tabelas comuns que `max_diagram_nodes` gera `CatalogError`, sem corte silencioso e sem alterar o catálogo JSON. O pequeno nó de estado é adicional a esse orçamento de tabelas. Erros de formato/publicação usam código de saída `3`; um relatório parcial emitido normalmente usa `2`; um completo usa `0`.
