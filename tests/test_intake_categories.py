"""Source labels must remain visible without turning them into diagnoses."""

from newton.intake_profile import profile_csv


def test_label_counts_include_late_labels_and_missing_values():
    rows = ["normal"] * 5 + ["frozen", "frozen", "", "unconfirmed"]
    data = ("label\n" + "\n".join('"' + value + '"' for value in rows)).encode()
    profile = profile_csv(data)
    assert profile["categorical_columns"] == [
        {
            "column": "label",
            "counts": {"normal": 5, "frozen": 2, "unconfirmed": 1},
            "unlisted_count": 0,
            "missing_count": 1,
            "semantics": "source_assertion",
        }
    ]


def test_large_category_sets_are_bounded_without_losing_denominator():
    data = ("label\n" + "\n".join(f"category-{i}" for i in range(130))).encode()
    column = profile_csv(data)["categorical_columns"][0]
    assert len(column["counts"]) == 100
    assert sum(column["counts"].values()) + column["unlisted_count"] == 130


def test_numeric_and_time_columns_are_not_misrepresented_as_categories():
    data = b"time,value,label\n2026-01-01 00:00:00,2,normal\n"
    assert [c["column"] for c in profile_csv(data)["categorical_columns"]] == ["label"]
