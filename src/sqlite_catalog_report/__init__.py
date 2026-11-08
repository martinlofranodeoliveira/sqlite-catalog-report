"""Schema-only documentation of local SQLite databases."""
__version__ = '1.0.0'

from .api import inspect_database
from .model import CatalogError, CatalogLimits
from .report import to_json, to_markdown, to_mermaid

__all__ = ['CatalogError', 'CatalogLimits', 'inspect_database', 'to_json',
           'to_markdown', 'to_mermaid', '__version__']
