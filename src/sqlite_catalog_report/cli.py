"""Command line interface and exclusive creation of report files."""
import argparse
from dataclasses import asdict
import os
from pathlib import Path
import sys
import tempfile

from . import __version__
from .api import inspect_database
from .model import CatalogError, CatalogLimits
from .report import to_json, to_markdown, to_mermaid


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError('Argumentos inválidos. Use --help para consultar o formato aceito.')


def _parser():
    parser = _Parser(prog='sqlite-catalog-report', allow_abbrev=False,
                     description='Documenta o esquema main de um arquivo SQLite sem exportar registros.')
    parser.add_argument('database', help='Arquivo SQLite local existente.')
    parser.add_argument('--version', action='version', version='sqlite-catalog-report ' + __version__)
    parser.add_argument('--format', choices=['json', 'markdown', 'mermaid'], default='json')
    parser.add_argument('--include-sql', action='store_true', help='Incluir texto das definições e dos defaults.')
    parser.add_argument('--include-internal', action='store_true', help='Incluir objetos internos sqlite_.')
    parser.add_argument('--output', type=Path, help='Arquivo NOVO; diretório pai já deve existir.')
    for key, value in asdict(CatalogLimits()).items():
        parser.add_argument('--' + key.replace('_', '-'), type=int, default=value,
                            help='Limite explícito (padrão: %(default)s).')
    return parser


def _publish_new(destination, text):
    # Adapted from LOFRANO TECNOLOGIA's MIT wheel-record-audit publisher.
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.sqlite-catalog-report-', suffix='.tmp', dir=destination.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError:
        raise CatalogError('output_exists', 'O destino já existe. Escolha um arquivo novo; nada foi sobrescrito.') from None
    except (OSError, UnicodeError):
        raise CatalogError('output_write', 'Não foi possível publicar um relatório novo. Confira o diretório e o suporte a links exclusivos.') from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        try:
            limits = CatalogLimits(**{key: getattr(args, key) for key in asdict(CatalogLimits())})
        except ValueError:
            raise _UsageError('Limite inválido. Consulte os valores permitidos na documentação.') from None
        report = inspect_database(args.database, include_sql=args.include_sql,
                                  include_internal=args.include_internal, limits=limits)
        text = {'json': to_json, 'markdown': to_markdown, 'mermaid': to_mermaid}[args.format](report)
        if args.output is not None:
            _publish_new(args.output, text)
        else:
            try:
                sys.stdout.write(text)
                sys.stdout.flush()
            except (OSError, UnicodeError):
                # A buffered broken pipe must not be retried by interpreter
                # shutdown (which would otherwise replace exit3 with exit120).
                try:
                    fd = sys.stdout.fileno()
                    sink = os.open(os.devnull, os.O_WRONLY)
                    try:
                        os.dup2(sink, fd)
                    finally:
                        os.close(sink)
                except (OSError, ValueError, AttributeError):
                    pass
                raise CatalogError('output_write', 'Não foi possível escrever o relatório na saída padrão.') from None
        return 0 if report['complete'] else 2
    except _UsageError as error:
        print('Erro de uso: ' + str(error), file=sys.stderr)
        return 3
    except CatalogError as error:
        print('Erro operacional (' + error.code + '): ' + str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
