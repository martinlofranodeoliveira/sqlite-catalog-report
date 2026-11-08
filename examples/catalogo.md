# Catálogo SQLite

**Estado:** completo

**Arquivo:** exemplo\.sqlite

**Runtime SQLite:** 3\.46\.1

**Fingerprint do catálogo:** a054476e92db52865ec543a9b23813ebcb09e3cf70576097177e924035c9ca33

Metadados do esquema main; não valida os registros nem executa o SQL armazenado. Nomes e definições podem conter informações sensíveis.

## Resumo

| Métrica | Valor |
| --- | --- |
| objects | 11 |
| ordinary\_tables | 6 |
| views | 1 |
| virtual\_tables | 0 |
| shadow\_tables | 0 |
| indexes | 3 |
| triggers | 1 |
| detail\_rows | 37 |

## Inventário

| Tipo | Nome | Tabela | Colunas | STRICT | WITHOUT ROWID | SHA\-256 do SQL |
| --- | --- | --- | --- | --- | --- | --- |
| index | produtos\_categoria\_nome | produtos | — | não observado | não observado | 5c51d08001d856afde80411bdd93a0fd8adbc9591cdb9e4f648151a97d0c9c8b |
| index | produtos\_nome\_parcial | produtos | — | não observado | não observado | 8cb77aa60a31acca77831c8bc8c034351e1dd82bb0ef100e4d0a571de600068b |
| index | sqlite\_autoindex\_categorias\_1 | categorias | — | não observado | não observado | — |
| table | categorias | categorias | 2 | sim | não | 69677ce54c045e8b99ccb2e8540980c6f25c351aeb766587bfe7e70424fc400c |
| table | equipes | equipes | 2 | não | não | 57f584024f7c3aa5b3233ab2da03780cf85cd6f4fe2558035ee2384a76dca4d3 |
| table | eventos | eventos | 2 | não | não | 0930e1ed253b2713aa0df0681c584ddee50f94069407939c0ac242bd5e133333 |
| table | gestores | gestores | 2 | não | não | 79492e9c2a4c40ec9dd4f5eb3fd73a64b25b5969e2a7925b5f928da118ec120e |
| table | pedidos | pedidos | 3 | sim | não | 22386c1dec1e400f85870e412956e5e6e9afe0c5139051ef0342f5fa8edd1995 |
| table | produtos | produtos | 6 | não | sim | 754a59feda1e4c32a2234ebd911c97c57f67f74352e256e1646449fa37b1df74 |
| trigger | produto\_aviso | produtos | — | não observado | não observado | 028729601bdedd569dcfc1f6e4fb94fa1ddb244442215ae2de63480ba7f8f923 |
| view | vitrine | vitrine | — | não observado | não observado | 048425816e75715fbeea21ad6ec9eff14820fbe941af0985e0e072232a4a580c |

## Tabela: categorias

**Detalhes completos:** sim

### Colunas

| cid | Nome | Tipo declarado | NOT NULL \(flag\) | Posição PK | Classe | Default presente | SHA\-256 do default |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | id | INTEGER | não | 1 | ordinary | não | — |
| 1 | nome | TEXT | sim | 0 | ordinary | não | — |

### Índices

**sqlite\_autoindex\_categorias\_1** · unique=sim · origem=u · parcial=não · detalhes completos=sim

| Ordem | cid | Nome | Classe | DESC | Collation | Chave |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | nome | column | não | BINARY | sim |
| 1 | \-1 | — | rowid | não | BINARY | não |

## Tabela: equipes

**Detalhes completos:** sim

### Colunas

| cid | Nome | Tipo declarado | NOT NULL \(flag\) | Posição PK | Classe | Default presente | SHA\-256 do default |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | id | INTEGER | não | 1 | ordinary | não | — |
| 1 | gestor\_id | INTEGER | não | 0 | ordinary | não | — |

### Índices

Nenhum índice capturado.

## Tabela: eventos

**Detalhes completos:** sim

### Colunas

| cid | Nome | Tipo declarado | NOT NULL \(flag\) | Posição PK | Classe | Default presente | SHA\-256 do default |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | id | INTEGER | não | 1 | ordinary | não | — |
| 1 | mensagem | TEXT | não | 0 | ordinary | sim | 749eb9758ad6bffb5dcfb81bcbc2325288f57aaaa42420b185f4c9757ab50fa3 |

### Índices

Nenhum índice capturado.

## Tabela: gestores

**Detalhes completos:** sim

### Colunas

| cid | Nome | Tipo declarado | NOT NULL \(flag\) | Posição PK | Classe | Default presente | SHA\-256 do default |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | id | INTEGER | não | 1 | ordinary | não | — |
| 1 | equipe\_id | INTEGER | não | 0 | ordinary | não | — |

### Índices

Nenhum índice capturado.

## Tabela: pedidos

**Detalhes completos:** sim

### Colunas

| cid | Nome | Tipo declarado | NOT NULL \(flag\) | Posição PK | Classe | Default presente | SHA\-256 do default |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | id | INTEGER | não | 1 | ordinary | não | — |
| 1 | produto\_sku | TEXT | sim | 0 | ordinary | não | — |
| 2 | quantidade | INTEGER | sim | 0 | ordinary | sim | 6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b |

### Índices

Nenhum índice capturado.

## Tabela: produtos

**Detalhes completos:** sim

### Colunas

| cid | Nome | Tipo declarado | NOT NULL \(flag\) | Posição PK | Classe | Default presente | SHA\-256 do default |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | sku | TEXT | sim | 1 | ordinary | não | — |
| 1 | categoria\_id | INTEGER | não | 0 | ordinary | não | — |
| 2 | nome | TEXT | sim | 0 | ordinary | não | — |
| 3 | preco\_centavos | INTEGER | sim | 0 | ordinary | não | — |
| 4 | nome\_busca | TEXT | não | 0 | generated\_virtual | não | — |
| 5 | preco\_dobrado | INTEGER | não | 0 | generated\_stored | não | — |

### Índices

**produtos\_categoria\_nome** · unique=sim · origem=c · parcial=não · detalhes completos=sim

| Ordem | cid | Nome | Classe | DESC | Collation | Chave |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | categoria\_id | column | não | BINARY | sim |
| 1 | 2 | nome | column | sim | NOCASE | sim |
| 2 | 0 | sku | column | não | BINARY | não |

**produtos\_nome\_parcial** · unique=não · origem=c · parcial=sim · detalhes completos=sim

| Ordem | cid | Nome | Classe | DESC | Collation | Chave |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | \-2 | — | expression | não | BINARY | sim |
| 1 | 0 | sku | column | não | BINARY | não |

**sqlite\_autoindex\_produtos\_1** · unique=sim · origem=pk · parcial=não · detalhes completos=sim

| Ordem | cid | Nome | Classe | DESC | Collation | Chave |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 | sku | column | não | BINARY | sim |
| 1 | 1 | categoria\_id | column | não | BINARY | não |
| 2 | 2 | nome | column | não | BINARY | não |
| 3 | 3 | preco\_centavos | column | não | BINARY | não |
| 4 | 5 | preco\_dobrado | column | não | BINARY | não |

## Relações declaradas

**Análise da captura:** completa. **Relações não resolvidas:** 0.

| Origem | FK | Destino declarado | Destino | Colunas origem | Colunas destino | Resolução | ON UPDATE | ON DELETE | MATCH |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| equipes | 0 | gestores | gestores | \["gestor\_id"\] | \["id"\] | resolved | NO ACTION | NO ACTION | NONE |
| gestores | 0 | equipes | equipes | \["equipe\_id"\] | \["id"\] | resolved | NO ACTION | NO ACTION | NONE |
| pedidos | 0 | produtos | produtos | \["produto\_sku"\] | \["sku"\] | resolved | CASCADE | NO ACTION | NONE |
| produtos | 0 | categorias | categorias | \["categoria\_id"\] | \["id"\] | resolved | NO ACTION | NO ACTION | NONE |

### Grupos e camadas

Pais precedem filhas nas camadas; ciclos pertencem ao mesmo grupo. Esta ordem estrutural não garante uma carga ou migração válida.

| Grupo | Tabelas | Cíclico | Depende de |
| --- | --- | --- | --- |
| g0 | \["categorias"\] | não |  |
| g1 | \["equipes", "gestores"\] | sim |  |
| g2 | \["eventos"\] | não |  |
| g3 | \["produtos"\] | não | g0 |
| g4 | \["pedidos"\] | não | g3 |

| Camada | Grupos |
| --- | --- |
| 0 | g0, g1, g2 |
| 1 | g3 |
| 2 | g4 |

## Achados

Nenhum achado de captura registrado.
