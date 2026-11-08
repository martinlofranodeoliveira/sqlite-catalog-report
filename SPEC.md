# Contrato público · SQLite Catalog Report 1

Biblioteca e CLI Python para documentar metadados do esquema `main` de um banco SQLite local. Não copia o banco, não realiza migrações, não conta/exporta registros e não executa consultas às views ou o SQL armazenado. Os relatórios são JSON, Markdown e grafo Mermaid de FKs declaradas. Requer Python >=3.11 e SQLite >=3.37, sem dependências de execução externas à biblioteca padrão.

## Referências e alcance

- [sqlite_schema](https://www.sqlite.org/schematab.html), [PRAGMAs](https://www.sqlite.org/pragma.html), [transações](https://www.sqlite.org/lang_transaction.html), [URI](https://www.sqlite.org/uri.html), [WAL](https://www.sqlite.org/wal.html#read_only_databases), [PRIMARY KEY](https://www.sqlite.org/lang_createtable.html#the_primary_key).
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html).

O perfil captura detalhes de tabelas comuns, incluindo STRICT, WITHOUT ROWID e colunas geradas. Views, triggers, tabelas virtuais e shadow constam do inventário como definições; não são consultados para obter linhas nem submetidos à introspecção detalhada de colunas/índices. Não interpreta SQL para inventar dependências de views, expressões de índices, CHECKs ou propriedades de deferrability. O grafo é exclusivamente de FKs declaradas de tabelas comuns.

SQLite pode interpretar definições e ler suas próprias estruturas internas para fornecer PRAGMAs. O programa não oferece sandbox para vulnerabilidades do motor nativo. O modo de conexão impede DML/DDL no banco; SQLite pode gerenciar arquivos auxiliares de WAL/SHM, portanto não promete ausência absoluta de alterações auxiliares no diretório.

## API

`from sqlite_catalog_report import CatalogLimits, CatalogError, inspect_database, to_json, to_markdown, to_mermaid`

`inspect_database(path, *, include_sql=False, include_internal=False, limits=CatalogLimits()) -> dict`

`CatalogError(code, message)` para falha operacional de abertura, arquivo não regular, banco inválido/não legível, runtime incompatível, formato de saída inviável. Mensagens constantes em português, sem ecoar conteúdo SQL, caminhos absolutos ou mensagens SQLite. Argumentos inválidos levantam ValueError. Se parte da leitura já foi observada, erros de introspecção/limites devem produzir relatório `partial` com os objetos disponíveis; não apresentar conjunto truncado como catálogo completo.

Módulos e ownership:

- `model.py`: CatalogLimits, CatalogError, Issue, ordenação de achados e `ascii_fold` para equivalência de identificadores SQLite.
- `capture.py`: `capture_database(path, *, include_sql=False, include_internal=False, limits=CatalogLimits()) -> dict`, exatamente o resultado base abaixo SEM `graph` nem `catalog_sha256`. Captura não importa graph.py. A raiz compõe a API pública em api.py.
- `graph.py`: `analyze_relationships(tables, objects, *, capture_complete=True) -> dict` com relações e grupos abaixo; não acessa SQLite nem arquivos. `catalog_fingerprint(report) -> str | None` exclui campos de apresentação/ambiente.
- `report.py`: to_json/to_markdown/to_mermaid. `cli.py`: interface e publicação de arquivo novo.

## Abertura e captura

1. Aceite somente caminho de arquivo existente e regular (symlink de arquivo regular pode ser seguido). Construa URI por Path absoluto `as_uri()` + `?mode=ro`, sem interpretar texto do usuário como parâmetros URI. Não use `immutable=1`, `nolock`, ATTACH ou cópia da origem. Ausência não cria banco.
2. Conexão própria, `isolation_level=None`, timeout limitado. `PRAGMA query_only=ON` e `trusted_schema=OFF`, confirme valores. Carregamento de extensões permanece desabilitado. Não registre funções/módulos vindos do chamador, não aceite conexão externa nem SQL do usuário.
3. Abra uma transação de leitura e fixe o snapshot com a primeira leitura de `main.sqlite_schema`; mantenha todas as consultas na mesma conexão/transação até terminar. A captura deve permanecer coerente sob mudança concorrente em WAL. Feche conexão mesmo em limites/erros. Não execute integrity_check, quick_check ou foreign_key_check: eles percorrem dados.
4. Use consultas estáticas a sqlite_schema e PRAGMAs de metadados, com nomes como parâmetros nas funções pragma_table_xinfo, pragma_index_list, pragma_index_xinfo e pragma_foreign_key_list (schema main explícito). Nunca concatene identificadores sem cotação apropriada; nunca execute o campo SQL obtido. Use nomes explícitos de colunas, pois PRAGMAs podem ganhar campos.
5. Obtenha classificação/table flags via table_list, detectando capacidades reais, sem regex no CREATE TABLE. Views/triggers/virtual/shadow são inventariados; detalhes de tabelas comuns incluem generated via table_xinfo. Erro em uma definição não deve resultar em sucesso silencioso para seus detalhes. Virtual sem módulo disponível e ncol=0 pode impedir classificação de shadows; marque partial e suprima toda fase de detalhes nessa captura, preservando apenas inventário observado sem adivinhar tipos.
6. `include_internal=False` omite objetos próprios SQLite cujo nome começa com sqlite_, exceto índices automáticos associados a tabelas não internas, que são relevantes e devem aparecer. `include_internal=True` inclui esses objetos como metadados. Shadow tables continuam sem detalhes. O inventário informado só abrange objetos efetivamente incluídos.
7. Ordene por `(type, name)` com ordenação Python Unicode, colunas por cid, termos de índice por seqno, índices por nome e FKs por `(id, seq)`. Não dependa de locale, ordem implícita do SQLite ou relógio. O runtime SQLite aparece como versão explícita, mas não participa do fingerprint.

Não faça SELECT em tabelas de negócio, nem count(*), sampling, hashing dos registros, consulta da view ou execução de triggers. Testes devem observar statements e usar conteúdo canário/DDL malicioso para verificar que não se lê/exporta dados. Abertura e PRAGMAs podem preparar estruturas internas do motor, sem que isso autorize consultas a linhas de negócio.

## Limites

Inteiros com tipo exato (bool recusado), positivos exceto busy_timeout_ms que aceita zero. Tetos em model.py. Não alterar limites globais do processo SQLite.

| Campo | Padrão |
| --- | --- |
| max_objects | 5000 |
| max_detail_rows | 100000 (global: colunas + índices + termos + linhas FK) |
| max_text_bytes | 262144 por campo textual |
| max_total_text_bytes | 16777216 de texto observado |
| max_vm_steps | 2000000 |
| max_issues | 1000 |
| busy_timeout_ms | 1000 |
| max_diagram_nodes | 200 |

Consultas limitadas e fetch incremental: evite materializar resultados arbitrários antes de contar. Interrompa e marque partial em orçamento excedido, sem truncamento silencioso. O progress handler usa intervalo de 100 instruções, somado à reserva conservadora de 99 por statement para cobrir consultas curtas e sufixos sem callback. É uma estimativa superior conservadora que pode interromper antes do custo efetivo, não uma contagem exata de instruções, deadline ou limite rígido de memória/custo de preparação nativa. O SQLite pode carregar estruturas do esquema antes das contagens de resultados; não alegar limite global de memória. Após interrupção do orçamento, não repita consultas para contornar o limite.

Os bytes de SQL/default devem ser contados mesmo quando sua apresentação está ocultada. Achados também têm limite: reserve marcador issue_limit e pare; `complete=False` em qualquer truncamento. Formato Mermaid com mais nós que max_diagram_nodes falha claramente com CatalogError; não corta o grafo e não modifica o relatório JSON.

## Resultado base de captura

```json
{
  "schema_version": 1,
  "profile": "sqlite-catalog-report-v1",
  "filename": "exemplo.sqlite",
  "sqlite_version": "3.46.1",
  "options": {"include_sql": false, "include_internal": false},
  "limits": {},
  "status": "complete",
  "complete": true,
  "schema": {"schema_version": 1, "user_version": 0, "application_id": 0, "encoding": "UTF-8"},
  "summary": {"objects": 0, "ordinary_tables": 0, "views": 0, "virtual_tables": 0, "shadow_tables": 0, "indexes": 0, "triggers": 0, "detail_rows": 0},
  "objects": [],
  "tables": [],
  "issues": []
}
```

`status` complete ou partial, `complete` coincide com isso. Avisos de relações não resolvidas são fatos observados e não tornam captura incompleta por si só. Falha/limite em parte de metadados torna partial. Não inclui data, caminho absoluto, estatística de linhas ou hash do arquivo de banco.

Cada objeto:

```json
{"type":"table","sqlite_type":"table","name":"pessoas","table_name":"pessoas","sql_sha256":"...","column_count":2,"without_rowid":false,"strict":true}
```

type = table/view/virtual/shadow/index/trigger. `column_count/without_rowid/strict` são null quando não se aplicam/não puderam ser observados. `sql_sha256` é SHA-256 UTF-8 do texto SQL armazenado, ou null quando SQL é null (como índices automáticos). Com include_sql=true acrescente `sql` original ou null; sem a opção, a chave SQL não aparece. Não anonimize nomes: são conteúdo solicitado e podem ser sensíveis.

Cada tabela comum:

```json
{
 "name":"pessoas", "details_complete":true,
 "columns":[{"cid":0,"name":"id","declared_type":"INTEGER","not_null_declared":false,"primary_key_position":1,"hidden_code":0,"kind":"ordinary","default_present":false,"default_sha256":null}],
 "indexes":[{"name":"idx","unique":false,"origin":"c","partial":false,"complete":true,"terms":[{"seqno":0,"cid":0,"name":"id","kind":"column","descending":false,"collation":"BINARY","key":true}]}],
 "foreign_keys":[{"id":0,"target_table":"outra","on_update":"NO ACTION","on_delete":"NO ACTION","match":"NONE","columns":[{"seq":0,"from":"ref","to":null}]}]
}
```

`not_null_declared` preserva o flag PRAGMA, não uma conclusão geral de nullability. Coluna kind: ordinary/hidden/generated_virtual/generated_stored; códigos 0/1/2/3; desconhecido é incomplete. Default é somente presença+SHA-256; com include_sql=true acrescente default_sql (string ou null). PK preserva posição (0 quando não participa). Termos de índice distinguem cid>=0 column, -1 rowid, -2 expression; não inventar texto da expressão. key=false é coluna auxiliar. origin c/u/pk e partial são flags declarados, não prova de uso/validade do índice.

## Relações e fingerprint

`analyze_relationships` retorna:

```json
{
 "complete":true,
 "relations":[{"source":"filha","foreign_key_id":0,"target_declared":"PAI","target":"pai","source_columns":["pai_id"],"target_columns":["id"],"resolution":"resolved","on_update":"NO ACTION","on_delete":"NO ACTION","match":"NONE"}],
 "groups":[{"id":"g0","members":["pai"],"cyclic":false,"depends_on":[]},{"id":"g1","members":["filha"],"cyclic":false,"depends_on":["g0"]}],
 "layers":[["g0"],["g1"]],
 "unresolved_count":0
}
```

Identificadores são resolvidos com equivalência ASCII case-insensitive do SQLite, sem Unicode casefold. Preserve spelling declarado e nomes reais. Colunas de destino omitidas (`to` null em todas as sequências) resolvem à PK do pai na ordem da posição, com aridade exata. Referências explícitas resolvem nomes de colunas por ASCII fold. Fonte também é resolvida por nomes reais; se faltam detalhes, não declare resolved.

resolution: resolved/target_missing/target_not_table/target_not_captured/source_columns_missing/target_columns_missing/pk_arity_mismatch/metadata_inconsistent. O destino pode ser null quando não resolvido. target_columns preserva nomes explícitos disponíveis ou null para omitidos sem resolução. Ordene relações por source/id. Agrupe componentes fortemente conexos (SCC), inclusive self-loop; use algoritmo iterativo que suporte cadeias longas sem RecursionError. Condense o grafo e gere grupos/layers em ordem de dependências: pais antes de filhas, desempate por lista lexicográfica dos membros. Grupo id gN conforme ordem final, depends_on em ordem de id numérica. Layers são ondas de grupos prontos, ordenadas pelo mesmo desempate. Cyclic é dado estrutural, não erro; não executar carga/migração nem prometer que a ordem é suficiente para fazê-las.

Mesmo com referências não resolvidas, graph.complete é igual a capture_complete: significa que o conjunto observado foi analisado, não que todos os alvos existem ou dados são válidos. Se captura partial, o grafo só descreve a parcela observada. Somente resolved entra no grafo SCC; destino fora de ordinary tables não vira nó de importação inventado.

`catalog_fingerprint(report)` retorna null se report.complete ou graph.complete for false. Caso contrário SHA-256 do JSON canônico (ensure_ascii=True, sort_keys=True, separators compactos) da projeção `{"objects":...,"tables":...}`. Remova sql/default_sql recursivamente da projeção; preserve seus hashes. Exclua filename, sqlite_version, limits, options, schema counters, summary, issues e graph. Não é comparação semântica de SQL: alteração de espaços no DDL pode mudar hash. include_sql não altera fingerprint; include_internal pode mudar o conjunto e seu hash.

## CLI, relatório e entrega

`sqlite-catalog-report arquivo.sqlite [--format json|markdown|mermaid] [--include-sql] [--include-internal] [--output novo] [--max-.../--busy-timeout-ms]`; `python -m sqlite_catalog_report` equivalente. Exit0 catálogo completo; exit2 parcial; exit3 erro operacional/uso/formato; help/version0. JSON é padrão, ASCII-safe determinístico. Markdown escapa HTML/Markdown/controles Unicode de nomes e SQL e nunca incorpora SQL cru em cercas não protegidas. Mermaid usa IDs sintéticos estáveis e labels escapados para impedir que nomes virem sintaxe, sem truncamento silencioso. Grafo parcial deve ser rotulado como parcial no texto do grafo.

--output publica arquivo novo com temp no mesmo diretório + fsync + link exclusivo, nunca sobrescreve destino concorrente; falha sem fallback se filesystem não suporta. Diretório pai existente sob controle do usuário. Não promete durabilidade contra falha física. Não registra horários nem caminhos absolutos em relatórios; diagnóstico operacional não ecoa mensagens SQLite/SQL/dados.

Código/docs MIT, README PT-BR orientado a uso, exemplos inteiramente sintéticos com esquema/gerador e JSON/Markdown/Mermaid; CI Python3.11–3.14 Linux e3.14Windows; pacote wheel/sdist e ZIP de fontes em release GitHub, checksums e verificação da distribuição instalada fora da árvore. Não publicar no PyPI. Perfil GitHub: apenas atualizar catálogo/evidências, preservar README principal.
