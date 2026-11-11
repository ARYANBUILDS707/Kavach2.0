"""Worker process entry point.

Order of operations (docs/M4_SMS_INFERENCE_ARCHITECTURE.md §4):

1. Harden the process before anything else:
   - no core dumps;
   - private umask;
   - offline library settings;
   - a socket guard;
   - protocol frames on a private copy of stdout, with fd 1 pointed at stderr so stray library
     prints cannot corrupt the protocol.
2. Validate the manifest, verify every artifact, check the installed runtime against the
   manifest, check the canary hash. All of this happens before torch is imported.
3. Load once, run the self-test, send `ready`.
4. Answer `classify` frames one at a time until stdin closes.

Startup failures send one `fatal` frame with a fixed code and exit non-zero. Nothing here writes
message text anywhere: responses carry numbers and fixed codes only.
"""

import argparse
import os
import re
import resource
import socket
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, BinaryIO

from kavach_sms_worker.artifacts import ArtifactError, verify_artifacts
from kavach_sms_worker.canary import CANARY_TEXT, canary_sha256
from kavach_sms_worker.manifest import Manifest, ManifestError, load_manifest
from kavach_sms_worker.model import Classifier, ModelLoadError, load_classifier, runtime_mismatches
from kavach_sms_worker.protocol import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    read_frame,
    write_frame,
)

REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
REQUEST_KEYS = {"v", "type", "id", "text"}
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
}
EXIT_FATAL = 3

Loader = Callable[[Manifest, Path, int], Classifier]


class NetworkDisabled(OSError):
    """The worker never uses the network; any attempt fails here."""


def _refuse(*_: Any, **__: Any) -> Any:
    raise NetworkDisabled("network access is disabled in the SMS worker")


def disable_network() -> None:
    """In-process guard; OS-level enforcement is TD-27. Unix-domain socketpairs stay usable."""
    socket.getaddrinfo = _refuse
    socket.create_connection = _refuse
    socket.socket.connect = _refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = _refuse  # type: ignore[method-assign]
    socket.socket.sendto = _refuse  # type: ignore[method-assign]


def harden_process() -> None:
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass  # not supported here; documented, not fatal
    os.umask(0o077)
    os.environ.update(OFFLINE_ENV)
    disable_network()


def private_stdout() -> BinaryIO:
    """A private handle for frames; fd 1 is redirected to stderr for anything else."""
    frames = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return frames


def peak_rss_mb() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024)


def fatal(out: BinaryIO, code: str) -> int:
    write_frame(out, {"v": PROTOCOL_VERSION, "type": "fatal", "code": code}, MAX_RESPONSE_BYTES)
    return EXIT_FATAL


def close_to(expected: Sequence[float], found: Sequence[float], tolerance: float) -> bool:
    return len(expected) == len(found) and all(
        abs(a - b) <= tolerance for a, b in zip(expected, found, strict=True)
    )


def startup(
    manifest_path: Path,
    model_dir: Path,
    threads: int,
    loader: Loader = load_classifier,
    check_runtime: bool = True,
) -> tuple[Manifest, Classifier] | str:
    """The verified manifest and loaded classifier, or a fixed failure code."""
    try:
        manifest = load_manifest(manifest_path)
        directory = verify_artifacts(manifest, model_dir)
    except (ManifestError, ArtifactError):
        return "model_unverified"
    if canary_sha256() != manifest.canary_sha256:
        return "model_unverified"
    if check_runtime and runtime_mismatches(manifest):
        return "runtime_mismatch"
    try:
        classifier = loader(manifest, directory, threads)
        probabilities, _ = classifier.classify(CANARY_TEXT)
    except ModelLoadError:
        return "model_load_failed"
    top = manifest.labels[max(range(len(probabilities)), key=probabilities.__getitem__)]
    if top != manifest.expected_top_label or not close_to(
        manifest.expected_probabilities, probabilities, manifest.tolerance
    ):
        return "self_test_failed"
    return manifest, classifier


def valid_request(message: dict[str, Any], max_chars: int) -> bool:
    text = message.get("text")
    return (
        set(message) == REQUEST_KEYS
        and message.get("v") == PROTOCOL_VERSION
        and message.get("type") == "classify"
        and isinstance(message.get("id"), str)
        and bool(REQUEST_ID.match(message["id"]))
        and isinstance(text, str)
        and 1 <= len(text) <= max_chars
    )


def serve(
    manifest: Manifest,
    classifier: Classifier,
    stdin: BinaryIO,
    out: BinaryIO,
    rss: Callable[[], int] = peak_rss_mb,
    clock: Callable[[], int] = time.monotonic_ns,
) -> int:
    """Answer frames strictly one at a time; returns the exit code."""
    while True:
        try:
            message = read_frame(stdin, MAX_REQUEST_BYTES)
        except ProtocolError:
            return EXIT_FATAL  # the supervisor treats a dead worker as a crash and restarts it
        if message is None:
            return 0
        if not valid_request(message, manifest.max_input_chars):
            request_id = message.get("id")
            reply: dict[str, Any] = {
                "v": PROTOCOL_VERSION,
                "type": "result",
                "status": "error",
                "code": "invalid_input",
            }
            if isinstance(request_id, str) and REQUEST_ID.match(request_id):
                reply["id"] = request_id
            del message
            write_frame(out, reply, MAX_RESPONSE_BYTES)
            continue
        request_id = message["id"]
        started = clock()
        try:
            probabilities, truncated = classifier.classify(message["text"])
        except Exception:  # never echo library text; the code is enough
            reply = {
                "v": PROTOCOL_VERSION,
                "type": "result",
                "id": request_id,
                "status": "error",
                "code": "internal_error",
            }
        else:
            reply = {
                "v": PROTOCOL_VERSION,
                "type": "result",
                "id": request_id,
                "status": "ok",
                "probabilities": [round(float(p), 6) for p in probabilities],
                "truncated": bool(truncated),
                "duration_ms": max(0, (clock() - started) // 1_000_000),
                "rss_mb": rss(),
            }
        # Drop every reference to the text before waiting for the next frame. This does not
        # erase memory (TD-26); it only stops this process from keeping the text alive.
        del message
        write_frame(out, reply, MAX_RESPONSE_BYTES)


def main(
    argv: Sequence[str] | None = None,
    loader: Loader = load_classifier,
    check_runtime: bool = True,
) -> int:
    harden_process()
    out = private_stdout()
    parser = argparse.ArgumentParser(prog="kavach_sms_worker", add_help=False)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=2, choices=range(1, 9))
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return fatal(out, "invalid_arguments")
    result = startup(args.manifest, args.model_dir, args.threads, loader, check_runtime)
    if isinstance(result, str):
        return fatal(out, result)
    manifest, classifier = result
    write_frame(
        out,
        {
            "v": PROTOCOL_VERSION,
            "type": "ready",
            "manifest_sha256": manifest.sha256,
            "model_version": manifest.model_version,
            "self_test": "passed",
            "rss_mb": peak_rss_mb(),
        },
        MAX_RESPONSE_BYTES,
    )
    return serve(manifest, classifier, sys.stdin.buffer, out)
