"""Pure analysis of declared foreign keys and stable catalog fingerprints.

Only captured ordinary tables form graph nodes.  A resolved edge describes a
declaration and its metadata, rather than validation of stored rows or a claim
that an import in the resulting order would succeed.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from .model import ascii_fold


def _by_identifier(items, key="name"):
    result = defaultdict(list)
    for item in items:
        name = item.get(key)
        if isinstance(name, str):
            result[ascii_fold(name)].append(item)
    return result


def _column_metadata(table):
    """Return a name lookup and whether its captured shape is coherent."""
    columns = table.get("columns", [])
    lookup = _by_identifier(columns)
    coherent = (
        table.get("details_complete") is True
        and all(isinstance(column.get("name"), str) for column in columns)
        and all(len(matches) == 1 for matches in lookup.values())
    )
    return lookup, coherent


def _actual_column(name, lookup):
    if isinstance(name, str):
        matches = lookup.get(ascii_fold(name), [])
        if len(matches) == 1:
            return matches[0]["name"]
    return None


def _primary_key(table):
    """Return an ordered PK, distinguishing absent PKs from broken positions."""
    keyed = []
    for column in table.get("columns", []):
        position = column.get("primary_key_position")
        if type(position) is not int or position < 0:
            return [], False
        if position:
            keyed.append((position, column["name"]))
    keyed.sort()
    coherent = [position for position, _ in keyed] == list(range(1, len(keyed) + 1))
    return [name for _, name in keyed], coherent


def _relationship(source, foreign_key, table_lookup, object_lookup, metadata):
    declared_target = foreign_key.get("target_table")
    parts = list(foreign_key.get("columns", []))
    # seq is metadata, not the incoming container order.  Keep malformed rows
    # inspectable without asking Python to compare unrelated value types.
    parts.sort(key=lambda part: (type(part.get("seq")) is not int,
                                 part.get("seq") if type(part.get("seq")) is int else 0))
    declared_sources = [part.get("from") for part in parts]
    declared_targets = [part.get("to") for part in parts]
    source_lookup, source_coherent = metadata[source["name"]]
    actual_sources = [_actual_column(name, source_lookup) for name in declared_sources]
    relation = {
        "source": source["name"],
        "foreign_key_id": foreign_key.get("id"),
        "target_declared": declared_target,
        "target": None,
        "source_columns": [actual if actual is not None else declared
                           for actual, declared in zip(actual_sources, declared_sources)],
        "target_columns": declared_targets,
        "resolution": "metadata_inconsistent",
        "on_update": foreign_key.get("on_update"),
        "on_delete": foreign_key.get("on_delete"),
        "match": foreign_key.get("match"),
    }

    if not isinstance(declared_target, str):
        return relation
    folded = ascii_fold(declared_target)
    targets = table_lookup.get(folded, [])
    if len(targets) > 1:
        return relation
    if not targets:
        objects = object_lookup.get(folded, [])
        # SQLite has distinct namespaces for triggers and tables; a trigger
        # sharing a table's name must never hide the ordinary table object.
        ordinary = [obj for obj in objects if obj.get("type") == "table"]
        if ordinary:
            relation["target"] = sorted(obj["name"] for obj in ordinary)[0]
            relation["resolution"] = "target_not_captured"
        elif objects:
            relation["target"] = sorted(obj["name"] for obj in objects)[0]
            relation["resolution"] = "target_not_table"
        else:
            relation["resolution"] = "target_missing"
        return relation

    target = targets[0]
    relation["target"] = target["name"]
    target_lookup, target_coherent = metadata[target["name"]]
    omitted = all(name is None for name in declared_targets)
    actual_targets = [_actual_column(name, target_lookup) for name in declared_targets]
    if not omitted:
        relation["target_columns"] = [actual if actual is not None else declared
                                      for actual, declared in zip(actual_targets, declared_targets)]

    valid_sequence = (
        bool(parts)
        and all(type(part.get("seq")) is int for part in parts)
        and [part["seq"] for part in parts] == list(range(len(parts)))
    )
    if (not source_coherent or not target_coherent or not valid_sequence
            or type(foreign_key.get("id")) is not int
            or foreign_key["id"] < 0
            or (not omitted and any(name is None for name in declared_targets))):
        return relation
    if any(name is None for name in actual_sources):
        relation["resolution"] = "source_columns_missing"
        return relation
    if omitted:
        primary_key, coherent = _primary_key(target)
        if not coherent:
            return relation
        if len(primary_key) != len(parts):
            relation["resolution"] = "pk_arity_mismatch"
            return relation
        relation["target_columns"] = primary_key
    elif any(name is None for name in actual_targets):
        relation["resolution"] = "target_columns_missing"
        return relation
    relation["resolution"] = "resolved"
    return relation


def _groups(nodes, relations):
    """Iterative Kosaraju SCCs, then dependency waves of their condensation."""
    parents = {name: set() for name in nodes}
    children = {name: set() for name in nodes}
    for relation in relations:
        if relation["resolution"] == "resolved":
            source, target = relation["source"], relation["target"]
            parents[source].add(target)
            children[target].add(source)

    seen, finished = set(), []
    for start in nodes:
        if start in seen:
            continue
        seen.add(start)
        stack = [(start, iter(sorted(parents[start])))]
        while stack:
            node, neighbours = stack[-1]
            following = next(neighbours, None)
            if following is None:
                finished.append(node)
                stack.pop()
            elif following not in seen:
                seen.add(following)
                stack.append((following, iter(sorted(parents[following]))))

    component_of, components = {}, []
    for start in reversed(finished):
        if start in component_of:
            continue
        index = len(components)
        members, stack = [], [start]
        component_of[start] = index
        while stack:
            node = stack.pop()
            members.append(node)
            for following in children[node]:
                if following not in component_of:
                    component_of[following] = index
                    stack.append(following)
        components.append(sorted(members))

    dependencies = {index: set() for index in range(len(components))}
    dependents = {index: set() for index in range(len(components))}
    for node in nodes:
        source = component_of[node]
        for parent in parents[node]:
            target = component_of[parent]
            if source != target:
                dependencies[source].add(target)
                dependents[target].add(source)
    pending = {index: len(values) for index, values in dependencies.items()}
    ready = sorted((index for index, count in pending.items() if count == 0),
                   key=lambda index: components[index])
    order, waves = [], []
    while ready:
        waves.append(ready)
        order.extend(ready)
        following = []
        for index in ready:
            for child in dependents[index]:
                pending[child] -= 1
                if pending[child] == 0:
                    following.append(child)
        ready = sorted(following, key=lambda index: components[index])

    positions = {component: position for position, component in enumerate(order)}
    groups = []
    for component in order:
        members = components[component]
        groups.append({
            "id": f"g{positions[component]}",
            "members": members,
            "cyclic": len(members) > 1 or members[0] in parents[members[0]],
            "depends_on": [f"g{positions[parent]}" for parent in
                           sorted(dependencies[component], key=positions.__getitem__)],
        })
    layers = [[f"g{positions[component]}" for component in wave] for wave in waves]
    return groups, layers


def analyze_relationships(tables, objects, *, capture_complete=True) -> dict:
    """Resolve observed FK metadata without accessing SQLite or the filesystem."""
    tables = list(tables)
    objects = list(objects)
    table_lookup = _by_identifier(tables)
    object_lookup = _by_identifier(objects)
    metadata = {table["name"]: _column_metadata(table) for table in tables}
    relations = [
        _relationship(table, foreign_key, table_lookup, object_lookup, metadata)
        for table in tables for foreign_key in table.get("foreign_keys", [])
    ]
    relations.sort(key=lambda relation: (relation["source"], relation["foreign_key_id"]))
    groups, layers = _groups(sorted(metadata), relations)
    return {
        "complete": capture_complete,
        "relations": relations,
        "groups": groups,
        "layers": layers,
        "unresolved_count": sum(relation["resolution"] != "resolved" for relation in relations),
    }


def _without_sql(value):
    if isinstance(value, dict):
        return {key: _without_sql(item) for key, item in value.items()
                if key not in {"sql", "default_sql"}}
    if isinstance(value, (list, tuple)):
        return [_without_sql(item) for item in value]
    return value


def catalog_fingerprint(report) -> str | None:
    """Hash complete captured facts, omitting presentation and environment."""
    if report.get("complete") is not True or report.get("graph", {}).get("complete") is not True:
        return None
    projection = _without_sql({"objects": report["objects"], "tables": report["tables"]})
    canonical = json.dumps(projection, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
