"""Deterministic text presentations of an already captured catalog."""
import json
import re
import unicodedata

from .model import CatalogError


def to_json(report):
    return json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2,
                      allow_nan=False) + '\n'


def _visible(value, *, multiline=False):
    text = '—' if value is None else str(value)
    result = []
    for char in text:
        if multiline and char in '\n\t':
            result.append(char)
        elif unicodedata.category(char) in {'Cc', 'Cf', 'Cs', 'Zl', 'Zp'}:
            code = ord(char)
            result.append(('\\u%04x' if code <= 0xffff else '\\U%08x') % code)
        else:
            result.append(char)
    return ''.join(result)


def _md(value):
    text = _visible(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]()#+.!|~\-])', r'\\\1', text)


def _yes(value):
    return 'sim' if value is True else 'não' if value is False else 'não observado'


def _table(headers, rows):
    result = ['| ' + ' | '.join(_md(v) for v in headers) + ' |',
              '| ' + ' | '.join('---' for _ in headers) + ' |']
    result.extend('| ' + ' | '.join(_md(v) for v in row) + ' |' for row in rows)
    return '\n'.join(result)


def _sql_block(sql):
    # A stored definition cannot close this block. Controls are made visible;
    # literal HTML remains inert code, rather than an HTML element.
    text = _visible(sql, multiline=True)
    longest = max((len(run) for run in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return fence + 'sql\n' + text + '\n' + fence


def to_markdown(report):
    graph = report['graph']
    sections = ['# Catálogo SQLite',
                '**Estado:** ' + ('completo' if report['complete'] else 'PARCIAL'),
                '**Arquivo:** ' + _md(report['filename']),
                '**Runtime SQLite:** ' + _md(report['sqlite_version']),
                '**Fingerprint do catálogo:** ' + _md(report['catalog_sha256']),
                'Metadados do esquema main; não valida os registros nem executa o SQL armazenado. '
                'Nomes e definições podem conter informações sensíveis.',
                '## Resumo',
                _table(['Métrica', 'Valor'], report['summary'].items()),
                '## Inventário',
                _table(['Tipo', 'Nome', 'Tabela', 'Colunas', 'STRICT', 'WITHOUT ROWID', 'SHA-256 do SQL'],
                       ((obj['type'], obj['name'], obj['table_name'], obj['column_count'],
                         _yes(obj['strict']), _yes(obj['without_rowid']), obj['sql_sha256'])
                        for obj in report['objects']))]
    for table in report['tables']:
        sections.extend(['## Tabela: ' + _md(table['name']),
                         '**Detalhes completos:** ' + _yes(table['details_complete']),
                         '### Colunas',
                         _table(['cid', 'Nome', 'Tipo declarado', 'NOT NULL (flag)', 'Posição PK', 'Classe', 'Default presente', 'SHA-256 do default'],
                                ((c['cid'], c['name'], c['declared_type'], _yes(c['not_null_declared']),
                                  c['primary_key_position'], c['kind'], _yes(c['default_present']), c['default_sha256'])
                                 for c in table['columns'])), '### Índices'])
        for index in table['indexes']:
            sections.extend(['**' + _md(index['name']) + '** · unique=' + _yes(index['unique']) +
                             ' · origem=' + _md(index['origin']) + ' · parcial=' + _yes(index['partial']) +
                             ' · detalhes completos=' + _yes(index['complete']),
                             _table(['Ordem', 'cid', 'Nome', 'Classe', 'DESC', 'Collation', 'Chave'],
                                    ((t['seqno'], t['cid'], t['name'], t['kind'], _yes(t['descending']),
                                      t['collation'], _yes(t['key'])) for t in index['terms']))])
        if not table['indexes']:
            sections.append('Nenhum índice capturado.')
        if report['options']['include_sql']:
            for column in table['columns']:
                if column.get('default_sql') is not None:
                    sections.extend(['### Default: ' + _md(column['name']), _sql_block(column['default_sql'])])
    sections.extend(['## Relações declaradas',
                     '**Análise da captura:** ' + ('completa' if graph['complete'] else 'PARCIAL') +
                     '. **Relações não resolvidas:** ' + str(graph['unresolved_count']) + '.',
                     _table(['Origem', 'FK', 'Destino declarado', 'Destino', 'Colunas origem', 'Colunas destino', 'Resolução', 'ON UPDATE', 'ON DELETE', 'MATCH'],
                            ((r['source'], r['foreign_key_id'], r['target_declared'], r['target'],
                              json.dumps(r['source_columns'], ensure_ascii=True),
                              json.dumps(r['target_columns'], ensure_ascii=True), r['resolution'],
                              r['on_update'], r['on_delete'], r['match']) for r in graph['relations'])),
                     '### Grupos e camadas',
                     'Pais precedem filhas nas camadas; ciclos pertencem ao mesmo grupo. '
                     'Esta ordem estrutural não garante uma carga ou migração válida.',
                     _table(['Grupo', 'Tabelas', 'Cíclico', 'Depende de'],
                            ((g['id'], json.dumps(g['members'], ensure_ascii=True), _yes(g['cyclic']),
                              ', '.join(g['depends_on'])) for g in graph['groups'])),
                     _table(['Camada', 'Grupos'], ((i, ', '.join(layer)) for i, layer in enumerate(graph['layers']))),
                     '## Achados'])
    sections.append(_table(['Gravidade', 'Código', 'Objeto', 'Mensagem'],
                           ((i['severity'], i['code'], i.get('object'), i['message']) for i in report['issues']))
                    if report['issues'] else 'Nenhum achado de captura registrado.')
    if report['options']['include_sql']:
        sections.append('## Definições SQL armazenadas')
        for obj in report['objects']:
            if obj.get('sql') is not None:
                sections.extend(['### ' + _md(obj['type']) + ': ' + _md(obj['name']), _sql_block(obj['sql'])])
    return '\n\n'.join(sections) + '\n'


def _mermaid_label(value):
    # Only ASCII letters, digits and spaces are emitted literally. Everything
    # else uses Mermaid numeric entities; identifiers are always synthetic.
    return ''.join(char if (char.isascii() and (char.isalnum() or char == ' '))
                   else '#' + str(ord(char)) + ';' for char in _visible(value))


def to_mermaid(report):
    names = sorted(table['name'] for table in report['tables'])
    if len(names) > report['limits']['max_diagram_nodes']:
        raise CatalogError('diagram_limit', 'O catálogo excede o limite de nós Mermaid. Aumente o limite explicitamente ou escolha outro formato.')
    node_ids = {name: 't' + str(i) for i, name in enumerate(names)}
    lines = ['flowchart LR', '  status["' + ('Captura completa' if report['complete'] else 'Captura PARCIAL') +
             ' - ' + str(report['graph']['unresolved_count']) + ' relacoes nao resolvidas"]']
    if not names:
        lines.append('  empty["Nenhuma tabela comum capturada"]')
    for name in names:
        lines.append('  ' + node_ids[name] + '["' + _mermaid_label(name) + '"]')
    for relation in report['graph']['relations']:
        if relation['resolution'] == 'resolved':
            lines.append('  ' + node_ids[relation['source']] + ' -->|FK ' +
                         str(relation['foreign_key_id']) + '| ' + node_ids[relation['target']])
    return '\n'.join(lines) + '\n'
