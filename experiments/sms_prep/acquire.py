"""Reproducible, verified acquisition of the approved datasets into ignored local storage.

Rules (docs/DATASET_GOVERNANCE.md):
- Only datasets and files named in the manifest are fetched; every file must match its recorded
  SHA-256 and size. A changed, missing or unknown file stops the run: the publisher may have
  changed the data, and that needs a new approved manifest version.
- Downloads and redirects may only use the hosts the manifest allows, over https. URLs are never
  printed or stored: a redirect target can carry a signed token.
- Archives are read in memory with member-count and size limits, and only listed members are
  written, under validated plain file names (no path traversal).
- An existing local file with a different hash is never overwritten.
"""

import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from dataset_governance.manifest import Manifest

MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 50
MAX_NESTING = 2
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
RECEIPT_NAME = "RECEIPT.json"
# Some hosts reject the default Python agent; identify the tool honestly instead.
USER_AGENT = "kavach-dataset-acquisition/1.0 (offline research; manifest-verified downloads)"


class AcquisitionError(Exception):
    """Acquisition stopped; nothing unverified was kept as an approved file."""


@dataclass(frozen=True)
class FileSpec:
    name: str
    path_in_download: str
    sha256: str
    size_bytes: int
    extract: bool = True


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    url: str
    allowed_hosts: tuple[str, ...]
    files: tuple[FileSpec, ...]


class Fetcher(Protocol):
    def __call__(self, url: str, allowed_hosts: tuple[str, ...], max_bytes: int) -> bytes: ...


def specs_from_manifest(manifest: Manifest) -> list[DatasetSpec]:
    """The datasets to acquire: everything not excluded."""
    return [
        DatasetSpec(
            id=d.id,
            url=d.download_url,
            allowed_hosts=tuple(d.allowed_download_hosts),
            files=tuple(
                FileSpec(f.name, f.path_in_download or f.name, f.sha256, f.size_bytes, f.extract)
                for f in d.files
            ),
        )
        for d in manifest.datasets
        if d.status != "excluded"
    ]


# --- network -------------------------------------------------------------------------------


class AllowedHostRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed: tuple[str, ...]) -> None:
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        check_url(newurl, self.allowed)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url: str, allowed: tuple[str, ...]) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") not in allowed or parts.username:
        raise AcquisitionError("The download is not on an allowed https host")


def default_fetcher(url: str, allowed_hosts: tuple[str, ...], max_bytes: int) -> bytes:
    check_url(url, allowed_hosts)
    opener = urllib.request.build_opener(AllowedHostRedirects(allowed_hosts))
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener.open(request, timeout=60) as response:
            data = response.read(max_bytes + 1)
    except (urllib.error.URLError, OSError, TimeoutError):
        # Never include the exception text: it can repeat a signed redirect URL.
        raise AcquisitionError("The download failed") from None
    if len(data) > max_bytes:
        raise AcquisitionError("The download exceeds the size limit")
    return data


# --- verification --------------------------------------------------------------------------


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_file(spec: FileSpec, data: bytes) -> None:
    if len(data) != spec.size_bytes or sha256(data) != spec.sha256:
        raise AcquisitionError(f"{spec.name}: size or SHA-256 differs from the manifest")


def safe_member_name(name: str) -> str:
    if name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/"):
        raise AcquisitionError("An archive member has an unsafe path")
    return name


def read_archive(data: bytes, depth: int) -> dict[str, bytes]:
    """All file members of a zip, size-limited; names validated."""
    if depth > MAX_NESTING:
        raise AcquisitionError("Archives are nested too deeply")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise AcquisitionError("The download is not a valid archive") from None
    members = {}
    infos = [i for i in archive.infolist() if not i.is_dir()]
    if len(infos) > MAX_MEMBERS:
        raise AcquisitionError("The archive has too many members")
    if sum(i.file_size for i in infos) > MAX_DOWNLOAD_BYTES:
        raise AcquisitionError("The archive expands beyond the size limit")
    for info in infos:
        if info.file_size > MAX_MEMBER_BYTES:
            raise AcquisitionError("An archive member exceeds the size limit")
        members[safe_member_name(info.filename)] = archive.read(info)
    return members


def resolve(files: tuple[FileSpec, ...], data: bytes, depth: int = 0) -> dict[str, bytes]:
    """Map each spec's path_in_download to its bytes, refusing unknown or missing members.

    A path like "a/b.zip!c.csv" names c.csv inside the nested archive a/b.zip.
    """
    top = {f.path_in_download.split("!", 1)[0] for f in files}
    members = read_archive(data, depth)
    unknown = sorted(set(members) - top)
    missing = sorted(top - set(members))
    if unknown or missing:
        raise AcquisitionError(
            f"Archive contents differ from the manifest (unknown: {len(unknown)}, "
            f"missing: {len(missing)})"
        )
    found: dict[str, bytes] = {}
    for member in sorted(top):
        nested = tuple(
            FileSpec(f.name, f.path_in_download.split("!", 1)[1], f.sha256, f.size_bytes, f.extract)
            for f in files
            if f.path_in_download.startswith(member + "!")
        )
        if nested:
            for path, blob in resolve(nested, members[member], depth + 1).items():
                found[f"{member}!{path}"] = blob
        if any(f.path_in_download == member for f in files):
            found[member] = members[member]
    return found


def verify_download(spec: DatasetSpec, data: bytes) -> dict[str, bytes]:
    """Every listed file's bytes, verified; keyed by file name."""
    by_path = {f.path_in_download: f for f in spec.files}
    direct = len(spec.files) == 1 and spec.files[0].path_in_download == spec.files[0].name
    if direct and not zipfile.is_zipfile(io.BytesIO(data)):
        check_file(spec.files[0], data)
        return {spec.files[0].name: data}
    resolved = resolve(spec.files, data)
    verified = {}
    for path, blob in resolved.items():
        file_spec = by_path.get(path)
        if file_spec is None:
            continue  # an intermediate archive that is itself not listed
        check_file(file_spec, blob)
        verified[file_spec.name] = blob
    if set(verified) != {f.name for f in spec.files}:
        raise AcquisitionError("Not every manifest file was found")
    return verified


# --- storage -------------------------------------------------------------------------------


def write_verified(directory: Path, spec: DatasetSpec, files: dict[str, bytes]) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for file_spec in spec.files:
        if not file_spec.extract:
            continue
        if not SAFE_NAME.fullmatch(file_spec.name):
            raise AcquisitionError("A manifest file name is not a plain file name")
        target = directory / file_spec.name
        if target.exists() and sha256(target.read_bytes()) != file_spec.sha256:
            raise AcquisitionError(f"{file_spec.name}: a different local file already exists")
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(files[file_spec.name])
        temporary.replace(target)
        written.append(file_spec.name)
    return written


def acquire(
    spec: DatasetSpec,
    raw_dir: Path,
    manifest_version: int,
    fetch: Fetcher = default_fetcher,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[str]:
    directory = raw_dir / spec.id
    local = locally_verified(spec, directory)
    if local is not None:
        return local
    verified = verify_download(spec, fetch(spec.url, spec.allowed_hosts, MAX_DOWNLOAD_BYTES))
    written = write_verified(directory, spec, verified)
    receipt = {
        "dataset": spec.id,
        "manifest_version": manifest_version,
        "acquired_at": clock().isoformat(),
        "files": {f.name: {"sha256": f.sha256, "size_bytes": f.size_bytes} for f in spec.files},
        "stored": written,
    }
    (directory / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return written


def locally_verified(spec: DatasetSpec, directory: Path) -> list[str] | None:
    """The stored file names if every extracted file is present and verified; None if absent."""
    stored = [f for f in spec.files if f.extract]
    if not all((directory / f.name).exists() for f in stored):
        return None
    verify_local(spec, directory)
    return [f.name for f in stored]


def verify_local(spec: DatasetSpec, directory: Path) -> None:
    """Offline check of the stored files against the manifest; also refuses unexpected files."""
    expected = {f.name for f in spec.files if f.extract} | {RECEIPT_NAME}
    present = {p.name for p in directory.iterdir() if not p.name.endswith(".part")}
    if present - expected:
        raise AcquisitionError(f"{spec.id}: {len(present - expected)} unknown local file(s)")
    for file_spec in spec.files:
        if file_spec.extract:
            path = directory / file_spec.name
            if not path.exists():
                raise AcquisitionError(f"{file_spec.name}: missing")
            check_file(file_spec, path.read_bytes())
