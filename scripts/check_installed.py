"""Exercise the wheel outside its source tree, with no runtime dependencies."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def main(argv=None):
    parser = argparse.ArgumentParser(description='Confere o wheel em ambiente temporário separado.')
    parser.add_argument('--wheel', type=Path, required=True)
    args = parser.parse_args(argv)
    wheel = args.wheel.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='sqlite-catalog-installed-') as temporary:
        work = Path(temporary)
        environment = work / 'environment'
        venv.EnvBuilder(with_pip=True).create(environment)
        binaries = environment / ('Scripts' if os.name == 'nt' else 'bin')
        python = binaries / ('python.exe' if os.name == 'nt' else 'python')
        entry = binaries / ('sqlite-catalog-report.exe' if os.name == 'nt' else 'sqlite-catalog-report')
        subprocess.run([str(python), '-I', '-m', 'pip', 'install', '--no-deps', '--disable-pip-version-check', str(wheel)], cwd=work, check=True)
        database = work / 'samples/exemplo.sqlite'
        subprocess.run([sys.executable, str(root / 'scripts/make_sample.py'), '--output', str(database)], cwd=work, check=True)
        command = [str(python), '-I', '-m', 'sqlite_catalog_report', str(database)]
        normal = subprocess.run(command, cwd=work, text=True, capture_output=True, check=True)
        report = json.loads(normal.stdout)
        assert report['complete'] is True and report['catalog_sha256'], report
        assert report['summary']['ordinary_tables'] == 6, report['summary']
        assert any(group['cyclic'] for group in report['graph']['groups']), report['graph']
        assert 'REGISTRO_FICTICIO_NAO_EXPORTAR' not in normal.stdout
        assert 'PADRAO_FICTICIO' not in normal.stdout
        sql = subprocess.run(command + ['--include-sql'], cwd=work, text=True, capture_output=True, check=True)
        assert json.loads(sql.stdout)['catalog_sha256'] == report['catalog_sha256']
        assert 'PADRAO_FICTICIO' in sql.stdout and 'REGISTRO_FICTICIO_NAO_EXPORTAR' not in sql.stdout
        partial = subprocess.run(command + ['--max-objects', '1'], cwd=work, text=True, capture_output=True)
        assert partial.returncode == 2 and json.loads(partial.stdout)['catalog_sha256'] is None
        for kind in ('markdown', 'mermaid'):
            rendered = subprocess.run(command + ['--format', kind], cwd=work, text=True, capture_output=True, check=True)
            assert rendered.stdout and 'REGISTRO_FICTICIO_NAO_EXPORTAR' not in rendered.stdout
        destination = work / 'catalogo.json'
        subprocess.run(command + ['--output', str(destination)], cwd=work, check=True)
        previous = destination.read_bytes()
        repeat = subprocess.run(command + ['--output', str(destination)], cwd=work, text=True, capture_output=True)
        assert repeat.returncode == 3 and destination.read_bytes() == previous
        version = subprocess.run([str(entry), '--version'], cwd=work, text=True, capture_output=True, check=True)
        assert version.stdout.strip() == 'sqlite-catalog-report 1.0.0'
        probe = ('import importlib.metadata as m, json, sqlite_catalog_report as s; '
                 'print(json.dumps({"file":s.__file__,"dependencies":m.requires("sqlite-catalog-report") or []}))')
        installed = json.loads(subprocess.check_output([str(python), '-I', '-c', probe], cwd=work, text=True))
        assert Path(installed['file']).is_relative_to(environment)
        assert not [d for d in installed['dependencies'] if 'extra ==' not in d]
        print(json.dumps({'installedDistribution': True, 'outsideSourceTree': True,
                          'runtimeThirdPartyDependencies': 0, 'formats': 3, 'partialExit': 2,
                          'noOverwrite': True, 'entryPoint': True, 'rowCanaryAbsent': True}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
