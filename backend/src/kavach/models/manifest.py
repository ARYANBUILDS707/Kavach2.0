"""The SMS model manifest as the API sees it (deployment/models/*.json).

The worker re-validates the same file with its own standard-library parser and verifies the
artifacts; the API validates it so the supervisor knows the labels, input limit and the exact
manifest digest the worker must report when it becomes ready.
"""

import hashlib
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MANIFEST_VERSION = 1
SAFE_FILE = r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(json|safetensors)$|^(LICENSE|NOTICE)$"
FORBIDDEN_SUFFIXES = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".joblib", ".h5", ".py")
MAX_MANIFEST_BYTES = 64 * 1024


class ManifestInvalid(Exception):
    """The manifest cannot be used; the message is fixed text, never file content."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ModelFile(Strict):
    name: str = Field(pattern=SAFE_FILE, max_length=128)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def no_pickle_or_code(cls, value: str) -> str:
        if value.lower().endswith(FORBIDDEN_SUFFIXES):
            raise ValueError("file type not allowed")
        return value


class Preprocessing(Strict):
    max_input_chars: int = Field(ge=1, le=4096)
    max_tokens: int = Field(ge=8, le=512)
    truncation: Literal["tokenizer"]
    normalization: Literal["none"]


class Runtime(Strict):
    python: Literal["3.12"]
    device: Literal["cpu"]
    packages: dict[str, str]


class SelfTest(Strict):
    canary_id: str = Field(max_length=64)
    canary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_top_label: str
    expected_probabilities: tuple[float, ...]
    tolerance: float = Field(gt=0, le=0.05)


class SmsModelManifest(Strict):
    manifest_version: Literal[1]
    stage: Literal["sms_classifier"]
    model_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: str = Field(max_length=300)
    provenance: str = Field(max_length=500)
    artifact_dir: str = Field(
        pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*$"
    )
    files: tuple[ModelFile, ...] = Field(min_length=3)
    labels: tuple[str, ...] = Field(min_length=2)
    preprocessing: Preprocessing
    score_semantics: Literal["uncalibrated_softmax"]
    calibration: None
    kavach_validation: Literal["not_validated"]
    runtime: Runtime
    self_test: SelfTest

    @field_validator("labels")
    @classmethod
    def distinct_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate labels")
        return value


class LoadedManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest: SmsModelManifest
    sha256: str

    @property
    def labels(self) -> tuple[str, ...]:
        return self.manifest.labels

    @property
    def max_input_chars(self) -> int:
        return self.manifest.preprocessing.max_input_chars

    @property
    def model_version(self) -> str:
        m = self.manifest
        return f"{m.model_key}@{m.revision[:12]}+m{m.manifest_version}:{self.sha256[:12]}"


def parse_manifest(data: bytes) -> LoadedManifest:
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestInvalid("manifest too large")
    try:
        manifest = SmsModelManifest.model_validate_json(data)
    except ValidationError:
        raise ManifestInvalid("manifest invalid") from None
    names = [f.name for f in manifest.files]
    test = manifest.self_test
    if (
        len(set(names)) != len(names)
        or not {"config.json", "tokenizer.json", "model.safetensors"} <= set(names)
        or test.expected_top_label not in manifest.labels
        or len(test.expected_probabilities) != len(manifest.labels)
        or not all(math.isfinite(p) and 0 <= p <= 1 for p in test.expected_probabilities)
        or ".." in manifest.artifact_dir.split("/")
    ):
        raise ManifestInvalid("manifest invalid")
    return LoadedManifest(manifest=manifest, sha256=hashlib.sha256(data).hexdigest())


def load_manifest(path: Path) -> LoadedManifest:
    try:
        data = path.read_bytes()
    except OSError:
        raise ManifestInvalid("manifest unreadable") from None
    return parse_manifest(data)
