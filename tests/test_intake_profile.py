"""Synthetic-only coverage for bounded profiling, annotations, and repairs."""

import csv
import hashlib
import io
import json
import unittest

from newton.intake_annotations import parse_annotations
from newton.intake_profile import profile_csv
from newton.intake_transforms import prepare_csv


def _csv(rows, delimiter=","):
    """Encode synthetic cells without losing quotes, blanks, or newlines."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter)
    writer.writerows(rows)
    return stream.getvalue().encode()


def _task(results=None, source="/private/synthetic/obj007_capture.csv"):
    """Build the actual Label Studio task/annotation/result nesting."""
    if results is None:
        results = [{"type": "timeserieslabels", "value": {
            "start": 1, "end": 3, "instant": False, "timeserieslabels": ["Synthetic label"]}}]
    return {"id": 7, "data": {"csv": source}, "annotations": [{"id": 8, "result": results}]}


def _parse(tasks):
    """Encode synthetic JSON before exercising the public parser."""
    return parse_annotations(json.dumps(tasks).encode())


def _codes(result):
    """Extract finding codes for assertions independent of message wording."""
    return {finding["code"] for finding in result["findings"]}


class ProfileTests(unittest.TestCase):
    """Verify counts, temporal meaning, and CSV resource boundaries."""

    def test_delimiters_bom_and_original_samples(self):
        for delimiter in (",", ";", "\t"):
            with self.subTest(delimiter=delimiter):
                data = b"\xef\xbb\xbf" + _csv([["sensor", "value"], ["\u03b1", " 1 "]], delimiter)
                result = profile_csv(data)
                self.assertEqual(result["delimiter"], delimiter)
                self.assertEqual(result["sample_rows"], [{"sensor": "\u03b1", "value": " 1 "}])
                self.assertEqual(result["numeric_columns"][0]["mean"], 1)

    def test_numeric_missing_invalid_extreme_and_binary(self):
        result = profile_csv(b"x,binary\n1,0\n,1\nno,0\nNaN,1\nInfinity,\n201,0\n")
        numeric, binary = result["numeric_columns"]
        self.assertEqual((numeric["finite_count"], numeric["missing_count"],
                          numeric["invalid_count"]), (2, 1, 3))
        self.assertEqual((numeric["min"], numeric["max"], numeric["mean"]), (1, 201, 101))
        self.assertTrue(binary["binary"])
        self.assertFalse(numeric["binary"])
        self.assertTrue({"extreme_numeric", "invalid_numeric", "missing_values"} <= _codes(result))
        json.dumps(result, allow_nan=False)

    def test_empty_and_nonfinite_columns(self):
        result = profile_csv(b"empty,nan,text\n ,NaN,hello\n,inf,world\n")
        self.assertIn("empty_column", _codes(result))
        numeric = result["numeric_columns"][0]
        self.assertEqual(numeric["invalid_count"], 2)
        self.assertIsNone(numeric["mean"])
        self.assertEqual(profile_csv(b"a,b\n")["row_count"], 0)
        self.assertIn("empty_data", _codes(profile_csv(b"a\n")))

    def test_large_finite_mean_does_not_overflow(self):
        for cells in (["1e308", "1e308"], ["1e308", "-1e308"]):
            result = profile_csv(_csv([["n"], *[[cell] for cell in cells]]))
            json.dumps(result, allow_nan=False)
            self.assertEqual(result["numeric_columns"][0]["mean"],
                             1e308 if cells[0] == cells[1] else 0)

    def test_naive_cadence_duplicates_backward_gaps_all_rows(self):
        stamps = ["00:00", "00:01", "00:02", "00:05", "00:05", "00:04", "00:06"]
        result = profile_csv(_csv([["when"], *[["2026-01-01T" + stamp] for stamp in stamps]]))
        time = result["time_columns"][0]
        self.assertEqual(time["timezone_basis"], "naive")
        self.assertEqual((time["duplicate_count"], time["backward_count"], time["gap_count"]),
                         (1, 1, 2))
        self.assertEqual((time["expected_step_seconds"], time["missing_intervals"]), (60, 3))
        self.assertEqual(time["valid_count"], 7)
        self.assertEqual(result["duplicate_rows"], 1)
        self.assertEqual(len(result["sample_rows"]), 5)
        self.assertFalse(time["min"].endswith("+00:00"))

    def test_offsets_equivalent_instants_and_original_offset(self):
        data = b"t\n2026-01-01T01:00:00+01:00\n2026-01-01T00:00:00Z\n2026-01-01T00:01:00Z\n"
        time = profile_csv(data)["time_columns"][0]
        self.assertEqual(time["timezone_basis"], "offset")
        self.assertEqual(time["duplicate_count"], 1)
        self.assertEqual(time["expected_step_seconds"], 60)
        self.assertEqual(time["min"], "2026-01-01T01:00:00+01:00")

    def test_mixed_invalid_missing_and_date_only(self):
        result = profile_csv(b't\n2026-01-01\n2026-01-01T00:00:00Z\n""\nwrong\n2026-02-30\n')
        time = result["time_columns"][0]
        self.assertEqual(time["timezone_basis"], "mixed")
        self.assertIsNone(time["min"])
        self.assertIsNone(time["expected_step_seconds"])
        self.assertEqual(set(time["by_basis"]), {"naive", "offset"})
        self.assertEqual((time["valid_count"], time["invalid_count"], time["missing_count"]),
                         (2, 2, 1))
        self.assertTrue({"mixed_timezones", "invalid_times", "missing_values"} <= _codes(result))

    def test_cadence_tie_and_fractional_seconds(self):
        time = profile_csv(b"t\n2026-01-01T00:00:00\n2026-01-01T00:00:00.1\n"
                           b"2026-01-01T00:00:00.4\n")["time_columns"][0]
        self.assertEqual(time["expected_step_seconds"], 0.1)
        self.assertEqual(time["missing_intervals"], 2)

    def test_invalid_only_times_and_quoted_multiline_header(self):
        result = profile_csv(b"time\n2026-99-99\n2026-02-30\n")
        self.assertEqual(result["time_columns"], [])
        self.assertIn("invalid_times", _codes(result))
        data = _csv([['name,;\t"\nnext', "value"], ["a", "2"]], ";")
        self.assertEqual(profile_csv(data)["delimiter"], ";")

    def test_invalid_shapes_and_encoding(self):
        cases = [b"", b"\n", b"a,a\n1,2\n", b"a,\n1,2\n", b"a, \n1,2\n",
                 b"a,b\n1\n", b"a,b\n1,2,3\n", b"a\n\n", b"a\n\x00\n", b"a\n\xff\n",
                 b'a,b\n"unterminated,2', b'a,"unterminated\n1,2', b'a,b\n"x"bad,2\n']
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                profile_csv(data)

    def test_column_field_row_boundaries_and_full_counts(self):
        columns = [f"c{i}" for i in range(100)]
        result = profile_csv(_csv([columns, ["0"] * 100]))
        self.assertEqual(len(result["sample_rows"][0]), 20)
        self.assertEqual(len(result["numeric_columns"]), 100)
        for data in (_csv([columns + ["extra"]]), _csv([["x"], ["a" * 10001]]),
                     _csv([["a" * 10001]]), b"x\n" + b"0\n" * 200001):
            with self.assertRaises(ValueError):
                profile_csv(data)
        self.assertEqual(profile_csv(_csv([["x"], ["a" * 10000]]))["row_count"], 1)
        result = profile_csv(b"x\n" + b"0\n" * 199999 + b"bad\n")
        self.assertEqual((result["row_count"], result["duplicate_rows"]), (200000, 199998))
        self.assertEqual(result["numeric_columns"][0]["invalid_count"], 1)

    def test_bounded_findings_and_repeatability(self):
        data = _csv([[f"c{i}" for i in range(100)], ["201"] * 100, [""] * 100, ["bad"] * 100])
        result = profile_csv(data)
        self.assertEqual(result["finding_count"], 300)
        self.assertEqual(len(result["findings"]), 100)
        self.assertTrue(result["findings_truncated"])
        self.assertEqual(result, profile_csv(data))


class AnnotationTests(unittest.TestCase):
    """Verify actual source nesting, source fidelity, privacy, and strict limits."""

    def test_actual_shape_and_uri_basename(self):
        for source in ("/private/synthetic/obj007_capture.csv", "s3://bucket/obj007.csv?private=yes",
                       "https://example.invalid/obj007.csv", "C:\\private\\obj007.csv"):
            result = _parse([_task(source=source)])
            self.assertEqual(result["intervals"], [{"task_id": 7, "annotation_id": 8,
                             "object_ref": "obj007", "label": "Synthetic label",
                             "start": 1, "end": 3, "instant": False}])
            self.assertEqual(result["interval_semantics"], "source_unspecified")
            self.assertNotIn("private", json.dumps(result))

    def test_contradictions_multiple_labels_and_choices_preserved(self):
        results = [{"type": "timeserieslabels", "value": {"start": 5, "end": 2,
                    "instant": True, "timeserieslabels": ["Hot", "Cold"]}},
                   {"type": "choices", "value": {"choices": ["Needs review"]}}]
        result = _parse([_task(results)])
        self.assertEqual([item["label"] for item in result["intervals"]],
                         ["Hot", "Cold", "Needs review"])
        self.assertEqual(result["intervals"][0]["start"], 5)
        self.assertIsNone(result["intervals"][2]["start"])
        self.assertTrue({"reversed_interval", "contradictory_instant", "non_temporal_choice"}
                        <= _codes(result))

    def test_missing_data_and_unsupported_results_never_infer_normal(self):
        results = [{"type": "rectanglelabels", "value": {}}, {"type": "timeserieslabels"},
                   {"type": "timeserieslabels", "value": {"timeserieslabels": []}},
                   {"type": "timeserieslabels", "value": {"timeserieslabels": ["Source"]}}]
        result = _parse([{}, _task(results, "/obj123/no_identifier.csv")])
        self.assertEqual(len(result["intervals"]), 1)
        self.assertIsNone(result["intervals"][0]["object_ref"])
        self.assertTrue({"unmatched_id", "unmatched_object_id", "missing_annotations",
                         "unsupported_result_type", "missing_interval_bounds"} <= _codes(result))
        self.assertEqual(_parse([])["intervals"], [])

    def test_strict_json_and_limits(self):
        cases = [b"{}", b"[", b"[NaN]", b"[Infinity]", b"[1e999]", b'[{"id":1,"id":2}]',
                 br'["\ud800"]', b"[\xff]", b"[" * 40 + b"0" + b"]" * 40,
                 b" " * (8 * 1024 * 1024 + 1)]
        for data in cases:
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                parse_annotations(data)
        with self.assertRaises(ValueError):
            _parse([{}] * 10001)
        with self.assertRaises(ValueError):
            _parse([{"extra": [0] * 200000}])
        value = {"start": 0, "end": 1, "timeserieslabels": ["L"] * 100}
        result = _parse([_task([{"type": "timeserieslabels", "value": value}] * 500)])
        self.assertEqual(len(result["intervals"]), 50000)
        with self.assertRaises(ValueError):
            _parse([_task([{"type": "timeserieslabels", "value": value}] * 501)])

    def test_bounded_findings_and_duplicate_ids(self):
        result = _parse([_task()] * 101)
        self.assertEqual(len(result["intervals"]), 101)
        self.assertIn("duplicate_task_id", _codes(result))
        result = _parse([{}] * 100)
        self.assertEqual((len(result["findings"]), result["finding_count"]), (100, 300))
        self.assertTrue(result["findings_truncated"])
        self.assertEqual(result, _parse([{}] * 100))

    def test_invalid_labels_endpoints_and_instant(self):
        for update in ({"timeserieslabels": [" "]}, {"timeserieslabels": ["x" * 1001]},
                       {"start": {}}, {"start": True}, {"instant": "yes"}):
            value = {"start": 1, "end": 2, "timeserieslabels": ["A"], **update}
            with self.assertRaises(ValueError):
                _parse([_task([{"type": "timeserieslabels", "value": value}])])


class TransformTests(unittest.TestCase):
    """Verify explicit authorization, byte identity, and exact cell preservation."""

    def test_preservation_and_hashes(self):
        rows = [["old", "text", "missing"], ["001", 'quote";comma,', ""],
                ["  NaN ", "line1\r\nline2\rline3\nline4", " "], ["\u03bb", "2001-02-03", ""]]
        data = b"\xef\xbb\xbf" + _csv(rows, ";")
        operations = [{"name": "normalize_delimiter", "args": {"delimiter": ","}},
                      {"name": "rename_columns", "args": {"mapping": {"old": "new"}}}]
        output, provenance = prepare_csv(data, operations)
        actual = list(csv.reader(io.StringIO(output.decode(), newline="")))
        self.assertEqual(actual, [["new", "text", "missing"], *rows[1:]])
        self.assertEqual(provenance["input_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(provenance["output_sha256"], hashlib.sha256(output).hexdigest())
        self.assertEqual(provenance["changed_columns"], [{"old": "old", "new": "new"}])
        self.assertEqual(provenance["row_count"], 3)
        self.assertEqual((output, provenance), prepare_csv(data, operations))
        operations[1]["args"]["mapping"]["old"] = "different"
        self.assertEqual(provenance["operations"][1]["args"]["mapping"]["old"], "new")

    def test_identity_and_noop_validation(self):
        data = b'\xef\xbb\xbfa,b\n"1",\n'
        for operations in ([], [{"name": "normalize_delimiter", "args": {"delimiter": ","}}],
                           [{"name": "rename_columns", "args": {"mapping": {"a": "a"}}}]):
            self.assertIs(prepare_csv(data, operations)[0], data)
        with self.assertRaises(ValueError):
            prepare_csv(b"a,b\n1\n", [])

    def test_ordered_renames_swaps_and_special_header_cells(self):
        data = b'a;b\r\n001;""\r\n'
        swap = {"name": "rename_columns", "args": {"mapping": {"a": "b", "b": "a"}}}
        self.assertIs(prepare_csv(data, [swap, swap])[0], data)
        rename = {"name": "rename_columns", "args": {"mapping": {"b": 'multi;\n"line'}}}
        output, provenance = prepare_csv(data, [swap, rename])
        cells = list(csv.reader(io.StringIO(output.decode(), newline=""), delimiter=";"))
        self.assertEqual(cells, [['multi;\n"line', "a"], ["001", ""]])
        self.assertEqual(provenance["row_count"], 1)

    def test_transform_validates_full_rows_and_operation_bounds(self):
        for data in (b"a,b\n" + b"1,2\n" * 6 + b"wrong\n", b"x\n" + b"a" * 10001,
                     b"x\n" + b"0\n" * 200001):
            with self.assertRaises(ValueError):
                prepare_csv(data, [])
        for operations in (None, [{}] * 101, [{"name": "rename_columns", "args": {}, "extra": 1}]):
            with self.assertRaises(ValueError):
                prepare_csv(b"x\n1\n", operations)

    def test_forbidden_and_invalid_operations(self):
        operations = [{"name": name, "args": {}}
                      for name in ("drop", "interpolate", "clip", "swapdate")]
        operations.append({"name": "normalize_delimiter", "args": {"delimiter": ";"}})
        operations.extend({"name": "rename_columns", "args": {"mapping": mapping}}
                          for mapping in ({"a": "b"}, {"no": "new"}, {"a": ""}, {"a": "\x00"}))
        operations.extend([{}, {"name": "rename_columns", "args": []}])
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                prepare_csv(b"a,b\n1,2\n", [operation])


if __name__ == "__main__":
    unittest.main()
