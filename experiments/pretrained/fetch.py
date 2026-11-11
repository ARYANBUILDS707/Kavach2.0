"""Download and verify the selected candidate's files into ignored local storage.

- Only the selected candidate, only its listed files, only from its pinned revision.
- Only https on the allowed Hub hosts, redirects included. URLs are never printed or stored: a
  redirect target carries a signed token.
- Each file is streamed to a temporary name while hashing; it is kept only if size and SHA-256
  match, so a partial or substituted file is never left under the real name.
- An existing file with a different hash is never overwritten; it stops the run.
"""

import hashlib
import http.client
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from dataset_governance.fingerprints import REPO_ROOT
from pretrained.candidates import (
    ALLOWED_HOSTS,
    FORBIDDEN_SUFFIXES,
    HUB_HOST,
    REVISION,
    Candidate,
    ModelFile,
    allowed_file_name,
)
from sms_prep.acquire import AllowedHostRedirects, check_url

DEFAULT_MODEL_ROOT = REPO_ROOT / "data" / "models"
CHUNK = 1024 * 1024
USER_AGENT = "kavach-pretrained-poc/1.0 (offline research; pinned, hash-verified downloads)"

# Some networks cut long transfers; a short stream is resumed with an HTTP Range request. The
# whole file is re-hashed afterwards, so a resumed download is held to the same pinned record.
MAX_ATTEMPTS = 8

# (url, start offset) -> a response; `status` is 206 when a range request was honoured.
Opener = Callable[[str, int], BinaryIO]


class ModelFetchError(Exception):
    """The model files are not present and verified; nothing unverified was kept."""


def model_dir(candidate: Candidate, root: Path = DEFAULT_MODEL_ROOT) -> Path:
    return root / candidate.key / candidate.revision


def file_url(candidate: Candidate, name: str) -> str:
    return f"https://{HUB_HOST}/{candidate.repo}/resolve/{candidate.revision}/{name}"


def default_opener(url: str, start: int = 0) -> BinaryIO:
    check_url(url, ALLOWED_HOSTS)
    opener = urllib.request.build_opener(AllowedHostRedirects(ALLOWED_HOSTS))
    headers = {"User-Agent": USER_AGENT}
    if start:
        headers["Range"] = f"bytes={start}-"
    request = urllib.request.Request(url, headers=headers)
    return opener.open(request, timeout=60)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def check_candidate(candidate: Candidate) -> None:
    if not candidate.selected:
        raise ModelFetchError(f"{candidate.key} is not the selected candidate; it is not fetched")
    if not REVISION.match(candidate.revision):
        raise ModelFetchError("The revision must be a full 40-character commit hash")
    for spec in candidate.files:
        if not allowed_file_name(spec.name):
            raise ModelFetchError(f"{spec.name}: file type not allowed")


def stream_once(spec: ModelFile, url: str, partial: Path, opener: Opener) -> None:
    """Append to `partial` from its current size; restart from zero if the range is ignored."""
    start = partial.stat().st_size if partial.exists() else 0
    with opener(url, start) as response:
        if start and getattr(response, "status", 200) != 206:
            start = 0  # the server sent the whole file: start over
        size = start
        with partial.open("r+b" if start else "wb") as out:
            out.seek(start)
            out.truncate()
            while block := response.read(CHUNK):
                size += len(block)
                if size > spec.size_bytes:
                    raise ModelFetchError(f"{spec.name}: larger than recorded")
                out.write(block)


def download(spec: ModelFile, url: str, target: Path, opener: Opener) -> None:
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)  # never resume from a file of unknown origin
    try:
        for _ in range(MAX_ATTEMPTS):
            try:
                stream_once(spec, url, partial, opener)
            except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError):
                pass  # a dropped connection: resume from what was written
            if partial.exists() and partial.stat().st_size == spec.size_bytes:
                break
        else:
            # Never include exception text: it can repeat a signed redirect URL.
            raise ModelFetchError(f"{spec.name}: download incomplete after {MAX_ATTEMPTS} tries")
        if file_sha256(partial) != spec.sha256:
            raise ModelFetchError(f"{spec.name}: size or SHA-256 differs from the pinned record")
    except ModelFetchError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)


def fetch(
    candidate: Candidate, root: Path = DEFAULT_MODEL_ROOT, opener: Opener = default_opener
) -> list[str]:
    """Fetch missing files; returns the names downloaded (empty if all were already verified)."""
    check_candidate(candidate)
    directory = model_dir(candidate, root)
    directory.mkdir(parents=True, exist_ok=True)
    fetched = []
    for spec in candidate.files:
        target = directory / spec.name
        if target.exists():
            if file_sha256(target) != spec.sha256:
                raise ModelFetchError(f"{spec.name}: existing file differs; not overwritten")
            continue
        download(spec, file_url(candidate, spec.name), target, opener)
        fetched.append(spec.name)
    return fetched


def verify(candidate: Candidate, root: Path = DEFAULT_MODEL_ROOT) -> list[str]:
    """Problems that make the local copy unusable; empty means every file verifies."""
    directory = model_dir(candidate, root)
    if not directory.is_dir():
        return ["model directory missing"]
    problems = []
    expected = {f.name for f in candidate.files}
    for path in sorted(directory.iterdir()):
        if path.name not in expected:
            # A stray pickle or code file next to the weights could be picked up by a loader.
            kind = "forbidden" if path.name.lower().endswith(FORBIDDEN_SUFFIXES) else "unexpected"
            problems.append(f"{path.name}: {kind} file in the model directory")
    for spec in candidate.files:
        path = directory / spec.name
        if not path.is_file():
            problems.append(f"{spec.name}: missing")
        elif path.stat().st_size != spec.size_bytes or file_sha256(path) != spec.sha256:
            problems.append(f"{spec.name}: size or SHA-256 differs from the pinned record")
    return problems
