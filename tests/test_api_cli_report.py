"""Exercise the public API, text formats and exclusive CLI publisher together.

All database content, filenames and payloads in this file are synthetic.
"""

import copy
import errno
import io
import json
import os
from pathlib import Path
import re
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sqlite_catalog_report import (
    CatalogError, CatalogLimits, inspect_database, to_json, to_markdown, to_mermaid,
)
from sqlite_catalog_report import cli


PROJECT = Path(__file__).resolve().parents[1]


def quoted(value):
    return '"' + value.replace('"', '""') + '"'


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / 'synthetic.sqlite'

    def tearDown(self):
        self.directory.cleanup()

    def create(self, sql='CREATE TABLE parent(id INTEGER PRIMARY KEY); '
               'CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id REFERENCES parent)'):
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript(sql)
        finally:
            connection.close()

    def environment(self):
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(PROJECT / 'src')
        environment['PYTHONIOENCODING'] = 'utf-8'
        return environment

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, '-m', 'sqlite_catalog_report', *map(str, arguments)],
            cwd=self.root, env=self.environment(), text=True, encoding='utf-8',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )

    def assert_no_temporary_reports(self):
        self.assertEqual(list(self.root.glob('.sqlite-catalog-report-*.tmp')), [])

    def test_public_api_composes_capture_relationships_and_fingerprint(self):
        self.create()
        report = inspect_database(self.path)
        self.assertTrue(report['complete'])
        self.assertTrue(report['graph']['complete'])
        relation = report['graph']['relations'][0]
        self.assertEqual((relation['source'], relation['target'], relation['resolution']),
                         ('child', 'parent', 'resolved'))
        self.assertEqual(relation['target_columns'], ['id'])
        self.assertEqual([group['members'] for group in report['graph']['groups']],
                         [['parent'], ['child']])
        self.assertRegex(report['catalog_sha256'], r'^[0-9a-f]{64}$')
        self.assertNotIn(str(self.root), to_json(report))

    def test_fingerprint_ignores_sql_visibility_rows_and_schema_counters(self):
        self.create("CREATE TABLE example(id INTEGER PRIMARY KEY, value TEXT DEFAULT 'schema default')")
        hidden = inspect_database(self.path)
        shown = inspect_database(self.path, include_sql=True)
        self.assertEqual(hidden['catalog_sha256'], shown['catalog_sha256'])
        connection = sqlite3.connect(self.path)
        try:
            connection.execute('INSERT INTO example(value) VALUES (?)',
                               ('CANARY_PRIVATE_ROW_NOT_EXPORTED_7301',))
            connection.execute('PRAGMA user_version=98')
            connection.execute('PRAGMA application_id=45')
            connection.commit()
        finally:
            connection.close()
        changed = inspect_database(self.path, include_sql=True)
        self.assertEqual(hidden['catalog_sha256'], changed['catalog_sha256'])
        self.assertEqual(changed['schema']['user_version'], 98)
        for render in (to_json, to_markdown, to_mermaid):
            self.assertNotIn('CANARY_PRIVATE_ROW_NOT_EXPORTED_7301', render(changed))

    def test_synthetic_sample_generator_and_all_formats_do_not_export_rows(self):
        make_sample = runpy.run_path(str(PROJECT / 'scripts' / 'make_sample.py'))['make_sample']
        make_sample(self.path)
        original = self.path.read_bytes()
        report = inspect_database(self.path, include_sql=True)
        self.assertTrue(report['complete'], report['issues'])
        self.assertEqual(report['summary']['ordinary_tables'], 6)
        self.assertTrue(any(group['cyclic'] for group in report['graph']['groups']))
        for render in (to_json, to_markdown, to_mermaid):
            output = render(report)
            self.assertNotIn('REGISTRO_FICTICIO_NAO_EXPORTAR', output)
            self.assertNotIn('SKU_EXEMPLO', output)
        self.assertEqual(self.path.read_bytes(), original)
        with self.assertRaises(FileExistsError):
            make_sample(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.glob('.catalog-sample-*')), [])

    def test_unresolved_declared_relationship_keeps_complete_capture_and_hash(self):
        self.create('CREATE TABLE child(parent_id REFERENCES missing_parent(id))')
        report = inspect_database(self.path)
        self.assertTrue(report['complete'])
        self.assertTrue(report['graph']['complete'])
        self.assertEqual(report['graph']['unresolved_count'], 1)
        self.assertEqual(report['graph']['relations'][0]['resolution'], 'target_missing')
        self.assertIsNotNone(report['catalog_sha256'])

    def test_partial_api_and_presentations_are_explicit(self):
        self.create()
        report = inspect_database(self.path, limits=CatalogLimits(max_detail_rows=1))
        self.assertFalse(report['complete'])
        self.assertFalse(report['graph']['complete'])
        self.assertIsNone(report['catalog_sha256'])
        self.assertEqual(json.loads(to_json(report))['status'], 'partial')
        self.assertIn('PARCIAL', to_markdown(report))
        self.assertIn('Captura PARCIAL', to_mermaid(report))

    def test_json_is_ascii_safe_deterministic_and_renderers_do_not_mutate(self):
        self.create('CREATE TABLE "São Paulo"("descrição" TEXT)')
        report = inspect_database(self.path)
        before = copy.deepcopy(report)
        encoded = to_json(report)
        self.assertTrue(encoded.isascii())
        self.assertTrue(encoded.endswith('\n'))
        self.assertEqual(json.loads(encoded), report)
        self.assertEqual(encoded, to_json(report))
        for render in (to_markdown, to_mermaid):
            self.assertEqual(render(report), render(report))
        self.assertEqual(report, before)

    def test_markdown_escapes_html_links_delimiters_and_unicode_controls(self):
        name = 'unsafe|<img src=x onerror=alert(1)>`*_[click](javascript:evil)\\\n\t\u202e'
        self.create('CREATE TABLE ' + quoted(name) + '(' + quoted('c|<script>\u2028') + ' TEXT)')
        report = inspect_database(self.path)
        markdown = to_markdown(report)
        self.assertNotIn('<img', markdown)
        self.assertNotIn('<script>', markdown)
        self.assertIn('&lt;img', markdown)
        self.assertIn(r'\|', markdown)
        self.assertIn(r'\`', markdown)
        self.assertIn(r'\[click\]\(javascript:evil\)', markdown)
        for visible in (r'\\u000a', r'\\u0009', r'\\u202e', r'\\u2028'):
            self.assertIn(visible, markdown)
        self.assertNotIn('\u202e', markdown)
        self.assertNotIn('\u2028', markdown)
        self.assertNotIn(name, markdown)

    def test_stored_sql_cannot_close_markdown_fences(self):
        payload = 'literal ```` fence\n# injected heading\n<script>example</script>\u202e'
        escaped = payload.replace("'", "''")
        self.create("CREATE TABLE example(value TEXT DEFAULT '" + escaped + "')")
        hidden = to_markdown(inspect_database(self.path))
        self.assertNotIn('injected heading', hidden)
        shown = to_markdown(inspect_database(self.path, include_sql=True))
        lines = shown.splitlines()
        blocks = []
        position = 0
        while position < len(lines):
            match = re.fullmatch(r'(`{3,})sql', lines[position])
            if match is None:
                position += 1
                continue
            fence = match.group(1)
            end = lines.index(fence, position + 1)
            body = '\n'.join(lines[position + 1:end])
            longest = max((len(run) for run in re.findall(r'`+', body)), default=0)
            self.assertGreater(len(fence), longest)
            blocks.append(body)
            position = end + 1
        self.assertGreaterEqual(len(blocks), 2)  # default and stored definition
        self.assertTrue(any('# injected heading' in block for block in blocks))
        self.assertIn(r'\u202e', shown)
        self.assertNotIn('\u202e', shown)

    def test_mermaid_uses_synthetic_ids_and_numeric_entities_for_labels(self):
        parent = 'P"] --> x["&<>#;'
        child = 'C\n\u202e'
        self.create('CREATE TABLE ' + quoted(parent) + '(id INTEGER PRIMARY KEY); '
                    'CREATE TABLE ' + quoted(child) + '(ref REFERENCES ' + quoted(parent) + '(id))')
        report = inspect_database(self.path)
        mermaid = to_mermaid(report)
        definitions = [line for line in mermaid.splitlines() if re.match(r'  t\d+\[', line)]
        self.assertEqual(len(definitions), 2)
        for definition in definitions:
            self.assertRegex(definition, r'^  t\d+\["(?:[A-Za-z0-9 ]|#[0-9]+;)*"\]$')
        self.assertIn('#34;', mermaid)
        self.assertIn('#93;', mermaid)
        self.assertIn('#60;', mermaid)
        self.assertIn('#62;', mermaid)
        self.assertIn('#38;', mermaid)
        self.assertNotIn('\u202e', mermaid)
        self.assertNotIn(parent, mermaid)
        self.assertIn('  t0 -->|FK 0| t1', mermaid)
        self.assertEqual(mermaid, to_mermaid(report))

    def test_mermaid_limit_fails_without_truncation_or_json_mutation(self):
        self.create()
        report = inspect_database(self.path, limits=CatalogLimits(max_diagram_nodes=1))
        before = to_json(report)
        with self.assertRaises(CatalogError) as caught:
            to_mermaid(report)
        self.assertEqual(caught.exception.code, 'diagram_limit')
        self.assertEqual(to_json(report), before)
        self.assertTrue(report['complete'])
        self.assertEqual(len(report['tables']), 2)

    def test_public_api_rejects_invalid_flags_limits_and_paths(self):
        self.create()
        for keyword in ({'include_sql': 1}, {'include_internal': 'true'}, {'limits': None}):
            with self.subTest(keyword=keyword), self.assertRaises(ValueError):
                inspect_database(self.path, **keyword)
        for keyword in ({'max_objects': True}, {'max_text_bytes': 0},
                        {'max_diagram_nodes': 10_001}, {'busy_timeout_ms': -1}):
            with self.subTest(keyword=keyword), self.assertRaises(ValueError):
                CatalogLimits(**keyword)
        with self.assertRaises(ValueError):
            inspect_database(None)

    def test_module_cli_complete_partial_and_operational_exit_codes(self):
        self.create()
        complete = self.run_cli(self.path)
        self.assertEqual(complete.returncode, 0, complete.stderr)
        self.assertEqual(complete.stderr, '')
        self.assertEqual(json.loads(complete.stdout), inspect_database(self.path))
        partial = self.run_cli(self.path, '--max-objects', '1')
        self.assertEqual(partial.returncode, 2, partial.stderr)
        partial_report = json.loads(partial.stdout)
        self.assertFalse(partial_report['complete'])
        self.assertFalse(partial_report['graph']['complete'])
        self.assertIsNone(partial_report['catalog_sha256'])
        absent = self.root / 'PRIVATE_ABSENT_SOURCE.sqlite'
        failed = self.run_cli(absent)
        self.assertEqual(failed.returncode, 3)
        self.assertEqual(failed.stdout, '')
        self.assertIn('Erro operacional', failed.stderr)
        self.assertNotIn(str(absent), failed.stderr)
        self.assertFalse(absent.exists())

    def test_cli_help_version_and_usage_errors(self):
        for flag in ('--help', '--version'):
            with self.subTest(flag=flag):
                result = self.run_cli(flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout)
                self.assertEqual(result.stderr, '')
        self.create()
        for arguments in ([], [self.path, '--max-objects', 'true'],
                          [self.path, '--max-objects', '0'],
                          [self.path, '--max-objects', '50001'],
                          [self.path, '--busy-timeout-ms', '-1'],
                          [self.path, '--format', 'PRIVATE_UNKNOWN_FORMAT'],
                          [self.path, '--max-o', '1']):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 3)
                self.assertEqual(result.stdout, '')
                self.assertIn('Erro de uso:', result.stderr)
                self.assertNotIn('PRIVATE_UNKNOWN_FORMAT', result.stderr)
                self.assertNotIn(str(self.root), result.stderr)

    def test_cli_markdown_mermaid_and_diagram_error(self):
        self.create()
        for name, render in (('markdown', to_markdown), ('mermaid', to_mermaid)):
            with self.subTest(format=name):
                result = self.run_cli(self.path, '--format', name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, render(inspect_database(self.path)))
        limited = self.run_cli(self.path, '--format', 'mermaid', '--max-diagram-nodes', '1')
        self.assertEqual(limited.returncode, 3)
        self.assertEqual(limited.stdout, '')
        self.assertIn('diagram_limit', limited.stderr)

    def test_cli_inclusion_flags_are_wired_to_the_public_api(self):
        self.create("CREATE TABLE example(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "value TEXT UNIQUE DEFAULT 'synthetic schema default')")
        result = self.run_cli(self.path, '--include-sql', '--include-internal',
                              '--busy-timeout-ms', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report, inspect_database(self.path, include_sql=True,
                                                  include_internal=True,
                                                  limits=CatalogLimits(busy_timeout_ms=0)))
        self.assertIn('sqlite_sequence', {item['name'] for item in report['objects']})
        self.assertTrue(all('sql' in item for item in report['objects']))
        self.assertEqual(report['tables'][0]['columns'][1]['default_sql'],
                         "'synthetic schema default'")

    def test_cli_new_output_matches_report_and_preexisting_file_survives(self):
        self.create()
        destination = self.root / 'new-report.json'
        result = self.run_cli(self.path, '--output', destination)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(destination.read_text(encoding='utf-8'), to_json(inspect_database(self.path)))
        destination.write_text('EXISTING_SYNTHETIC_CONTENT', encoding='utf-8')
        failed = self.run_cli(self.path, '--output', destination)
        self.assertEqual(failed.returncode, 3)
        self.assertIn('output_exists', failed.stderr)
        self.assertEqual(destination.read_text(encoding='utf-8'), 'EXISTING_SYNTHETIC_CONTENT')
        self.assert_no_temporary_reports()

    def test_cli_partial_output_is_published_with_exit_two(self):
        self.create()
        destination = self.root / 'partial.json'
        result = self.run_cli(self.path, '--max-objects', '1', '--output', destination)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(json.loads(destination.read_text(encoding='utf-8'))['status'], 'partial')
        self.assert_no_temporary_reports()

    def test_output_cannot_overwrite_the_source_database(self):
        self.create()
        before = self.path.read_bytes()
        result = self.run_cli(self.path, '--output', self.path)
        self.assertEqual(result.returncode, 3)
        self.assertIn('output_exists', result.stderr)
        self.assertEqual(self.path.read_bytes(), before)
        self.assert_no_temporary_reports()

    def test_exclusive_link_detects_a_concurrent_destination(self):
        destination = self.root / 'raced.json'
        link = os.link

        def concurrent_link(source, target):
            Path(target).write_text('CONCURRENT_WRITER', encoding='utf-8')
            return link(source, target)

        with patch.object(cli.os, 'link', side_effect=concurrent_link) as operation:
            with self.assertRaises(CatalogError) as caught:
                cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(caught.exception.code, 'output_exists')
        self.assertEqual(operation.call_count, 1)
        self.assertEqual(destination.read_text(encoding='utf-8'), 'CONCURRENT_WRITER')
        self.assert_no_temporary_reports()

    def test_fsync_failure_removes_temporary_and_publishes_nothing(self):
        destination = self.root / 'unpublished.json'
        with patch.object(cli.os, 'fsync', side_effect=OSError('PRIVATE_FSYNC_BACKEND')):
            with self.assertRaises(CatalogError) as caught:
                cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(caught.exception.code, 'output_write')
        self.assertNotIn('PRIVATE_FSYNC_BACKEND', str(caught.exception))
        self.assertFalse(destination.exists())
        self.assert_no_temporary_reports()

    def test_unsupported_exclusive_link_has_no_fallback_or_leftovers(self):
        destination = self.root / 'unpublished.json'
        with patch.object(cli.os, 'link', side_effect=OSError(errno.ENOTSUP, 'PRIVATE_LINK_BACKEND')) as operation:
            with self.assertRaises(CatalogError) as caught:
                cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(operation.call_count, 1)
        self.assertEqual(caught.exception.code, 'output_write')
        self.assertNotIn('PRIVATE_LINK_BACKEND', str(caught.exception))
        self.assertFalse(destination.exists())
        self.assert_no_temporary_reports()

    def test_output_parent_must_exist_and_encoding_failure_leaves_no_file(self):
        destination = self.root / 'missing-directory' / 'report.json'
        with self.assertRaises(CatalogError) as missing:
            cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(missing.exception.code, 'output_write')
        self.assertFalse(destination.parent.exists())
        destination = self.root / 'encoding.json'
        with self.assertRaises(CatalogError) as encoding:
            cli._publish_new(destination, '\ud800')
        self.assertEqual(encoding.exception.code, 'output_write')
        self.assertFalse(destination.exists())
        self.assert_no_temporary_reports()

    def test_publisher_fsyncs_before_linking_and_removes_temporary_name(self):
        destination = self.root / 'ordered.json'
        events = []
        original_fsync, original_link = os.fsync, os.link

        def sync(descriptor):
            events.append('fsync')
            return original_fsync(descriptor)

        def link(source, target):
            events.append('link')
            self.assertEqual(Path(source).parent, destination.parent)
            self.assertEqual(Path(source).read_text(encoding='utf-8'), 'NEW_REPORT\n')
            return original_link(source, target)

        with patch.object(cli.os, 'fsync', side_effect=sync), patch.object(cli.os, 'link', side_effect=link):
            cli._publish_new(destination, 'NEW_REPORT\n')
        self.assertEqual(events, ['fsync', 'link'])
        self.assertEqual(destination.read_text(encoding='utf-8'), 'NEW_REPORT\n')
        self.assert_no_temporary_reports()

    def test_cli_closed_stdout_pipe_returns_operational_error_without_shutdown_traceback(self):
        self.create('CREATE TABLE small_example(x)')
        reader, writer = os.pipe()
        os.close(reader)  # No reader exists, including before process startup.
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'sqlite_catalog_report', str(self.path)],
                cwd=self.root, env=self.environment(), stdout=writer,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', timeout=20,
            )
        finally:
            os.close(writer)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('output_write', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('Exception ignored', result.stderr)
        self.assertNotIn(str(self.path), result.stderr)

    def test_cli_stdout_write_failure_is_sanitized(self):
        self.create('CREATE TABLE small_example(x)')

        class BrokenOutput(io.StringIO):
            def write(self, text):
                raise OSError('PRIVATE_STDOUT_BACKEND')

        diagnostic = io.StringIO()
        with patch.object(cli.sys, 'stdout', BrokenOutput()), patch.object(cli.sys, 'stderr', diagnostic):
            status = cli.main([str(self.path)])
        self.assertEqual(status, 3)
        self.assertIn('output_write', diagnostic.getvalue())
        self.assertNotIn('PRIVATE_STDOUT_BACKEND', diagnostic.getvalue())


if __name__ == '__main__':
    unittest.main()
