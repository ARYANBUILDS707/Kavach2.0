"""Fetch the pinned model files a manifest names and verify them before they can be used.

This runs at image build time (deployment/Dockerfile.public) or by an operator preparing a model
directory. The worker never runs it: the worker stays offline and only verifies. Files are
downloaded into a staging directory beside the target, checked one by one against the manifest's
size and SHA-256, and moved into place together only when every file matches, so a mismatch or an
interrupted download leaves no partial artifact directory behind. Nothing is committed to Git.
"""

import argparse
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from kavach_sms_worker.artifacts import artifact_problems, file_sha256
from kavach_sms_worker.manifest import Manifest, ManifestError, load_manifest

# (repo, revision, file name, cache directory) -> the downloaded file's resolved path
Fetcher = Callable[[str, str, str, Path], Path]


def hub_fetch(repo: str, revision: str, name: str, cache_dir: Path) -> Path:
    """One file from the Hugging Face Hub at exactly the pinned revision (model group only)."""
    from huggingface_hub import hf_hub_download

    return Path(
        hf_hub_download(repo_id=repo, filename=name, revision=revision, cache_dir=cache_dir)
    ).resolve()


def provision(manifest: Manifest, model_dir: Path, fetch: Fetcher) -> list[str]:
    """Make `model_dir` hold the manifest's artifacts. Returns the remaining artifact problems
    (empty means verified). Artifacts that already verify are left untouched: no download."""
    if not artifact_problems(manifest, model_dir):
        return []
    target = model_dir / manifest.artifact_dir
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".provision-", dir=target.parent))
    try:
        for spec in manifest.files:
            downloaded = fetch(manifest.repo, manifest.revision, spec.name, staging / "cache")
            if downloaded.stat().st_size != spec.size_bytes or (
                file_sha256(downloaded) != spec.sha256
            ):
                return [f"{spec.name}: downloaded file differs from the manifest"]
            installed = staging / spec.name
            shutil.move(downloaded, installed)
            installed.chmod(0o444)
        shutil.rmtree(staging / "cache", ignore_errors=True)
        if target.exists():
            target.chmod(0o755)
            shutil.rmtree(target)
        staging.chmod(0o755)
        staging.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return artifact_problems(manifest, model_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download and verify the pinned SMS model named in a manifest."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as error:
        print(f"model provisioning refused: {error}", file=sys.stderr)
        return 2
    try:
        problems = provision(manifest, args.model_dir, hub_fetch)
    except Exception as error:  # hub or filesystem failure: the type only, never a URL or token
        print(f"model provisioning failed: {type(error).__name__}", file=sys.stderr)
        return 1
    if problems:
        print(f"model provisioning failed: {len(problems)} artifact problem(s)", file=sys.stderr)
        return 1
    print(f"model {manifest.model_version} verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
