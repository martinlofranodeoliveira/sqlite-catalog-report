"""Create a synthetic SQLite fixture, publishing only a new database file."""
import argparse
import os
from pathlib import Path
import sqlite3
import tempfile


def make_sample(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.catalog-sample-', suffix='.sqlite', dir=destination.parent)
        os.close(fd)
        temporary = Path(name)
        schema = (Path(__file__).resolve().parents[1] / 'examples/schema.sql').read_text(encoding='utf-8')
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(schema)
            connection.commit()
        finally:
            connection.close()
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Cria um banco sintético NOVO para os exemplos do catálogo.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        make_sample(args.output)
    except (OSError, sqlite3.Error):
        parser.exit(3, 'Não foi possível criar um banco novo. Confira o diretório e escolha um destino inexistente.\n')
    print('Banco sintético criado.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
