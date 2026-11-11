"""Verify the files under MODEL_DIR against the manifest before anything is loaded."""

import hashlib
import json
from pathlib import Path

from kavach_sms_worker.manifest import FORBIDDEN_SUFFIXES, Manifest

CHUNK = 1024 * 1024


class ArtifactError(Exception):
    """The artifacts do not match the manifest. The message holds a count, never paths."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def artifact_problems(manifest: Manifest, model_dir: Path) -> list[str]:
    """Problems with the artifact directory; empty means every file verifies.

    Problems name the manifest's own file names only, never a path or file content.
    """
    directory = model_dir / manifest.artifact_dir
    if not directory.is_dir() or directory.is_symlink():
        return ["artifact directory missing"]
    problems = []
    expected = {f.name for f in manifest.files}
    for path in sorted(directory.iterdir()):
        if path.name not in expected:
            # A stray pickle, code file or extra weights beside the model could be picked up by
            # a loader, so anything unlisted blocks loading.
            forbidden = path.name.lower().endswith(FORBIDDEN_SUFFIXES)
            problems.append("forbidden file present" if forbidden else "unexpected file present")
    for spec in manifest.files:
        path = directory / spec.name
        if path.is_symlink() or not path.is_file():
            problems.append(f"{spec.name}: missing")
        elif path.stat().st_size != spec.size_bytes:
            problems.append(f"{spec.name}: size differs")
        elif file_sha256(path) != spec.sha256:
            problems.append(f"{spec.name}: sha256 differs")
    if not problems:
        problems += config_problems(manifest, directory)
    return problems


def config_problems(manifest: Manifest, directory: Path) -> list[str]:
    """`config.json` must name no custom code and carry exactly the manifest's labels."""
    try:
        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["config.json: unreadable"]
    if not isinstance(config, dict):
        return ["config.json: not an object"]
    problems = []
    if "auto_map" in config or config.get("trust_remote_code"):
        problems.append("config.json: custom code requested")
    id2label = config.get("id2label")
    if not isinstance(id2label, dict):
        return problems + ["config.json: label map missing"]
    found = tuple(id2label.get(str(i)) for i in range(len(id2label)))
    if found != manifest.labels:
        problems.append("config.json: label map differs from manifest")
    return problems


def verify_artifacts(manifest: Manifest, model_dir: Path) -> Path:
    problems = artifact_problems(manifest, model_dir)
    if problems:
        raise ArtifactError(f"{len(problems)} artifact problem(s)")
    return model_dir / manifest.artifact_dir
