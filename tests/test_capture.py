"""Capture tests use only databases made here with synthetic schema and rows."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlite_catalog_report import capture
from sqlite_catalog_report.model import CatalogError, CatalogLimits


_CONNECT = sqlite3.connect


class RecordedConnection(sqlite3.Connection):
    instances = []
    inject = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.statements = []
        self.calls = []
        self.extension_settings = []
        self.progress_interval = None
        self.was_closed = False
        self.set_trace_callback(self.statements.append)
        type(self).instances.append(self)

    def execute(self, statement, parameters=()):
        self.calls.append((statement, parameters))
        callback = type(self).inject
        if callback is not None:
            callback(self, statement, parameters)
        return super().execute(statement, parameters)

    def enable_load_extension(self, enabled):
        self.extension_settings.append(enabled)
        return super().enable_load_extension(enabled)

    def set_progress_handler(self, handler, interval):
        self.progress_interval = interval
        return super().set_progress_handler(handler, interval)

    def close(self):
        self.was_closed = True
        return super().close()


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / 'synthetic.sqlite'
        RecordedConnection.instances = []
        RecordedConnection.inject = None

    def tearDown(self):
        RecordedConnection.inject = None
        self.directory.cleanup()

    def create(self, sql='CREATE TABLE example(id INTEGER PRIMARY KEY, label TEXT)'):
        connection = _CONNECT(self.path)
        try:
            connection.executescript(sql)
        finally:
            connection.close()
        return self.path

    def recorded(self, **kwargs):
        calls = []

        def connect(*args, **options):
            calls.append((args, options.copy()))
            options['factory'] = RecordedConnection
            return _CONNECT(*args, **options)

        with patch.object(capture.sqlite3, 'connect', side_effect=connect):
            report = capture.capture_database(self.path, **kwargs)
        return report, RecordedConnection.instances[-1], calls

    def test_rich_schema_and_exact_metadata(self):
        self.create('''
            PRAGMA user_version=7;
            PRAGMA application_id=42;
            CREATE TABLE parent(a TEXT, b INTEGER, PRIMARY KEY(b, a)) WITHOUT ROWID;
            CREATE TABLE child(
                id INTEGER PRIMARY KEY,
                ref_b INTEGER, ref_a TEXT NOT NULL DEFAULT 'synthetic default',
                virtual_value TEXT GENERATED ALWAYS AS (upper(ref_a)) VIRTUAL,
                stored_value INTEGER GENERATED ALWAYS AS (ref_b + 1) STORED,
                FOREIGN KEY(ref_b,ref_a) REFERENCES parent ON DELETE CASCADE
            ) STRICT;
            CREATE UNIQUE INDEX descending_index ON child(ref_a COLLATE NOCASE DESC);
            CREATE INDEX expression_index ON child(lower(ref_a)) WHERE ref_b > 1;
        ''')
        report = capture.capture_database(self.path)
        self.assertTrue(report['complete'], report['issues'])
        self.assertNotIn('graph', report)
        self.assertNotIn('catalog_sha256', report)
        self.assertEqual(report['schema']['user_version'], 7)
        self.assertEqual(report['schema']['application_id'], 42)
        tables = {table['name']: table for table in report['tables']}
        objects = {item['name']: item for item in report['objects']}
        self.assertTrue(objects['child']['strict'])
        self.assertTrue(objects['parent']['without_rowid'])
        self.assertEqual(objects['child']['column_count'], 5)
        self.assertFalse(tables['child']['columns'][0]['not_null_declared'])
        self.assertEqual([column['kind'] for column in tables['child']['columns']][-2:],
                         ['generated_virtual', 'generated_stored'])
        self.assertEqual(tables['parent']['columns'][0]['primary_key_position'], 2)
        self.assertEqual(tables['parent']['columns'][1]['primary_key_position'], 1)
        foreign_key = tables['child']['foreign_keys'][0]
        self.assertEqual(foreign_key['target_table'], 'parent')
        self.assertEqual(foreign_key['on_delete'], 'CASCADE')
        self.assertEqual(foreign_key['columns'], [{'seq': 0, 'from': 'ref_b', 'to': None},
                                                  {'seq': 1, 'from': 'ref_a', 'to': None}])
        indexes = {item['name']: item for item in tables['child']['indexes']}
        self.assertEqual(indexes['expression_index']['terms'][0]['kind'], 'expression')
        self.assertIsNone(indexes['expression_index']['terms'][0]['name'])
        self.assertTrue(indexes['expression_index']['partial'])
        self.assertEqual(indexes['expression_index']['terms'][1]['kind'], 'rowid')
        self.assertFalse(indexes['expression_index']['terms'][1]['key'])
        self.assertTrue(indexes['descending_index']['terms'][0]['descending'])
        self.assertEqual(indexes['descending_index']['terms'][0]['collation'], 'NOCASE')
        self.assertEqual(tables['parent']['indexes'][0]['origin'], 'pk')

    def test_sql_and_defaults_hidden_but_hashed(self):
        self.create("CREATE TABLE example(value TEXT DEFAULT 'private schema default')")
        hidden = capture.capture_database(self.path)
        shown = capture.capture_database(self.path, include_sql=True)
        hidden_column = hidden['tables'][0]['columns'][0]
        shown_column = shown['tables'][0]['columns'][0]
        self.assertNotIn('sql', hidden['objects'][0])
        self.assertNotIn('default_sql', hidden_column)
        self.assertTrue(hidden_column['default_present'])
        self.assertEqual(hidden_column['default_sha256'],
                         hashlib.sha256(shown_column['default_sql'].encode()).hexdigest())
        self.assertEqual(hidden['objects'][0]['sql_sha256'],
                         hashlib.sha256(shown['objects'][0]['sql'].encode()).hexdigest())
        self.assertEqual(hidden_column['default_sha256'], shown_column['default_sha256'])

    def test_internal_tables_filtered_autoindexes_preserved(self):
        self.create('CREATE TABLE example(id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT UNIQUE)')
        hidden = capture.capture_database(self.path)
        shown = capture.capture_database(self.path, include_internal=True)
        names = {item['name'] for item in hidden['objects']}
        self.assertNotIn('sqlite_sequence', names)
        self.assertIn('sqlite_autoindex_example_1', names)
        automatic = next(item for item in hidden['objects'] if item['type'] == 'index')
        self.assertIsNone(automatic['sql_sha256'])
        self.assertIn('sqlite_sequence', {item['name'] for item in shown['objects']})
        self.assertIn('sqlite_sequence', {item['name'] for item in shown['tables']})

    def test_connection_safety_trace_and_no_business_rows(self):
        self.create('''
            CREATE TABLE business(secret TEXT);
            INSERT INTO business VALUES('CANARY_ROW_NOT_METADATA_4927');
            CREATE TABLE destination(value TEXT);
            CREATE VIEW hostile_view AS SELECT unavailable_dangerous_function(secret) FROM business;
            CREATE TRIGGER hostile_trigger AFTER INSERT ON destination
            BEGIN DELETE FROM business; END;
        ''')
        before = self.path.read_bytes()
        report, connection, calls = self.recorded()
        serialized = json.dumps(report)
        self.assertNotIn('CANARY_ROW_NOT_METADATA_4927', serialized)
        self.assertTrue(report['complete'], report['issues'])
        self.assertTrue(connection.was_closed)
        self.assertEqual(connection.extension_settings, [False])
        self.assertEqual(connection.progress_interval, 100)
        self.assertTrue(calls[0][0][0].endswith('?mode=ro'))
        self.assertTrue(calls[0][1]['uri'])
        self.assertIsNone(calls[0][1]['isolation_level'])
        statements = connection.statements
        self.assertIn('PRAGMA query_only=ON', statements)
        self.assertIn('PRAGMA query_only', statements)
        self.assertIn('PRAGMA trusted_schema=OFF', statements)
        self.assertIn('PRAGMA trusted_schema', statements)
        self.assertEqual(statements.count('BEGIN'), 1)
        schema_read = next(index for index, statement in enumerate(statements)
                           if 'FROM main.sqlite_schema' in statement)
        self.assertLess(statements.index('BEGIN'), schema_read)
        for statement in statements:
            normalized = statement.lower().strip()
            self.assertNotIn('count(', normalized)
            self.assertNotIn('integrity_check', normalized)
            self.assertNotIn('quick_check', normalized)
            self.assertNotIn('foreign_key_check', normalized)
            self.assertNotIn('from business', normalized)
            self.assertNotIn('from hostile_view', normalized)
            self.assertFalse(normalized.startswith(('insert ', 'update ', 'delete ', 'attach ', 'create ')))
        self.assertEqual(self.path.read_bytes(), before)

    def test_identifiers_are_parameters_not_executable_syntax(self):
        name = 'odd"; DROP TABLE guard;--?/#'
        quoted = '"' + name.replace('"', '""') + '"'
        self.create('CREATE TABLE guard(x); CREATE TABLE ' + quoted + '("a\'b" TEXT UNIQUE)')
        report, connection, _ = self.recorded()
        self.assertTrue(report['complete'], report['issues'])
        self.assertEqual({table['name'] for table in report['tables']}, {'guard', name})
        parameter_calls = [(statement, parameters) for statement, parameters in connection.calls
                           if name in parameters]
        self.assertGreaterEqual(len(parameter_calls), 4)
        self.assertTrue(all(name not in statement for statement, _ in parameter_calls))

    def test_special_filename_is_uri_encoded_and_source_not_modified(self):
        self.path = self.root / 'fictício ?mode=rw#fragment%.sqlite'
        self.create()
        original = self.path.read_bytes()
        report, _, calls = self.recorded()
        self.assertEqual(report['filename'], self.path.name)
        self.assertIn('%3Fmode%3Drw%23fragment%25', calls[0][0][0])
        self.assertNotIn('immutable', calls[0][0][0])
        self.assertNotIn('nolock', calls[0][0][0])
        self.assertEqual(self.path.read_bytes(), original)

    def test_regular_symlink_can_be_followed(self):
        self.create()
        alias = self.root / 'alias.sqlite'
        try:
            alias.symlink_to(self.path)
        except OSError:
            self.skipTest('Symlinks unavailable for this test account')
        self.assertTrue(capture.capture_database(alias)['complete'])
        self.assertEqual(capture.capture_database(alias)['filename'], 'alias.sqlite')

    def test_operational_errors_are_constant_and_missing_is_not_created(self):
        with self.assertRaises(CatalogError) as missing:
            capture.capture_database(self.path)
        self.assertEqual(missing.exception.code, 'file_not_found')
        self.assertFalse(self.path.exists())
        with self.assertRaises(CatalogError) as directory:
            capture.capture_database(self.root)
        self.assertEqual(directory.exception.code, 'file_not_regular')
        self.path.write_text('NOT_SQLITE_SENSITIVE_CANARY')
        with self.assertRaises(CatalogError) as invalid:
            capture.capture_database(self.path)
        for exception in (missing.exception, directory.exception, invalid.exception):
            self.assertNotIn(str(self.root), str(exception))
            self.assertNotIn('NOT_SQLITE_SENSITIVE_CANARY', str(exception))
        self.assertEqual(invalid.exception.code, 'invalid_database')

    def test_incompatible_runtime_and_arguments(self):
        self.create()
        with patch.object(capture.sqlite3, 'sqlite_version_info', (3, 36, 0)):
            with self.assertRaises(CatalogError) as caught:
                capture.capture_database(self.path)
        self.assertEqual(caught.exception.code, 'incompatible_runtime')
        for arguments in ({'include_sql': 1}, {'include_internal': 'yes'}, {'limits': None}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                capture.capture_database(self.path, **arguments)
        for path in (None, b'file.sqlite', 'bad\x00path'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                capture.capture_database(path)

    def test_readonly_and_query_only_are_effective(self):
        self.create()
        observed = []

        def verify(connection, statement, parameters):
            if statement.startswith('SELECT type, name, tbl_name'):
                observed.append((connection.in_transaction,
                                 sqlite3.Connection.execute(connection, 'PRAGMA query_only').fetchone()[0],
                                 sqlite3.Connection.execute(connection, 'PRAGMA trusted_schema').fetchone()[0]))
                with self.assertRaises(sqlite3.OperationalError):
                    sqlite3.Connection.execute(connection, 'CREATE TABLE forbidden(x)')

        RecordedConnection.inject = verify
        report, _, _ = self.recorded()
        self.assertTrue(report['complete'])
        self.assertEqual(observed, [(True, 1, 0)])

    def test_safety_flags_must_be_confirmed(self):
        self.create()

        class MissingFlagConnection(RecordedConnection):
            def execute(self, statement, parameters=()):
                if statement == 'PRAGMA trusted_schema':
                    return super().execute('SELECT 1')
                return super().execute(statement, parameters)

        def connect(*args, **kwargs):
            return _CONNECT(*args, **kwargs, factory=MissingFlagConnection)

        with patch.object(capture.sqlite3, 'connect', side_effect=connect):
            with self.assertRaises(CatalogError) as caught:
                capture.capture_database(self.path)
        self.assertEqual(caught.exception.code, 'incompatible_runtime')
        self.assertTrue(MissingFlagConnection.instances[-1].was_closed)

    def test_wal_schema_is_one_coherent_snapshot(self):
        self.create('CREATE TABLE old_table(original INTEGER)')
        writer = _CONNECT(self.path, isolation_level=None)
        if writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
            writer.close()
            self.skipTest('WAL unavailable')
        changed = []

        class ConcurrentConnection(RecordedConnection):
            def execute(self, statement, parameters=()):
                cursor = super().execute(statement, parameters)
                if statement.startswith('SELECT type, name, tbl_name') and not changed:
                    # execute() has stepped to the first sqlite_schema row and
                    # fixed the reader snapshot before the writer commits.
                    writer.execute('ALTER TABLE old_table ADD COLUMN concurrent TEXT')
                    writer.execute('CREATE TABLE new_table(new_column TEXT)')
                    changed.append(True)
                return cursor

        def connect(*args, **kwargs):
            return _CONNECT(*args, **kwargs, factory=ConcurrentConnection)

        try:
            with patch.object(capture.sqlite3, 'connect', side_effect=connect):
                report = capture.capture_database(self.path)
            self.assertTrue(changed)
            self.assertTrue(report['complete'], report['issues'])
            self.assertEqual([table['name'] for table in report['tables']], ['old_table'])
            self.assertEqual([column['name'] for column in report['tables'][0]['columns']], ['original'])
            self.assertTrue(ConcurrentConnection.instances[-1].was_closed)
        finally:
            writer.close()
        after = capture.capture_database(self.path)
        self.assertEqual([table['name'] for table in after['tables']], ['new_table', 'old_table'])
        self.assertEqual(after['tables'][1]['columns'][1]['name'], 'concurrent')

    def test_object_limit_is_visible_and_closes_connection(self):
        self.create('CREATE TABLE a(x); CREATE TABLE b(y); CREATE TABLE c(z)')
        report, connection, _ = self.recorded(limits=CatalogLimits(max_objects=2))
        self.assertFalse(report['complete'])
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['summary']['objects'], 2)
        self.assertEqual(report['issues'][0]['code'], 'object_limit')
        self.assertTrue(connection.was_closed)
        self.assertFalse(any('pragma_table_xinfo' in statement for statement, _ in connection.calls))

    def test_detail_limit_is_global_across_tables_indexes_and_terms(self):
        self.create('CREATE TABLE a(x,y); CREATE INDEX ix ON a(x); CREATE TABLE b(z)')
        report, connection, _ = self.recorded(limits=CatalogLimits(max_detail_rows=4))
        self.assertFalse(report['complete'])
        self.assertEqual(report['summary']['detail_rows'], 4)
        self.assertEqual(report['issues'][0]['code'], 'detail_limit')
        self.assertEqual(len(report['tables'][0]['columns']), 2)
        self.assertEqual(len(report['tables'][0]['indexes']), 1)
        self.assertEqual(len(report['tables'][0]['indexes'][0]['terms']), 1)
        self.assertFalse(report['tables'][0]['indexes'][0]['complete'])
        self.assertFalse(report['tables'][0]['details_complete'])
        self.assertEqual([table['name'] for table in report['tables']], ['a'])
        self.assertTrue(connection.was_closed)

    def test_index_list_cutoff_does_not_claim_unread_terms_are_complete(self):
        self.create('CREATE TABLE a(x); CREATE INDEX i1 ON a(x); CREATE INDEX i2 ON a(x)')
        report, connection, _ = self.recorded(limits=CatalogLimits(max_detail_rows=2))
        self.assertFalse(report['complete'])
        indexes = report['tables'][0]['indexes']
        self.assertEqual([index['name'] for index in indexes], ['i1'])
        self.assertEqual(indexes[0]['terms'], [])
        self.assertFalse(indexes[0]['complete'])
        self.assertFalse(report['tables'][0]['details_complete'])
        self.assertFalse(any('pragma_index_xinfo' in statement for statement, _ in connection.calls))

    def test_hidden_ddl_counts_toward_field_and_total_text_budgets(self):
        self.create("CREATE TABLE example(value TEXT DEFAULT '" + ('x' * 300) + "')")
        for limits, code in ((CatalogLimits(max_text_bytes=100), 'text_limit'),
                             (CatalogLimits(max_total_text_bytes=100), 'total_text_limit')):
            with self.subTest(code=code):
                report, connection, _ = self.recorded(limits=limits)
                self.assertFalse(report['complete'])
                self.assertEqual(report['issues'][0]['code'], code)
                self.assertNotIn('x' * 300, json.dumps(report))
                self.assertTrue(connection.was_closed)

    def test_hidden_default_counts_again_when_observed_by_xinfo(self):
        default = "'" + 'x' * 100 + "'"
        self.create('CREATE TABLE example(value TEXT DEFAULT ' + default + ')')
        # The DDL fits the field budget; a total between inventory and the
        # repeated default in xinfo proves hidden defaults are also charged.
        report = capture.capture_database(self.path, limits=CatalogLimits(max_total_text_bytes=220))
        self.assertFalse(report['complete'])
        self.assertEqual(report['issues'][0]['code'], 'total_text_limit')
        self.assertEqual(len(report['objects']), 1)

    def test_vm_budget_cannot_be_evaded_by_short_statements(self):
        self.create()
        report, connection, _ = self.recorded(limits=CatalogLimits(max_vm_steps=1))
        self.assertFalse(report['complete'])
        self.assertEqual(report['issues'][0]['code'], 'vm_limit')
        self.assertTrue(connection.was_closed)
        self.assertEqual(connection.progress_interval, 100)
        self.assertEqual(connection.calls, [])

    def test_vm_progress_interrupt_does_not_restart_metadata_queries(self):
        self.create(';'.join('CREATE TABLE t' + str(index) + '(a,b,c,d,e)' for index in range(250)))
        report, connection, _ = self.recorded(limits=CatalogLimits(max_vm_steps=1000))
        self.assertFalse(report['complete'])
        self.assertEqual(report['issues'][0]['code'], 'vm_limit')
        self.assertTrue(connection.was_closed)
        self.assertEqual(sum(statement == capture._OBJECTS for statement, _ in connection.calls), 1)
        self.assertFalse(any('pragma_table_xinfo' in statement for statement, _ in connection.calls))

    def test_global_vm_budget_also_charges_many_small_metadata_statements(self):
        self.create(';'.join('CREATE TABLE t' + str(index) + '(x)' for index in range(10)))
        report, connection, _ = self.recorded(limits=CatalogLimits(max_vm_steps=4500))
        self.assertFalse(report['complete'])
        self.assertEqual(report['issues'][0]['code'], 'vm_limit')
        self.assertGreater(len(connection.calls), 20)
        self.assertLessEqual(len(connection.calls), 4500 // 99)
        self.assertTrue(connection.was_closed)

    def test_invalid_database_closes_connection_and_open_errors_are_sanitized(self):
        self.path.write_bytes(b'SYNTHETIC_INVALID_DATABASE_CANARY')
        with self.assertRaises(CatalogError) as invalid:
            self.recorded()
        self.assertEqual(invalid.exception.code, 'invalid_database')
        self.assertTrue(RecordedConnection.instances[-1].was_closed)
        with patch.object(capture.sqlite3, 'connect',
                          side_effect=sqlite3.OperationalError('SECRET_BACKEND_SQL /secret/path')):
            with self.assertRaises(CatalogError) as failed:
                capture.capture_database(self.path)
        self.assertEqual(failed.exception.code, 'open_failed')
        self.assertNotIn('SECRET_BACKEND_SQL', str(failed.exception))
        self.assertNotIn('/secret/path', str(failed.exception))

    def test_issue_limit_reserves_visible_marker_and_stops(self):
        self.create('CREATE TABLE a(x); CREATE TABLE b(y); CREATE TABLE c(z)')

        def fail_columns(connection, statement, parameters):
            if 'pragma_table_xinfo' in statement:
                raise sqlite3.OperationalError('LEAK_CANARY /absolute/private/path SQL SELECT secret')

        RecordedConnection.inject = fail_columns
        report, connection, _ = self.recorded(limits=CatalogLimits(max_issues=2))
        self.assertFalse(report['complete'])
        self.assertEqual(len(report['issues']), 2)
        self.assertIn('issue_limit', {issue['code'] for issue in report['issues']})
        self.assertNotIn('LEAK_CANARY', json.dumps(report))
        self.assertNotIn('/absolute/private/path', json.dumps(report))
        self.assertEqual([table['name'] for table in report['tables']], ['a', 'b'])
        self.assertTrue(connection.was_closed)
        one, _, _ = self.recorded(limits=CatalogLimits(max_issues=1))
        self.assertEqual([issue['code'] for issue in one['issues']], ['issue_limit'])

    def test_individual_metadata_failure_preserves_other_tables(self):
        self.create('CREATE TABLE a(x); CREATE TABLE b(y)')

        def fail_one(connection, statement, parameters):
            if 'pragma_table_xinfo' in statement and parameters[0] == 'a':
                raise sqlite3.OperationalError('SENSITIVE_BACKEND_MESSAGE')

        RecordedConnection.inject = fail_one
        report, connection, _ = self.recorded()
        self.assertFalse(report['complete'])
        self.assertFalse(report['tables'][0]['details_complete'])
        self.assertTrue(report['tables'][1]['details_complete'])
        self.assertEqual(report['tables'][1]['columns'][0]['name'], 'y')
        self.assertNotIn('SENSITIVE_BACKEND_MESSAGE', json.dumps(report))
        self.assertTrue(connection.was_closed)

    def test_failed_index_details_mark_both_index_and_table_incomplete(self):
        self.create('CREATE TABLE a(x); CREATE INDEX ix ON a(x)')

        def fail_terms(connection, statement, parameters):
            if 'pragma_index_xinfo' in statement:
                raise sqlite3.OperationalError('private backend detail')

        RecordedConnection.inject = fail_terms
        report, _, _ = self.recorded()
        self.assertFalse(report['complete'])
        self.assertFalse(report['tables'][0]['details_complete'])
        self.assertFalse(report['tables'][0]['indexes'][0]['complete'])
        self.assertEqual(report['issues'][0]['code'], 'index_metadata_unavailable')

    def test_valid_terms_do_not_hide_an_unknown_index_origin(self):
        self.create('CREATE TABLE a(x); CREATE INDEX ix ON a(x)')

        class UnknownOriginConnection(RecordedConnection):
            def execute(self, statement, parameters=()):
                if statement == capture._INDEXES:
                    return super().execute("SELECT 0, 'ix', 0, 'unknown', 0")
                return super().execute(statement, parameters)

        def connect(*args, **kwargs):
            return _CONNECT(*args, **kwargs, factory=UnknownOriginConnection)

        with patch.object(capture.sqlite3, 'connect', side_effect=connect):
            report = capture.capture_database(self.path)
        self.assertFalse(report['complete'])
        index = report['tables'][0]['indexes'][0]
        self.assertTrue(index['terms'])
        self.assertFalse(index['complete'])
        self.assertIn('unknown_index_origin', {issue['code'] for issue in report['issues']})

    def test_missing_table_list_result_is_not_silent_success(self):
        self.create()

        class MissingClassification(RecordedConnection):
            def execute(self, statement, parameters=()):
                if statement == capture._TABLE_FLAGS:
                    return super().execute('SELECT name FROM main.sqlite_schema WHERE 0')
                return super().execute(statement, parameters)

        def connect(*args, **kwargs):
            return _CONNECT(*args, **kwargs, factory=MissingClassification)

        with patch.object(capture.sqlite3, 'connect', side_effect=connect):
            report = capture.capture_database(self.path)
        self.assertFalse(report['complete'])
        self.assertEqual(report['issues'][0]['code'], 'table_classification_unavailable')
        self.assertEqual(report['tables'], [])

    def test_views_and_triggers_are_definitions_only_even_if_view_is_unusable(self):
        self.create('''
            CREATE TABLE present(x);
            CREATE VIEW missing_view AS SELECT * FROM nonexistent_table;
            CREATE TRIGGER declared_trigger AFTER INSERT ON present
            BEGIN SELECT nonexistent_function(NEW.x); END;
        ''')
        report, connection, _ = self.recorded()
        self.assertTrue(report['complete'], report['issues'])
        self.assertEqual(report['summary']['views'], 1)
        self.assertEqual(report['summary']['triggers'], 1)
        self.assertEqual([table['name'] for table in report['tables']], ['present'])
        self.assertFalse(any(parameters and parameters[0] in ('missing_view', 'declared_trigger')
                             for statement, parameters in connection.calls))

    def test_fts_virtual_and_shadow_tables_are_inventory_only(self):
        try:
            self.create('CREATE VIRTUAL TABLE search USING fts5(content)')
        except sqlite3.OperationalError:
            self.skipTest('This SQLite build does not include FTS5')
        report, connection, _ = self.recorded()
        self.assertTrue(report['complete'], report['issues'])
        self.assertEqual(report['summary']['virtual_tables'], 1)
        self.assertGreater(report['summary']['shadow_tables'], 0)
        self.assertEqual(report['tables'], [])
        self.assertFalse(any('pragma_table_xinfo' in statement or 'pragma_index_list' in statement
                             for statement, _ in connection.calls))

    def test_unavailable_virtual_module_does_not_claim_complete_classification(self):
        try:
            self.create('CREATE TABLE ordinary(secret TEXT); '
                        'CREATE VIRTUAL TABLE search USING fts5(content)')
        except sqlite3.OperationalError:
            self.skipTest('This SQLite build does not include FTS5')
        connection = _CONNECT(self.path)
        try:
            connection.execute('PRAGMA writable_schema=ON')
            connection.execute("UPDATE sqlite_schema SET sql=? WHERE name='search'",
                               ('CREATE VIRTUAL TABLE search USING absent_test_module(content)',))
            connection.commit()
        finally:
            connection.close()
        report, captured_connection, _ = self.recorded()
        self.assertFalse(report['complete'])
        self.assertIn('virtual_metadata_unavailable', {issue['code'] for issue in report['issues']})
        self.assertIn('search', {item['name'] for item in report['objects']})
        self.assertIn('ordinary', {item['name'] for item in report['objects']})
        self.assertEqual(report['tables'], [])
        self.assertEqual(report['summary']['detail_rows'], 0)
        self.assertFalse(any(any(pragma in statement for pragma in
                                 ('pragma_table_xinfo', 'pragma_index_list',
                                  'pragma_index_xinfo', 'pragma_foreign_key_list'))
                             for statement, _ in captured_connection.calls))

    def test_unicode_ordering_and_repeatability(self):
        self.create('CREATE TABLE "z"(x); CREATE TABLE "Á"(y); CREATE TABLE "A"(z); '
                    'CREATE INDEX "é" ON "z"(x); CREATE INDEX "b" ON "z"(x)')
        first = capture.capture_database(self.path)
        second = capture.capture_database(self.path)
        self.assertEqual(first, second)
        self.assertEqual([(item['type'], item['name']) for item in first['objects']],
                         sorted((item['type'], item['name']) for item in first['objects']))
        self.assertEqual([table['name'] for table in first['tables']], ['A', 'z', 'Á'])
        self.assertEqual([index['name'] for index in first['tables'][1]['indexes']], ['b', 'é'])

    def test_catalog_limits_reject_booleans_and_out_of_range_integers(self):
        defaults = CatalogLimits()
        for field in defaults.__dataclass_fields__:
            for value in (True, 1.0, -1):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    replace(defaults, **{field: value})
            if field != 'busy_timeout_ms':
                with self.subTest(field=field, value=0), self.assertRaises(ValueError):
                    replace(defaults, **{field: 0})
        self.assertEqual(CatalogLimits(busy_timeout_ms=0).busy_timeout_ms, 0)


if __name__ == '__main__':
    unittest.main()
