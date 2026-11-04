"""Acquisition: verified, allow-listed, bounded, and refusing anything the manifest does not
describe. All archives are built in memory; no network is used."""

import hashlib
import io
import json
import urllib.error
import zipfile
from datetime import UTC, datetime

import pytest

from dataset_governance.manifest import load_manifest
from sms_prep import acquire as acq
from sms_prep.acquire import AcquisitionError, DatasetSpec, FileSpec

HOSTS = ("data.example.test",)
URL = "https://data.example.test/file.zip?token=SECRET-SIGNED-TOKEN"
CSV = b"a,b\n1,2\n"
README = b"readme text"
SCRIPT = b"print('never run')"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def file_spec(name: str, data: bytes, path: str | None = None, extract: bool = True) -> FileSpec:
    return FileSpec(name, path or name, sha(data), len(data), extract)


def flat_spec() -> tuple[DatasetSpec, bytes]:
    archive = make_zip({"data.csv": CSV, "readme": README})
    files = (file_spec("data.csv", CSV), file_spec("readme", README))
    return DatasetSpec("flat", URL, HOSTS, files), archive


def nested_spec() -> tuple[DatasetSpec, bytes]:
    inner = make_zip({"inner.csv": CSV})
    outer = make_zip({"folder with space/inner.zip": inner, "folder with space/tool.py": SCRIPT})
    files = (
        file_spec("inner.csv", CSV, "folder with space/inner.zip!inner.csv"),
        file_spec("inner.zip", inner, "folder with space/inner.zip", extract=False),
        file_spec("tool.py", SCRIPT, "folder with space/tool.py", extract=False),
    )
    return DatasetSpec("nested", URL, HOSTS, files), outer


class Fetch:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls = 0

    def __call__(self, url: str, allowed_hosts: tuple[str, ...], max_bytes: int) -> bytes:
        self.calls += 1
        return self.data


def run(spec: DatasetSpec, data: bytes, tmp_path):
    fetch = Fetch(data)
    stored = acq.acquire(spec, tmp_path, 2, fetch, lambda: datetime(2026, 11, 5, tzinfo=UTC))
    return stored, fetch


def test_a_verified_archive_is_stored_with_a_receipt(tmp_path) -> None:
    spec, archive = flat_spec()
    stored, _ = run(spec, archive, tmp_path)
    assert sorted(stored) == ["data.csv", "readme"]
    assert (tmp_path / "flat" / "data.csv").read_bytes() == CSV
    receipt = json.loads((tmp_path / "flat" / "RECEIPT.json").read_text())
    assert receipt["manifest_version"] == 2 and receipt["files"]["data.csv"]["sha256"] == sha(CSV)
    assert "SECRET" not in json.dumps(receipt) and "http" not in json.dumps(receipt)


def test_a_direct_download_is_verified(tmp_path) -> None:
    spec = DatasetSpec("direct", URL, HOSTS, (file_spec("only.csv", CSV),))
    stored, _ = run(spec, CSV, tmp_path)
    assert stored == ["only.csv"] and (tmp_path / "direct" / "only.csv").read_bytes() == CSV


def test_nested_archives_are_resolved_and_unused_members_are_not_written(tmp_path) -> None:
    spec, archive = nested_spec()
    stored, _ = run(spec, archive, tmp_path)
    assert stored == ["inner.csv"]
    assert sorted(p.name for p in (tmp_path / "nested").iterdir()) == ["RECEIPT.json", "inner.csv"]


@pytest.mark.parametrize("field", ["sha256", "size_bytes"])
def test_a_changed_file_is_refused(tmp_path, field: str) -> None:
    spec, archive = flat_spec()
    good = spec.files[0]
    changed = FileSpec(
        "data.csv",
        "data.csv",
        "0" * 64 if field == "sha256" else good.sha256,
        good.size_bytes + (1 if field == "size_bytes" else 0),
    )
    bad = DatasetSpec(spec.id, spec.url, spec.allowed_hosts, (changed, spec.files[1]))
    with pytest.raises(AcquisitionError, match="differs from the manifest"):
        run(bad, archive, tmp_path)
    assert not (tmp_path / "flat").exists()


def test_an_unknown_archive_member_is_refused(tmp_path) -> None:
    spec, _ = flat_spec()
    archive = make_zip({"data.csv": CSV, "readme": README, "extra.bin": b"surprise"})
    with pytest.raises(AcquisitionError, match="unknown: 1"):
        run(spec, archive, tmp_path)
    assert not (tmp_path / "flat").exists()


def test_a_missing_archive_member_is_refused(tmp_path) -> None:
    spec, _ = flat_spec()
    with pytest.raises(AcquisitionError, match="missing: 1"):
        run(spec, make_zip({"data.csv": CSV}), tmp_path)


@pytest.mark.parametrize("name", ["../evil.csv", "/abs/evil.csv", "a\\b.csv", "dir/../../x"])
def test_path_traversal_in_an_archive_is_refused(tmp_path, name: str) -> None:
    spec = DatasetSpec("zipslip", URL, HOSTS, (file_spec("data.csv", CSV, name),))
    with pytest.raises(AcquisitionError, match="unsafe path"):
        run(spec, make_zip({name: CSV}), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_unsafe_manifest_file_names_are_refused(tmp_path) -> None:
    spec = DatasetSpec("odd", URL, HOSTS, (file_spec("../x.csv", CSV, "x.csv"),))
    with pytest.raises(AcquisitionError, match="plain file name"):
        run(spec, make_zip({"x.csv": CSV}), tmp_path)


def test_archive_limits(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec, archive = flat_spec()
    monkeypatch.setattr(acq, "MAX_MEMBERS", 1)
    with pytest.raises(AcquisitionError, match="too many members"):
        run(spec, archive, tmp_path)
    monkeypatch.setattr(acq, "MAX_MEMBERS", 50)
    monkeypatch.setattr(acq, "MAX_MEMBER_BYTES", 3)
    with pytest.raises(AcquisitionError, match="exceeds the size limit"):
        run(spec, archive, tmp_path)
    monkeypatch.setattr(acq, "MAX_MEMBER_BYTES", 10**6)
    monkeypatch.setattr(acq, "MAX_DOWNLOAD_BYTES", 5)
    with pytest.raises(AcquisitionError, match="expands beyond"):
        run(spec, archive, tmp_path)


def test_garbage_is_not_an_archive(tmp_path) -> None:
    spec, _ = flat_spec()
    with pytest.raises(AcquisitionError):
        run(spec, b"not a zip", tmp_path)


def test_an_existing_different_local_file_is_never_overwritten(tmp_path) -> None:
    spec, archive = flat_spec()
    directory = tmp_path / "flat"
    directory.mkdir()
    (directory / "data.csv").write_bytes(b"tampered")
    (directory / "readme").write_bytes(README)
    with pytest.raises(AcquisitionError, match="differs from the manifest"):
        run(spec, archive, tmp_path)
    assert (directory / "data.csv").read_bytes() == b"tampered"


def test_stored_files_are_verified_offline_and_not_downloaded_again(tmp_path) -> None:
    spec, archive = flat_spec()
    run(spec, archive, tmp_path)
    stored, fetch = run(spec, archive, tmp_path)
    assert sorted(stored) == ["data.csv", "readme"] and fetch.calls == 0


def test_offline_verification_detects_tampering_and_unknown_files(tmp_path) -> None:
    spec, archive = flat_spec()
    run(spec, archive, tmp_path)
    directory = tmp_path / "flat"
    acq.verify_local(spec, directory)
    (directory / "stray.txt").write_text("x")
    with pytest.raises(AcquisitionError, match="unknown local file"):
        acq.verify_local(spec, directory)
    (directory / "stray.txt").unlink()
    (directory / "data.csv").write_bytes(b"changed")
    with pytest.raises(AcquisitionError, match="differs from the manifest"):
        acq.verify_local(spec, directory)


@pytest.mark.parametrize(
    "url",
    [
        "http://data.example.test/f.zip",
        "https://evil.example.test/f.zip",
        "https://user:pw@data.example.test/f.zip",
        "ftp://data.example.test/f.zip",
        "https://data.example.test.evil.test/f.zip",
    ],
)
def test_only_allowed_https_hosts_may_be_fetched(url: str) -> None:
    with pytest.raises(AcquisitionError, match="allowed https host"):
        acq.default_fetcher(url, HOSTS, 10)


def test_a_redirect_to_another_host_is_refused() -> None:
    handler = acq.AllowedHostRedirects(HOSTS)
    with pytest.raises(AcquisitionError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://other.example.test/x")
    with pytest.raises(AcquisitionError):
        handler.redirect_request(None, None, 302, "Found", {}, "http://data.example.test/x")


def test_network_errors_never_repeat_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class Opener:
        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            raise urllib.error.URLError(
                "failed: https://s3.example.test/x?X-Amz-Security-Token=SECRET"
            )

    monkeypatch.setattr(acq.urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(AcquisitionError) as error:
        acq.default_fetcher(URL, HOSTS, 10)
    assert "SECRET" not in str(error.value) and "http" not in str(error.value)


def test_manifest_specs_cover_every_approved_dataset_and_never_munoz() -> None:
    specs = {s.id: s for s in acq.specs_from_manifest(load_manifest())}
    assert set(specs) == {"imc25_smishing_reports", "uci_sms_spam_collection", "mishra_soni_2022"}
    assert all(s.allowed_hosts and s.url.startswith("https://") for s in specs.values())
    mishra = specs["mishra_soni_2022"]
    assert [f.name for f in mishra.files if f.extract] == ["Dataset_5971.csv"]
    assert len(mishra.files) == 8
