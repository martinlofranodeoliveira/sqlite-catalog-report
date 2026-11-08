"""Compose the private capture and the pure relationship analysis."""
from .capture import capture_database
from .graph import analyze_relationships, catalog_fingerprint
from .model import CatalogLimits


def inspect_database(path, *, include_sql=False, include_internal=False,
                     limits=CatalogLimits()):
    report = capture_database(path, include_sql=include_sql,
                              include_internal=include_internal, limits=limits)
    report['graph'] = analyze_relationships(report['tables'], report['objects'],
                                            capture_complete=report['complete'])
    report['catalog_sha256'] = catalog_fingerprint(report)
    return report
