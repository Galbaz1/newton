"""Bounded CSV mappings with explicit units, timestamps and all-row validation."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def upload_csv(client, owner):
    """Upload explicitly synthetic CSV content through the multipart route."""

    def upload(content):
        response = client.post(
            f"/api/machines/{owner['machine']['id']}/sources",
            files={
                "file": ("synthetic.csv", content, "text/csv"),
            },
        )
        assert response.status_code == 200
        return response.json()

    return upload


def _mapping(**updates):
    return {"time_column": "time", "value_column": "reading", "unit": "degC", **updates}


def test_explicit_mapping_preserves_values_offsets_and_originals(client, owner, upload_csv):
    """Mapping never guesses units or converts the original measured values."""
    data = (
        b"time,reading,corrected\n2026-01-01T02:00:00+02:00,001.50,10\n"
        b"2026-01-01T00:01:00Z,-2.75,20\n"
    )
    source = upload_csv(data)
    assert source["status"] == "needs_mapping" and source["mapping"] is None
    assert source["metadata"]["columns"] == ["time", "reading", "corrected"]
    assert source["metadata"]["sample_rows"][0]["reading"] == "001.50"
    path = f"/api/sources/{source['id']}"
    assert client.get(path + "/series").status_code == 409
    mapped = client.patch(path, json={"mapping": _mapping()}).json()
    assert mapped["status"] == "ready" and mapped["version"] == 2
    result = client.get(path + "/series").json()
    assert set(result) == {
        "source_id",
        "time_basis",
        "selected_period",
        "unit",
        "time_column",
        "value_column",
        "points",
        "summary",
        "truncated",
    }
    assert result["unit"] == "degC" and result["truncated"] is False
    assert result["points"] == [
        {"time": "2026-01-01T02:00:00+02:00", "value": 1.5},
        {"time": "2026-01-01T00:01:00+00:00", "value": -2.75},
    ]
    assert result["summary"] == {
        "count": 2,
        "min": -2.75,
        "max": 1.5,
        "mean": -0.625,
        "start": "2026-01-01T02:00:00+02:00",
        "end": "2026-01-01T00:01:00+00:00",
    }
    corrected = client.patch(
        path, json={"revision": "Sensor correction", "mapping": _mapping(value_column="corrected")}
    ).json()
    assert corrected["version"] == 3 and corrected["revision"] == "Sensor correction"
    assert corrected["sha256"] == hashlib.sha256(data).hexdigest()
    assert client.get(path + "/original").content == data
    assert client.get(path + "/series").json()["summary"]["mean"] == 15
    readiness = client.get(f"/api/machines/{owner['machine']['id']}/readiness").json()
    assert readiness["context_version"] == 4
    assert (
        next(row for row in readiness["capabilities"] if row["id"] == "timeseries")["state"]
        == "ready"
    )


def test_naive_timestamp_error_can_be_corrected_with_timezone(client, upload_csv):
    """A missing timezone is stored as an error and a correction restores readiness."""
    source = upload_csv(b"time,reading\n2026-01-01T12:00:00,4.25\n")
    path = f"/api/sources/{source['id']}"
    invalid = client.patch(path, json={"mapping": _mapping()}).json()
    assert invalid["status"] == "error" and "timezone" in invalid["metadata"]["error"]
    assert client.get(path + "/series").status_code == 409
    valid = client.patch(path, json={"mapping": _mapping(timezone="Europe/Amsterdam")}).json()
    assert valid["status"] == "ready" and "error" not in valid["metadata"]
    assert client.get(path + "/series").json()["points"] == [
        {"time": "2026-01-01T12:00:00+01:00", "value": 4.25},
    ]


@pytest.mark.parametrize(
    "time,value,fragment",
    [
        ("2026-01-01T00:00:00Z", "NaN", "finite"),
        ("2026-01-01T00:00:00Z", "inf", "finite"),
        ("2026-01-01T00:00:00Z", "1e999", "finite"),
        ("2026-01-01T00:00:00Z", "", "finite"),
        ("2026-01-01T00:00:00Z", "broken", "finite"),
        ("2026-99-01T00:00:00Z", "2", "ISO"),
        ("", "2", "ISO"),
        ("2026-10-25T02:30:00", "2", "ambiguous"),
        ("2026-03-29T02:30:00", "2", "nonexistent"),
    ],
)
def test_bad_observation_is_visible_and_never_silently_dropped(
    client,
    upload_csv,
    time,
    value,
    fragment,
):
    """One invalid observation blocks a whole mapped series, including otherwise good rows."""
    source = upload_csv(f"time,reading\n2026-01-01T00:00:00Z,1\n{time},{value}\n".encode())
    path = f"/api/sources/{source['id']}"
    result = client.patch(path, json={"mapping": _mapping(timezone="Europe/Amsterdam")}).json()
    assert result["status"] == "error"
    assert "row 3" in result["metadata"]["error"] and fragment in result["metadata"]["error"]
    assert client.get(path + "/series").status_code == 409


@pytest.mark.parametrize(
    "data",
    [
        b"time,reading\n2026-01-01T00:00Z\n",
        b"time,reading\n2026-01-01T00:00Z,1,extra\n",
        b"time,time\n2026-01-01T00:00Z,1\n",
        b"time,reading\n",
        b'time,reading\n"unclosed,1\n',
        b"time,reading\n\xff,1\n",
        b"time,reading\n\n",
    ],
)
def test_invalid_csv_shape_stores_original_error(client, upload_csv, data):
    """Malformed CSV files retain their hash and a public processing error."""
    source = upload_csv(data)
    assert source["status"] == "error" and source["metadata"]["error"]
    assert source["sha256"] == hashlib.sha256(data).hexdigest()
    assert client.get(f"/api/sources/{source['id']}/original").content == data


@pytest.mark.parametrize(
    "mapping",
    [
        _mapping(time_column="missing"),
        _mapping(value_column="time"),
        _mapping(timezone="Not/AZone"),
        _mapping(timezone="/etc/passwd"),
        _mapping(unit=""),
        {"time_column": "time", "value_column": "reading"},
    ],
)
def test_invalid_mapping_fields_return_422_without_version_change(
    client, owner, upload_csv, mapping
):
    """Invalid mapping structure is rejected atomically, before updating the source."""
    source = upload_csv(b"time,reading\n2026-01-01T00:00Z,1\n")
    response = client.patch(f"/api/sources/{source['id']}", json={"mapping": mapping})
    assert response.status_code == 422
    assert "/etc/passwd" not in str(response.json().get("detail", ""))
    sources = client.get(f"/api/machines/{owner['machine']['id']}/sources").json()
    assert sources[0]["version"] == 1
    assert client.get(f"/api/machines/{owner['machine']['id']}").json()["context_version"] == 2


def test_truncation_still_summarizes_and_validates_all_rows(client, upload_csv):
    """The first 5000 points are original rows; summary and validation cover all rows."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    lines = [f"{(start + timedelta(seconds=n)).isoformat()},{n}" for n in range(5002)]
    source = upload_csv(("time,reading\n" + "\n".join(lines)).encode())
    path = f"/api/sources/{source['id']}"
    assert client.patch(path, json={"mapping": _mapping()}).json()["status"] == "ready"
    result = client.get(path + "/series").json()
    assert len(result["points"]) == 5000 and result["truncated"] is True
    assert result["points"][-1]["value"] == 4999
    assert result["summary"]["count"] == 5002 and result["summary"]["max"] == 5001
    assert result["summary"]["mean"] == 2500.5
    bad = upload_csv(("time,reading\n" + "\n".join(lines) + "\n2026-01-02T00:00Z,NaN").encode())
    mapped = client.patch(f"/api/sources/{bad['id']}", json={"mapping": _mapping()}).json()
    assert mapped["status"] == "error" and "row 5004" in mapped["metadata"]["error"]


def test_preview_is_bounded_and_source_row_limit_is_explicit(client, upload_csv):
    """CSV previews cap rows/columns while excessive data causes a visible error."""
    header = ",".join(f"column{n}" for n in range(25))
    line = ",".join(str(n) for n in range(25))
    source = upload_csv((header + "\n" + (line + "\n") * 6).encode())
    assert len(source["metadata"]["columns"]) == 25
    assert len(source["metadata"]["sample_rows"]) == 5
    assert len(source["metadata"]["sample_rows"][0]) == 20
    assert source["metadata"]["row_count"] == 6 and source["metadata"]["warnings"]
    oversized = upload_csv(b"time,reading\n" + b"2026-01-01T00:00Z,1\n" * 200001)
    assert oversized["status"] == "error" and "200000" in oversized["metadata"]["error"]


@pytest.mark.parametrize("column_count", [21, 100])
def test_late_columns_are_available_for_mapping(client, upload_csv, column_count):
    """Expose late timestamp/value headers while keeping sampled cells bounded."""
    columns = [f"unused{n}" for n in range(column_count - 2)] + ["time", "reading"]
    rows = [["0"] * (column_count - 2) + ["2026-09-21T09:00:00", "7"]]
    data = (",".join(columns) + "\n" + "\n".join(",".join(row) for row in rows)).encode()
    source = upload_csv(data)
    assert source["metadata"]["columns"] == columns
    assert list(source["metadata"]["sample_rows"][0]) == columns[:20]
    path = f"/api/sources/{source['id']}"
    failed = client.patch(path, json={"mapping": _mapping()}).json()
    assert failed["status"] == "error" and "timezone" in failed["metadata"]["error"]
    corrected = client.patch(path, json={"mapping": _mapping(timezone="UTC")}).json()
    assert corrected["status"] == "ready"
    assert corrected["metadata"]["columns"] == columns
    assert client.get(path + "/series").json()["summary"]["mean"] == 7
    assert client.get(path + "/original").content == data
