"""Relationship analysis uses metadata only, including malformed declarations."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from sqlite_catalog_report.graph import analyze_relationships, catalog_fingerprint


def column(name="id", *, pk=0, cid=0):
    return {"cid": cid, "name": name, "declared_type": "INTEGER",
            "not_null_declared": False, "primary_key_position": pk,
            "hidden_code": 0, "kind": "ordinary", "default_present": False,
            "default_sha256": None}


def foreign_key(target, pairs=(("parent_id", "id"),), *, identifier=0):
    return {"id": identifier, "target_table": target, "on_update": "NO ACTION",
            "on_delete": "CASCADE", "match": "NONE",
            "columns": [{"seq": seq, "from": source, "to": destination}
                        for seq, (source, destination) in enumerate(pairs)]}


def table(name, columns=None, foreign_keys=(), *, complete=True):
    return {"name": name, "details_complete": complete,
            "columns": [column(pk=1)] if columns is None else columns,
            "indexes": [], "foreign_keys": list(foreign_keys)}


def inventory(tables):
    return [{"type": "table", "sqlite_type": "table", "name": item["name"],
             "table_name": item["name"]} for item in tables]


class RelationshipTests(unittest.TestCase):
    def analyze(self, tables, objects=None, **kwargs):
        return analyze_relationships(tables, inventory(tables) if objects is None else objects,
                                     **kwargs)

    def relation(self, parent, child, objects=None):
        return self.analyze([parent, child], objects)["relations"][0]

    def test_empty_graph(self):
        self.assertEqual(self.analyze([]), {"complete": True, "relations": [],
                                          "groups": [], "layers": [], "unresolved_count": 0})

    def test_ascii_case_resolution_preserves_real_names_and_declared_target(self):
        parent = table("Parent", [column("ID", pk=1)])
        child = table("Child", [column("Parent_Id")],
                      [foreign_key("PARENT", [("parent_ID", "id")])])
        relation = self.relation(parent, child)
        self.assertEqual(relation, {
            "source": "Child", "foreign_key_id": 0, "target_declared": "PARENT",
            "target": "Parent", "source_columns": ["Parent_Id"], "target_columns": ["ID"],
            "resolution": "resolved", "on_update": "NO ACTION", "on_delete": "CASCADE",
            "match": "NONE"})

    def test_unicode_case_is_not_sqlite_identifier_equivalence(self):
        upper = table("Ä", [column("ÄID", pk=1)])
        child = table("child", [column("ref")], [foreign_key("ä", [("ref", "ÄID")])])
        self.assertEqual(self.relation(upper, child)["resolution"], "target_missing")
        lower = table("ä", [column("äID", pk=1)])
        graph = self.analyze([upper, lower, child])
        self.assertEqual(graph["relations"][0]["target"], "ä")
        self.assertEqual(graph["relations"][0]["resolution"], "target_columns_missing")
        child["foreign_keys"][0]["columns"][0]["to"] = "äID"
        self.assertEqual(self.analyze([upper, lower, child])["relations"][0]["resolution"],
                         "resolved")
        self.assertEqual({tuple(group["members"]) for group in graph["groups"]},
                         {("Ä",), ("ä",), ("child",)})

    def test_composite_omitted_target_uses_pk_positions_and_fk_sequence(self):
        parent = table("parent", [column("second", pk=2, cid=0),
                                  column("first", pk=1, cid=9)])
        key = foreign_key("parent", [("a", None), ("b", None)])
        key["columns"].reverse()
        child = table("child", [column("b"), column("a")], [key])
        result = self.relation(parent, child)
        self.assertEqual(result["source_columns"], ["a", "b"])
        self.assertEqual(result["target_columns"], ["first", "second"])
        self.assertEqual(result["resolution"], "resolved")

    def test_explicit_composite_target_order_follows_sequence(self):
        parent = table("parent", [column("first", pk=1), column("second", pk=2)])
        key = foreign_key("parent", [("a", "SECOND"), ("b", "FIRST")])
        key["columns"].reverse()
        child = table("child", [column("a"), column("b")], [key])
        self.assertEqual(self.relation(parent, child)["target_columns"], ["second", "first"])

    def test_omitted_targets_require_exact_primary_key_arity(self):
        child = table("child", [column("parent_id")], [foreign_key("parent", [("parent_id", None)])])
        for columns in ([], [column("a", pk=1), column("b", pk=2)]):
            with self.subTest(columns=columns):
                relation = self.relation(table("parent", columns), child)
                self.assertEqual(relation["resolution"], "pk_arity_mismatch")
                self.assertEqual(relation["target_columns"], [None])

    def test_missing_source_and_target_columns_remain_declared(self):
        parent = table("parent")
        child = table("child", [], [foreign_key("parent")])
        relation = self.relation(parent, child)
        self.assertEqual(relation["resolution"], "source_columns_missing")
        self.assertEqual(relation["source_columns"], ["parent_id"])
        child["columns"] = [column("parent_id")]
        child["foreign_keys"][0]["columns"][0]["to"] = "absent"
        relation = self.relation(parent, child)
        self.assertEqual(relation["resolution"], "target_columns_missing")
        self.assertEqual(relation["target_columns"], ["absent"])

    def test_all_target_failure_reasons_and_no_invented_nodes(self):
        child = table("child", [column("parent_id")], [foreign_key("parent")])
        for kind, resolution in [(None, "target_missing"), ("table", "target_not_captured"),
                                 ("view", "target_not_table"), ("virtual", "target_not_table"),
                                 ("shadow", "target_not_table"), ("index", "target_not_table"),
                                 ("trigger", "target_not_table")]:
            with self.subTest(kind=kind):
                objects = inventory([child])
                if kind is not None:
                    objects.append({"type": kind, "name": "Parent"})
                graph = self.analyze([child], objects)
                self.assertEqual(graph["relations"][0]["resolution"], resolution)
                self.assertEqual(graph["groups"], [{"id": "g0", "members": ["child"],
                                                    "cyclic": False, "depends_on": []}])
                self.assertEqual(graph["unresolved_count"], 1)
                self.assertTrue(graph["complete"])

    def test_trigger_namespace_does_not_mask_table(self):
        parent = table("Parent")
        child = table("child", [column("parent_id")], [foreign_key("PARENT")])
        objects = inventory([parent, child]) + [{"type": "trigger", "name": "Parent"}]
        self.assertEqual(self.relation(parent, child, objects)["resolution"], "resolved")
        for order in (objects, list(reversed(objects))):
            graph = self.analyze([child], order)
            self.assertEqual(graph["relations"][0]["resolution"], "target_not_captured")

    def test_partial_column_metadata_cannot_resolve(self):
        for incomplete in ("source", "target"):
            with self.subTest(incomplete=incomplete):
                parent = table("parent", complete=incomplete != "target")
                child = table("child", [column("parent_id")], [foreign_key("parent")],
                              complete=incomplete != "source")
                graph = self.analyze([parent, child], capture_complete=False)
                self.assertEqual(graph["relations"][0]["resolution"], "metadata_inconsistent")
                self.assertFalse(graph["complete"])
                self.assertTrue(all(not group["depends_on"] for group in graph["groups"]))

    def test_invalid_sequences_and_mixed_omission_are_metadata_inconsistent(self):
        parent = table("parent", [column("a", pk=1), column("b", pk=2)])
        cases = [[], [{"seq": 1, "from": "a", "to": "a"}],
                 [{"seq": 0, "from": "a", "to": "a"},
                  {"seq": 0, "from": "b", "to": "b"}],
                 [{"seq": 0, "from": "a", "to": None},
                  {"seq": 1, "from": "b", "to": "b"}]]
        for parts in cases:
            with self.subTest(parts=parts):
                key = foreign_key("parent")
                key["columns"] = parts
                child = table("child", [column("a"), column("b")], [key])
                self.assertEqual(self.relation(parent, child)["resolution"], "metadata_inconsistent")

    def test_duplicate_or_gapped_pk_positions_are_not_inferred(self):
        child = table("child", [column("a"), column("b")],
                      [foreign_key("parent", [("a", None), ("b", None)])])
        for positions in ((1, 1), (1, 3), (-1, 2)):
            with self.subTest(positions=positions):
                parent = table("parent", [column("a", pk=positions[0]),
                                          column("b", pk=positions[1])])
                self.assertEqual(self.relation(parent, child)["resolution"], "metadata_inconsistent")

    def test_duplicate_identifier_metadata_is_not_resolved(self):
        parent = table("parent", [column("id"), column("ID")])
        child = table("child", [column("parent_id")], [foreign_key("parent")])
        self.assertEqual(self.relation(parent, child)["resolution"], "metadata_inconsistent")

    def test_relations_are_sorted_by_source_then_numeric_id(self):
        parent = table("parent")
        child = table("child", [column("parent_id")],
                      [foreign_key("parent", identifier=index) for index in (10, 2, 0)])
        another = table("another", [column("parent_id")], [foreign_key("parent", identifier=1)])
        graph = self.analyze([parent, child, another])
        self.assertEqual([(r["source"], r["foreign_key_id"]) for r in graph["relations"]],
                         [("another", 1), ("child", 0), ("child", 2), ("child", 10)])

    def test_self_loop_and_mutual_cycle_are_structural_groups(self):
        a = table("a", foreign_keys=[foreign_key("b", [("id", "id")])])
        b = table("b", foreign_keys=[foreign_key("a", [("id", "id")])])
        loop = table("self", foreign_keys=[foreign_key("self", [("id", "id")])])
        child = table("child", foreign_keys=[foreign_key("b", [("id", "id")])])
        graph = self.analyze([child, loop, b, a])
        self.assertEqual(graph["groups"], [
            {"id": "g0", "members": ["a", "b"], "cyclic": True, "depends_on": []},
            {"id": "g1", "members": ["self"], "cyclic": True, "depends_on": []},
            {"id": "g2", "members": ["child"], "cyclic": False, "depends_on": ["g0"]}])
        self.assertEqual(graph["layers"], [["g0", "g1"], ["g2"]])

    def test_waves_are_ready_together_and_ties_are_lexicographic(self):
        a, z = table("a"), table("z")
        b = table("b", foreign_keys=[foreign_key("a", [("id", "id")])])
        c = table("c", foreign_keys=[foreign_key("a", [("id", "id")]),
                                     foreign_key("z", [("id", "id")], identifier=1)])
        graph = self.analyze([c, z, b, a])
        self.assertEqual([g["members"] for g in graph["groups"]], [["a"], ["z"], ["b"], ["c"]])
        self.assertEqual(graph["layers"], [["g0", "g1"], ["g2", "g3"]])
        self.assertEqual(graph["groups"][-1]["depends_on"], ["g0", "g1"])
        reversed_tables = [a, b, z, c]
        self.assertEqual(graph, self.analyze(reversed_tables, list(reversed(inventory(reversed_tables)))))

    def test_dependencies_are_sorted_by_numeric_group_id(self):
        parents = [table(f"p{index:02}") for index in range(12)]
        child = table("child", foreign_keys=[foreign_key(parent["name"], [("id", "id")],
                                                         identifier=index)
                                               for index, parent in enumerate(reversed(parents))])
        graph = self.analyze([child, *parents])
        self.assertEqual(graph["groups"][-1]["depends_on"], [f"g{index}" for index in range(12)])

    def test_long_chain_and_long_cycle_do_not_use_python_recursion(self):
        size = 2200
        tables = [table(f"t{index:04}", foreign_keys=[] if index == 0 else
                        [foreign_key(f"t{index - 1:04}", [("id", "id")])])
                  for index in range(size)]
        graph = self.analyze(list(reversed(tables)))
        self.assertEqual(len(graph["groups"]), size)
        self.assertEqual(graph["groups"][0]["members"], ["t0000"])
        self.assertEqual(graph["groups"][-1]["depends_on"], [f"g{size - 2}"])
        tables[0]["foreign_keys"] = [foreign_key(f"t{size - 1:04}", [("id", "id")])]
        graph = self.analyze(tables)
        self.assertEqual(len(graph["groups"]), 1)
        self.assertEqual(len(graph["groups"][0]["members"]), size)
        self.assertTrue(graph["groups"][0]["cyclic"])

    def test_analysis_does_not_connect_or_read_files_or_modify_input(self):
        tables = [table("parent"), table("child", [column("parent_id")], [foreign_key("parent")])]
        objects = inventory(tables)
        before = copy.deepcopy((tables, objects))
        with patch("builtins.open", side_effect=AssertionError("file access")), \
                patch("sqlite3.connect", side_effect=AssertionError("database access")):
            self.assertEqual(self.analyze(tables, objects)["unresolved_count"], 0)
        self.assertEqual((tables, objects), before)


class FingerprintTests(unittest.TestCase):
    def report(self):
        tables = [table("á")]
        tables[0]["columns"][0].update(default_sha256="default-hash", default_sql="'canary'")
        objects = inventory(tables)
        objects[0].update(sql_sha256="sql-hash", sql="CREATE TABLE á(id)")
        return {"complete": True, "status": "complete", "graph": {"complete": True},
                "objects": objects, "tables": tables, "filename": "first.sqlite",
                "sqlite_version": "3.46.0", "schema": {"schema_version": 3},
                "options": {"include_sql": True}, "limits": {}, "summary": {}, "issues": []}

    def test_exact_canonical_projection_and_no_input_mutation(self):
        report = self.report()
        before = copy.deepcopy(report)
        expected = {"objects": copy.deepcopy(report["objects"]), "tables": copy.deepcopy(report["tables"])}
        del expected["objects"][0]["sql"]
        del expected["tables"][0]["columns"][0]["default_sql"]
        encoded = json.dumps(expected, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        self.assertEqual(catalog_fingerprint(report), hashlib.sha256(encoded.encode("utf-8")).hexdigest())
        self.assertEqual(report, before)

    def test_environment_presentation_and_graph_do_not_affect_hash(self):
        report = self.report()
        expected = catalog_fingerprint(report)
        report.update(filename="second.sqlite", sqlite_version="9.0.0",
                      schema={"schema_version": 200, "user_version": 123}, summary={"objects": 99},
                      options={"include_sql": False, "include_internal": True}, limits={"anything": 4},
                      issues=[{"message": "other"}], graph={"complete": True, "unresolved_count": 999})
        del report["objects"][0]["sql"]
        del report["tables"][0]["columns"][0]["default_sql"]
        self.assertEqual(catalog_fingerprint(report), expected)

    def test_only_sql_and_default_sql_keys_are_removed_recursively(self):
        report = self.report()
        report["tables"][0]["nested"] = [{"sql": "hidden", "default_sql": "hidden", "keep": "kept"}]
        expected = catalog_fingerprint(report)
        report["tables"][0]["nested"][0].update(sql="changed", default_sql="changed")
        self.assertEqual(catalog_fingerprint(report), expected)
        report["tables"][0]["nested"][0]["keep"] = "changed"
        self.assertNotEqual(catalog_fingerprint(report), expected)

    def test_schema_facts_and_preserved_hashes_affect_hash(self):
        for path in ("objects", "tables"):
            report = self.report()
            expected = catalog_fingerprint(report)
            report[path][0]["name"] = "other"
            self.assertNotEqual(catalog_fingerprint(report), expected)
        for container, key in (("objects", "sql_sha256"), ("tables", "default_sha256")):
            report = self.report()
            expected = catalog_fingerprint(report)
            item = report[container][0] if container == "objects" else report["tables"][0]["columns"][0]
            item[key] = "changed"
            self.assertNotEqual(catalog_fingerprint(report), expected)

    def test_partial_capture_or_graph_has_no_fingerprint(self):
        for field in ("capture", "graph"):
            with self.subTest(field=field):
                report = self.report()
                if field == "capture":
                    report["complete"] = False
                else:
                    report["graph"]["complete"] = False
                self.assertIsNone(catalog_fingerprint(report))


if __name__ == "__main__":
    unittest.main()
