"""Public budgets and stable diagnostics for schema-only catalog capture."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CatalogLimits:
    max_objects: int = 5000
    max_detail_rows: int = 100_000
    max_text_bytes: int = 262_144
    max_total_text_bytes: int = 16_777_216
    max_vm_steps: int = 2_000_000
    max_issues: int = 1000
    busy_timeout_ms: int = 1000
    max_diagram_nodes: int = 200

    def __post_init__(self):
        ceilings = {'max_objects': 50_000, 'max_detail_rows': 1_000_000,
                    'max_text_bytes': 4_194_304, 'max_total_text_bytes': 134_217_728,
                    'max_vm_steps': 20_000_000, 'max_issues': 10_000,
                    'busy_timeout_ms': 10_000, 'max_diagram_nodes': 10_000}
        for key, value in asdict(self).items():
            minimum = 0 if key == 'busy_timeout_ms' else 1
            if type(value) is not int or not minimum <= value <= ceilings[key]:
                raise ValueError('Limite inválido: ' + key)


class CatalogError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    object: str | None = None


def ascii_fold(value: str) -> str:
    return value.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))


def sort_issues(issues):
    rank = {'incomplete': 0, 'warning': 1}
    return sorted(issues, key=lambda item: (rank[item.severity], item.object or '', item.code, item.message))
