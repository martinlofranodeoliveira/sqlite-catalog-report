"""Read a bounded, schema-only catalog through a private read-only connection.

The SQL below is deliberately static. Names obtained from the catalog are bound
arguments to metadata PRAGMA functions, never executable SQL or identifiers.
SQLite may itself prepare schema definitions and read internal structures while
implementing these PRAGMAs; this module is not a sandbox for the native engine.
"""

from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import sys

from .model import CatalogError, CatalogLimits, Issue, sort_issues


_OBJECTS = """SELECT type, name, tbl_name, sql FROM main.sqlite_schema
WHERE (? OR substr(name, 1, 7) != 'sqlite_'
       OR (type = 'index' AND substr(tbl_name, 1, 7) != 'sqlite_'))
ORDER BY type, name LIMIT ?"""
_TABLE_FLAGS = """SELECT name, type, ncol, wr, strict
FROM pragma_table_list(?) WHERE schema = 'main' LIMIT 2"""
_COLUMNS = """SELECT cid, name, type, "notnull", dflt_value, pk, hidden
FROM pragma_table_xinfo(?, 'main') ORDER BY cid LIMIT ?"""
_INDEXES = """SELECT seq, name, "unique", origin, partial
FROM pragma_index_list(?, 'main') ORDER BY name LIMIT ?"""
_TERMS = """SELECT seqno, cid, name, "desc", coll, "key"
FROM pragma_index_xinfo(?, 'main') ORDER BY seqno LIMIT ?"""
_FOREIGN_KEYS = """SELECT id, seq, "table", "from", "to", on_update, on_delete, match
FROM pragma_foreign_key_list(?, 'main') ORDER BY id, seq LIMIT ?"""

_LIMIT_MESSAGES = {
    'object_limit': 'O limite de objetos foi atingido.',
    'detail_limit': 'O limite global de detalhes foi atingido.',
    'text_limit': 'O limite de bytes de um campo textual foi atingido.',
    'total_text_limit': 'O limite total de texto observado foi atingido.',
    'vm_limit': 'O orçamento de instruções SQLite foi atingido.',
    'issue_limit': 'O limite de achados foi atingido.',
}


class _Stop(Exception):
    def __init__(self, code):
        self.code = code


class _BadMetadata(Exception):
    pass


def _text(value, *, nullable=False):
    if isinstance(value, str) or (nullable and value is None):
        return value
    raise _BadMetadata


def _integer(value, *, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise _BadMetadata
    return value


def _flag(value):
    if type(value) is not int or value not in (0, 1):
        raise _BadMetadata
    return bool(value)


def _sha256(value):
    return None if value is None else hashlib.sha256(value.encode('utf-8')).hexdigest()


class _Capture:
    def __init__(self, connection, report, limits):
        self.connection = connection
        self.report = report
        self.limits = limits
        self.text_bytes = 0
        self.detail_rows = 0
        self.vm_steps = 0
        self.vm_exhausted = False
        self.observed = False
        self.issues = []
        self.active_table = None
        self.active_index = None
        self.active_name = None

    def progress(self):
        self.vm_steps += 100
        if self.vm_steps >= self.limits.max_vm_steps:
            self.vm_exhausted = True
            return 1
        return 0

    def execute(self, sql, parameters=()):
        # SQLite can finish a statement before the first progress callback.
        # Reserve its unobserved suffix (0..99 steps) so many short statements
        # cannot evade a global budget. This deliberately errs conservatively.
        if self.vm_steps + 99 > self.limits.max_vm_steps:
            self.vm_exhausted = True
            raise _Stop('vm_limit')
        self.vm_steps += 99
        return self.connection.execute(sql, parameters)

    def incomplete(self):
        self.report['complete'] = False
        self.report['status'] = 'partial'
        if self.active_table is not None:
            self.active_table['details_complete'] = False
        if self.active_index is not None:
            self.active_index['complete'] = False

    def issue(self, code, message, object_name=None):
        self.incomplete()
        # Keep one slot for a visible truncation marker, including max_issues=1.
        if len(self.issues) >= self.limits.max_issues - 1:
            self.issues.append(Issue('incomplete', 'issue_limit',
                                     _LIMIT_MESSAGES['issue_limit']))
            raise _Stop('issue_limit')
        self.issues.append(Issue('incomplete', code, message, object_name))

    def stop(self, exception):
        self.incomplete()
        if exception.code != 'issue_limit':
            try:
                self.issue(exception.code, _LIMIT_MESSAGES[exception.code], self.active_name)
            except _Stop:
                pass

    def observe(self, row, *, detail=False):
        if detail:
            if self.detail_rows >= self.limits.max_detail_rows:
                raise _Stop('detail_limit')
        for value in row:
            if isinstance(value, str):
                size = len(value.encode('utf-8'))
                if size > self.limits.max_text_bytes:
                    raise _Stop('text_limit')
                if self.text_bytes + size > self.limits.max_total_text_bytes:
                    raise _Stop('total_text_limit')
                self.text_bytes += size
        if detail:
            self.detail_rows += 1

    def rows(self, sql, parameters=(), *, snapshot=False):
        cursor = None
        try:
            cursor = self.execute(sql, parameters)
            if snapshot:
                self.observed = True
            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                yield row
        except sqlite3.Error:
            if self.vm_exhausted:
                raise _Stop('vm_limit') from None
            raise
        finally:
            if cursor is not None:
                cursor.close()

    def remaining(self):
        # One extra row proves truncation without an unbounded fetchall().
        return self.limits.max_detail_rows - self.detail_rows + 1

    def metadata_failure(self, code='metadata_unavailable'):
        self.issue(code, 'Não foi possível obter parte dos metadados.', self.active_name)

    def inventory(self, include_sql, include_internal):
        for row in self.rows(_OBJECTS, (int(include_internal), self.limits.max_objects + 1),
                             snapshot=True):
            if len(self.report['objects']) >= self.limits.max_objects:
                raise _Stop('object_limit')
            self.observe(row)
            sqlite_type, name, table_name, sql = row
            sqlite_type = _text(sqlite_type)
            if sqlite_type not in ('table', 'view', 'index', 'trigger'):
                raise _BadMetadata
            item = {'type': sqlite_type, 'sqlite_type': sqlite_type,
                    'name': _text(name), 'table_name': _text(table_name),
                    'sql_sha256': _sha256(_text(sql, nullable=True)),
                    'column_count': None, 'without_rowid': None, 'strict': None}
            if include_sql:
                item['sql'] = sql
            self.report['objects'].append(item)

    def schema_flags(self):
        for field in ('schema_version', 'user_version', 'application_id', 'encoding'):
            # field is from this fixed tuple, never caller or database content.
            sql = {'schema_version': 'PRAGMA main.schema_version',
                   'user_version': 'PRAGMA main.user_version',
                   'application_id': 'PRAGMA main.application_id',
                   'encoding': 'PRAGMA main.encoding'}[field]
            try:
                iterator = self.rows(sql)
                try:
                    row = next(iterator)
                    self.observe(row)
                    value = _text(row[0]) if field == 'encoding' else _integer(row[0])
                    self.report['schema'][field] = value
                finally:
                    iterator.close()
            except (sqlite3.Error, UnicodeError, _BadMetadata, StopIteration):
                self.metadata_failure('schema_metadata_unavailable')

    def classify(self):
        ordinary = []
        shadow_classification_uncertain = False
        for item in self.report['objects']:
            if item['sqlite_type'] != 'table':
                continue
            self.active_name = item['name']
            try:
                found = False
                for row in self.rows(_TABLE_FLAGS, (item['name'],)):
                    self.observe(row)
                    if found:
                        raise _BadMetadata
                    name, kind, ncol, wr, strict = row
                    if _text(name) != item['name'] or kind not in ('table', 'virtual', 'shadow'):
                        raise _BadMetadata
                    item['type'] = kind
                    item['column_count'] = _integer(ncol, minimum=0)
                    item['without_rowid'] = _flag(wr)
                    item['strict'] = _flag(strict)
                    found = True
                if not found:
                    raise _BadMetadata
                if item['type'] == 'virtual' and item['column_count'] == 0:
                    # An unavailable virtual module can prevent SQLite from
                    # recognizing its shadow tables. Do not claim full capture.
                    shadow_classification_uncertain = True
                    self.issue('virtual_metadata_unavailable',
                               'O módulo virtual não forneceu metadados completos.', item['name'])
                if item['type'] == 'table':
                    ordinary.append(item)
            except (sqlite3.Error, UnicodeError, _BadMetadata):
                self.metadata_failure('table_classification_unavailable')
        self.active_name = None
        # Without the virtual module, names reported as ordinary can actually
        # be its shadow tables. Keep the observed inventory, but start no table
        # details at all: identifying an allegedly safe subset would be a guess.
        return [] if shadow_classification_uncertain else ordinary

    def columns(self, table, item, include_sql):
        for row in self.rows(_COLUMNS, (table['name'], self.remaining())):
            self.observe(row, detail=True)
            cid, name, declared_type, not_null, default, pk, hidden = row
            hidden = _integer(hidden, minimum=0)
            kind = {0: 'ordinary', 1: 'hidden', 2: 'generated_virtual',
                    3: 'generated_stored'}.get(hidden, 'unknown')
            column = {'cid': _integer(cid, minimum=0), 'name': _text(name),
                      'declared_type': _text(declared_type),
                      'not_null_declared': _flag(not_null),
                      'primary_key_position': _integer(pk, minimum=0),
                      'hidden_code': hidden, 'kind': kind,
                      'default_present': default is not None,
                      'default_sha256': _sha256(_text(default, nullable=True))}
            if include_sql:
                column['default_sql'] = default
            table['columns'].append(column)
            if kind == 'unknown':
                self.metadata_failure('unknown_column_kind')
        if len(table['columns']) != item['column_count']:
            raise _BadMetadata
        if len({column['cid'] for column in table['columns']}) != len(table['columns']):
            raise _BadMetadata

    def indexes(self, table):
        # Complete this small list first, then read each index on the same
        # snapshot; concurrent DDL cannot mix an old list with new terms.
        for row in self.rows(_INDEXES, (table['name'], self.remaining())):
            self.observe(row, detail=True)
            seq, name, unique, origin, partial = row
            _integer(seq, minimum=0)
            index = {'name': _text(name), 'unique': _flag(unique),
                     'origin': _text(origin), 'partial': _flag(partial),
                     'complete': False, 'terms': []}
            table['indexes'].append(index)
            if origin not in ('c', 'u', 'pk'):
                self.metadata_failure('unknown_index_origin')
        for index in table['indexes']:
            self.active_index = index
            valid = index['origin'] in ('c', 'u', 'pk')
            try:
                for row in self.rows(_TERMS, (index['name'], self.remaining())):
                    self.observe(row, detail=True)
                    seqno, cid, name, descending, collation, key = row
                    cid = _integer(cid)
                    kind = 'column' if cid >= 0 else {-1: 'rowid', -2: 'expression'}.get(cid, 'unknown')
                    term = {'seqno': _integer(seqno, minimum=0), 'cid': cid,
                            'name': _text(name, nullable=True), 'kind': kind,
                            'descending': _flag(descending),
                            'collation': _text(collation, nullable=True), 'key': _flag(key)}
                    index['terms'].append(term)
                    if kind == 'unknown':
                        valid = False
                        self.metadata_failure('unknown_index_term')
                if not index['terms']:
                    raise _BadMetadata
                if [term['seqno'] for term in index['terms']] != list(range(len(index['terms']))):
                    raise _BadMetadata
                index['complete'] = valid
            except (sqlite3.Error, UnicodeError, _BadMetadata):
                self.metadata_failure('index_metadata_unavailable')
            self.active_index = None

    def foreign_keys(self, table):
        groups = {}
        for row in self.rows(_FOREIGN_KEYS, (table['name'], self.remaining())):
            self.observe(row, detail=True)
            fk_id, seq, target, source, destination, on_update, on_delete, match = row
            fk_id, seq = _integer(fk_id, minimum=0), _integer(seq, minimum=0)
            attributes = {'target_table': _text(target), 'on_update': _text(on_update),
                          'on_delete': _text(on_delete), 'match': _text(match)}
            if fk_id not in groups:
                groups[fk_id] = {'id': fk_id, **attributes, 'columns': []}
                table['foreign_keys'].append(groups[fk_id])
            foreign_key = groups[fk_id]
            if any(foreign_key[key] != value for key, value in attributes.items()):
                raise _BadMetadata
            foreign_key['columns'].append({'seq': seq, 'from': _text(source),
                                           'to': _text(destination, nullable=True)})
        for foreign_key in table['foreign_keys']:
            if [column['seq'] for column in foreign_key['columns']] != list(range(len(foreign_key['columns']))):
                raise _BadMetadata

    def details(self, ordinary, include_sql):
        for item in sorted(ordinary, key=lambda value: value['name']):
            self.active_name = item['name']
            table = {'name': item['name'], 'details_complete': True,
                     'columns': [], 'indexes': [], 'foreign_keys': []}
            self.report['tables'].append(table)
            self.active_table = table
            for operation in (lambda: self.columns(table, item, include_sql),
                              lambda: self.indexes(table), lambda: self.foreign_keys(table)):
                try:
                    operation()
                except (sqlite3.Error, UnicodeError, _BadMetadata):
                    self.metadata_failure()
            self.active_table = None
        self.active_name = None

    def finish(self):
        self.report['objects'].sort(key=lambda value: (value['type'], value['name']))
        self.report['tables'].sort(key=lambda value: value['name'])
        counts = {'table': 'ordinary_tables', 'view': 'views', 'virtual': 'virtual_tables',
                  'shadow': 'shadow_tables', 'index': 'indexes', 'trigger': 'triggers'}
        summary = dict.fromkeys(('objects', *counts.values(), 'detail_rows'), 0)
        summary['objects'] = len(self.report['objects'])
        summary['detail_rows'] = self.detail_rows
        for item in self.report['objects']:
            summary[counts[item['type']]] += 1
        self.report['summary'] = summary
        self.report['issues'] = [asdict(issue) for issue in sort_issues(self.issues)]
        return self.report


def capture_database(path, *, include_sql=False, include_internal=False,
                     limits=CatalogLimits()):
    """Capture metadata from ``main`` without querying business rows.

    Operational diagnostics are constant and intentionally omit the supplied
    path, SQL text and SQLite's exception messages. A stopped or partly failed
    capture returns its observed objects with an explicit partial status.
    """
    if type(include_sql) is not bool or type(include_internal) is not bool:
        raise ValueError('As opções de inclusão devem ser booleanas.')
    if not isinstance(limits, CatalogLimits):
        raise ValueError('Limites inválidos.')
    try:
        raw_path = os.fspath(path)
    except TypeError:
        raise ValueError('Caminho inválido.') from None
    if not isinstance(raw_path, str) or '\x00' in raw_path:
        raise ValueError('Caminho inválido.')
    if sys.version_info < (3, 11) or sqlite3.sqlite_version_info < (3, 37, 0):
        raise CatalogError('incompatible_runtime', 'O runtime Python ou SQLite é incompatível.')
    source = Path(raw_path).absolute()
    try:
        source_stat = source.stat()
    except FileNotFoundError:
        raise CatalogError('file_not_found', 'O arquivo de origem não existe.') from None
    except OSError:
        raise CatalogError('file_unreadable', 'Não foi possível acessar o arquivo de origem.') from None
    if not stat.S_ISREG(source_stat.st_mode):
        raise CatalogError('file_not_regular', 'A origem deve ser um arquivo regular.')
    report = {'schema_version': 1, 'profile': 'sqlite-catalog-report-v1',
              'filename': source.name, 'sqlite_version': sqlite3.sqlite_version,
              'options': {'include_sql': include_sql, 'include_internal': include_internal},
              'limits': asdict(limits), 'status': 'complete', 'complete': True,
              'schema': dict.fromkeys(('schema_version', 'user_version', 'application_id', 'encoding')),
              'summary': {}, 'objects': [], 'tables': [], 'issues': []}
    connection = None
    capture = None
    try:
        connection = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True,
                                     isolation_level=None,
                                     timeout=limits.busy_timeout_ms / 1000)
        capture = _Capture(connection, report, limits)
        connection.set_progress_handler(capture.progress, 100)
        try:
            connection.enable_load_extension(False)
        except (AttributeError, sqlite3.NotSupportedError):
            # Builds without extension loading already keep it unavailable.
            pass
        capture.execute('PRAGMA query_only=ON').close()
        capture.execute('PRAGMA trusted_schema=OFF').close()
        for statement, expected in (('PRAGMA query_only', 1), ('PRAGMA trusted_schema', 0)):
            iterator = capture.rows(statement)
            try:
                row = next(iterator, None)
                if row is None or row[0] != expected:
                    raise CatalogError('incompatible_runtime', 'O runtime Python ou SQLite é incompatível.')
            finally:
                iterator.close()
        capture.execute('BEGIN').close()
        capture.inventory(include_sql, include_internal)
        capture.schema_flags()
        ordinary = capture.classify()
        capture.details(ordinary, include_sql)
    except _Stop as exception:
        capture.stop(exception)
    except (sqlite3.Error, UnicodeError, _BadMetadata):
        if connection is None:
            raise CatalogError('open_failed', 'Não foi possível abrir o banco SQLite de origem.') from None
        if capture is not None and capture.vm_exhausted:
            capture.stop(_Stop('vm_limit'))
        elif capture is not None and capture.observed:
            try:
                capture.metadata_failure('capture_metadata_unavailable')
            except _Stop:
                pass
        else:
            raise CatalogError('invalid_database', 'Não foi possível ler o catálogo SQLite de origem.') from None
    except OSError:
        raise CatalogError('open_failed', 'Não foi possível abrir o banco SQLite de origem.') from None
    finally:
        if connection is not None:
            connection.close()
    return capture.finish()
