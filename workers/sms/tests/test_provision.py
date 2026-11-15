"""Provisioning: download, verify each file, install all of them together or nothing at all."""

import json
from pathlib import Path

import pytest

from conftest import config_bytes, write_artifacts
from kavach_sms_worker import provision as provisioning
from kavach_sms_worker.artifacts import artifact_problems
from kavach_sms_worker.manifest import load_manifest
from kavach_sms_worker.provision import main, provision

FILES = {
    "config.json": config_bytes(),
    "tokenizer.json": b'{"fake": "tokenizer"}',
    "model.safetensors": b"fake weights, never loaded",
    "LICENSE": b"license text",
}


def fetcher(files: dict[str, bytes], calls: list[str]):
    def fetch(repo: str, revision: str, name: str, cache_dir: Path) -> Path:
        calls.append(name)
        assert repo == "Horizon-Labs/phishing-scam-detector-base" and len(revision) == 40
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / name
        path.write_bytes(files[name])
        return path

    return fetch


@pytest.fixture
def manifest(tmp_path):
    # The fixture manifest describes FILES; the artifacts it writes are not the provisioning target.
    write_artifacts(tmp_path / "elsewhere", FILES)
    return load_manifest(tmp_path / "elsewhere" / "manifest.json")


def test_downloads_verify_and_install_read_only(manifest, tmp_path):
    models = tmp_path / "models"
    calls: list[str] = []
    assert provision(manifest, models, fetcher(FILES, calls)) == []
    assert calls == list(FILES)
    assert artifact_problems(manifest, models) == []
    directory = models / manifest.artifact_dir
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == FILES
    assert all(path.stat().st_mode & 0o222 == 0 for path in directory.iterdir())
    assert list(models.rglob(".provision-*")) == [] and list(models.rglob("cache")) == []


def test_verified_artifacts_are_not_downloaded_again(manifest, tmp_path):
    models = tmp_path / "models"
    provision(manifest, models, fetcher(FILES, []))

    def refuse(*_):
        raise AssertionError("no download expected")

    assert provision(manifest, models, refuse) == []


@pytest.mark.parametrize("damaged", ["model.safetensors", "config.json"])
def test_a_mismatched_download_installs_nothing(manifest, tmp_path, damaged):
    models = tmp_path / "models"
    corrupt = FILES | {damaged: FILES[damaged] + b"x"}
    assert provision(manifest, models, fetcher(corrupt, [])) == [
        f"{damaged}: downloaded file differs from the manifest"
    ]
    assert not (models / manifest.artifact_dir).exists()
    assert list(models.rglob(".provision-*")) == []


def test_a_corrupt_existing_directory_is_replaced(manifest, tmp_path):
    models = tmp_path / "models"
    provision(manifest, models, fetcher(FILES, []))
    directory = models / manifest.artifact_dir
    (directory / "model.safetensors").chmod(0o644)
    (directory / "model.safetensors").write_bytes(b"tampered")
    assert artifact_problems(manifest, models) == ["model.safetensors: size differs"]
    assert provision(manifest, models, fetcher(FILES, [])) == []
    assert (directory / "model.safetensors").read_bytes() == FILES["model.safetensors"]


def test_cli_exit_codes_and_safe_messages(manifest, tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "elsewhere" / "manifest.json"
    models = tmp_path / "models"
    monkeypatch.setattr(provisioning, "hub_fetch", fetcher(FILES, []))
    assert main(["--manifest", str(manifest_path), "--model-dir", str(models)]) == 0
    assert manifest.model_version in capsys.readouterr().out

    def failing(*_):
        raise ConnectionError("https://secret.example/token=abc")

    monkeypatch.setattr(provisioning, "hub_fetch", failing)
    assert main(["--manifest", str(manifest_path), "--model-dir", str(tmp_path / "other")]) == 1
    err = capsys.readouterr().err
    assert "ConnectionError" in err and "secret.example" not in err

    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"manifest_version": 1}))
    assert main(["--manifest", str(broken), "--model-dir", str(models)]) == 2
