# Segurança

Relatórios de esquema podem revelar nomes internos, nomes de arquivo e informações embutidas em definições SQL ou valores padrão. Revise-os antes de compartilhar. A opção `--include-sql` está desativada por padrão, mas isso não anonimiza os nomes ou os demais metadados.

## Relatar uma vulnerabilidade

Use o [relato privado de vulnerabilidade do GitHub](https://github.com/martinlofranodeoliveira/sqlite-catalog-report/security/advisories/new), quando disponível. Informe a versão afetada, Python/SQLite utilizados, impacto observado e uma reprodução mínima com dados sintéticos.

Se o relato privado estiver indisponível, abra uma issue solicitando um canal privado, sem incluir detalhes de exploração, arquivos suspeitos ou conteúdo sensível. Aguarde a definição desse canal para compartilhar o material. Não publique bancos de terceiros ou credenciais.

As correções de segurança são direcionadas à versão estável mais recente. Não há prazo de resposta ou manutenção de versões antigas garantido.

## Escopo das proteções

O programa aceita um arquivo local existente, abre sua conexão com `mode=ro` e exige `query_only=ON` e `trusted_schema=OFF`. A captura ocorre em uma única transação de leitura. Não aceita SQL arbitrário, conexão externa ou extensões fornecidas pelo chamador. Não executa o texto SQL armazenado nem consulta linhas de tabelas de negócio ou views.

Essas medidas reduzem a superfície de execução da aplicação, mas o SQLite ainda precisa interpretar o arquivo e suas estruturas nativas para fornecer metadados. O projeto não fornece sandbox contra vulnerabilidades do motor SQLite ou do runtime Python. Mantenha o runtime atualizado e use isolamento do sistema operacional quando a procedência do arquivo exigir.

Uma conexão de leitura pode depender de WAL/SHM, e o próprio SQLite pode gerenciar esses arquivos auxiliares. O programa não promete que nenhum arquivo auxiliar será criado ou alterado no diretório. Não use a ferramenta como mecanismo de preservação forense de mídia.

Os orçamentos restringem resultados observados, textos e uma estimativa conservadora do trabalho da máquina virtual SQLite. A reserva por statement pode interromper a captura antes de consumir o número configurado de instruções efetivas. Esses orçamentos não constituem limite rígido de memória, custo de preparação nativa ou duração total. Atingir limites de captura resulta em catálogo parcial; nenhum fingerprint completo é emitido nesse caso.

## Saídas e diagnósticos

Os renderizadores escapam metadados para seus formatos, e a publicação com `--output` exige um arquivo novo em diretório pai existente. Mantenha esse diretório sob seu controle. Uma falha de publicação é informada sem fallback de sobrescrita; não há garantia de durabilidade diante de falha física do armazenamento.

Diagnósticos operacionais não devem reproduzir SQL, conteúdo de registros, caminhos absolutos ou mensagens brutas do SQLite. Se identificar vazamento desse tipo, inclua um exemplo sintético no relato privado.
