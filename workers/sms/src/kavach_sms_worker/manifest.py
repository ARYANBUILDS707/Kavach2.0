"""The versioned model manifest: the single trust root for what the worker may load.

Parsed with the standard library only (the worker environment has no pydantic). Any field that is
missing, mistyped or outside the allowed values makes the manifest invalid; the worker then
reports `model_unverified` and never imports torch.
"""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

MANIFEST_VERSION = 1
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
LABEL = re.compile(r"^[a-z][a-z_]{0,31}$")
# Data formats only. Pickle-based weights (.bin, .pt, .pth, .pkl, .ckpt) and code are never
# loaded, so they cannot appear in a manifest.
ALLOWED_SUFFIXES = (".json", ".safetensors")
ALLOWED_PLAIN_NAMES = ("LICENSE", "NOTICE")
FORBIDDEN_SUFFIXES = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".joblib", ".h5", ".py")
REQUIRED_FILES = ("config.json", "tokenizer.json", "model.safetensors")
RUNTIME_PACKAGES = (
    "huggingface-hub",
    "numpy",
    "safetensors",
    "tokenizers",
    "torch",
    "transformers",
)


class ManifestError(Exception):
    """The manifest is invalid; the message names the field, never file content."""


@dataclass(frozen=True)
class ModelFile:
    name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class Manifest:
    manifest_version: int
    model_key: str
    repo: str
    revision: str
    artifact_dir: str
    files: tuple[ModelFile, ...]
    labels: tuple[str, ...]
    max_input_chars: int
    max_tokens: int
    packages: dict[str, str]
    canary_sha256: str
    expected_top_label: str
    expected_probabilities: tuple[float, ...]
    tolerance: float
    sha256: str  # of the manifest file bytes

    @property
    def model_version(self) -> str:
        return f"{self.model_key}@{self.revision[:12]}+m{self.manifest_version}:{self.sha256[:12]}"


def allowed_file_name(name: str) -> bool:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return False
    if name.lower().endswith(FORBIDDEN_SUFFIXES):
        return False
    return name.endswith(ALLOWED_SUFFIXES) or name in ALLOWED_PLAIN_NAMES


def require(condition: bool, field: str) -> None:
    if not condition:
        raise ManifestError(f"manifest field invalid: {field}")


def safe_relative_dir(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        return False
    return all(
        part and part not in (".", "..") and not part.startswith(".") for part in value.split("/")
    )


def parse_manifest(data: bytes) -> Manifest:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ManifestError("manifest is not JSON") from None
    require(isinstance(raw, dict), "root")
    require(raw.get("manifest_version") == MANIFEST_VERSION, "manifest_version")
    require(raw.get("stage") == "sms_classifier", "stage")
    require(
        isinstance(raw.get("model_key"), str) and bool(KEY.match(raw["model_key"])), "model_key"
    )
    require(isinstance(raw.get("repo"), str) and raw["repo"].count("/") == 1, "repo")
    require(
        isinstance(raw.get("revision"), str) and bool(REVISION.match(raw["revision"])), "revision"
    )
    require(safe_relative_dir(raw.get("artifact_dir")), "artifact_dir")
    require(raw.get("score_semantics") == "uncalibrated_softmax", "score_semantics")
    require(raw.get("calibration") is None, "calibration")

    files_raw = raw.get("files")
    require(isinstance(files_raw, list) and files_raw, "files")
    files = []
    for item in files_raw:
        require(isinstance(item, dict), "files[]")
        name, digest, size = item.get("name"), item.get("sha256"), item.get("size_bytes")
        require(isinstance(name, str) and allowed_file_name(name), "files[].name")
        require(isinstance(digest, str) and bool(SHA256.match(digest)), "files[].sha256")
        require(
            isinstance(size, int) and not isinstance(size, bool) and size > 0, "files[].size_bytes"
        )
        files.append(ModelFile(name, digest, size))
    names = [f.name for f in files]
    require(len(set(names)) == len(names), "files (duplicate name)")
    require(all(r in names for r in REQUIRED_FILES), "files (required file missing)")

    labels = raw.get("labels")
    require(isinstance(labels, list) and len(labels) >= 2, "labels")
    require(all(isinstance(x, str) and LABEL.match(x) for x in labels), "labels[]")
    require(len(set(labels)) == len(labels), "labels (duplicate)")

    pre = raw.get("preprocessing")
    require(isinstance(pre, dict), "preprocessing")
    max_chars, max_tokens = pre.get("max_input_chars"), pre.get("max_tokens")
    require(isinstance(max_chars, int) and 1 <= max_chars <= 4096, "preprocessing.max_input_chars")
    require(isinstance(max_tokens, int) and 8 <= max_tokens <= 512, "preprocessing.max_tokens")
    require(
        pre.get("truncation") == "tokenizer" and pre.get("normalization") == "none", "preprocessing"
    )

    runtime = raw.get("runtime")
    require(isinstance(runtime, dict) and runtime.get("device") == "cpu", "runtime.device")
    packages = runtime.get("packages")
    require(
        isinstance(packages, dict) and sorted(packages) == sorted(RUNTIME_PACKAGES),
        "runtime.packages",
    )
    require(all(isinstance(v, str) and v for v in packages.values()), "runtime.packages[]")

    test = raw.get("self_test")
    require(isinstance(test, dict), "self_test")
    require(
        isinstance(test.get("canary_sha256"), str) and bool(SHA256.match(test["canary_sha256"])),
        "self_test.canary_sha256",
    )
    require(test.get("expected_top_label") in labels, "self_test.expected_top_label")
    probs = test.get("expected_probabilities")
    require(
        isinstance(probs, list) and len(probs) == len(labels), "self_test.expected_probabilities"
    )
    require(
        all(
            isinstance(p, int | float)
            and not isinstance(p, bool)
            and math.isfinite(p)
            and 0 <= p <= 1
            for p in probs
        ),
        "self_test.expected_probabilities[]",
    )
    tolerance = test.get("tolerance")
    require(isinstance(tolerance, float) and 0 < tolerance <= 0.05, "self_test.tolerance")

    return Manifest(
        manifest_version=raw["manifest_version"],
        model_key=raw["model_key"],
        repo=raw["repo"],
        revision=raw["revision"],
        artifact_dir=raw["artifact_dir"],
        files=tuple(files),
        labels=tuple(labels),
        max_input_chars=max_chars,
        max_tokens=max_tokens,
        packages=dict(packages),
        canary_sha256=test["canary_sha256"],
        expected_top_label=test["expected_top_label"],
        expected_probabilities=tuple(float(p) for p in probs),
        tolerance=tolerance,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def load_manifest(path: Path) -> Manifest:
    try:
        data = path.read_bytes()
    except OSError:
        raise ManifestError("manifest unreadable") from None
    if len(data) > 64 * 1024:
        raise ManifestError("manifest too large")
    return parse_manifest(data)
