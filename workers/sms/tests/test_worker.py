"""Worker tests without torch: protocol, manifest, artifact verification, startup, serve loop,
process hardening and offline guard."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REAL_MANIFEST, FakeClassifier, config_bytes, write_artifacts
from kavach_sms_worker import main as worker_main
from kavach_sms_worker.artifacts import artifact_problems
from kavach_sms_worker.manifest import ManifestError, load_manifest, parse_manifest
from kavach_sms_worker.protocol import (
    HEADER,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    ProtocolError,
    encode_frame,
    read_frame,
)

REQUEST_ID = "0123456789abcdef0123456789abcdef"
PRIVATE = "FICTIONAL PRIVATE 9921-WORKER-CANARY text"


def frames(data: bytes) -> list[dict]:
    stream, found = io.BytesIO(data), []
    while (message := read_frame(stream, 1 << 20)) is not None:
        found.append(message)
    return found


def request(text: str, **extra) -> bytes:
    return encode_frame(
        {"v": 1, "type": "classify", "id": REQUEST_ID, "text": text, **extra}, MAX_REQUEST_BYTES
    )


# --- protocol --------------------------------------------------------------------------------


def test_frames_round_trip_and_enforce_limits():
    data = encode_frame({"a": 1}, 64)
    assert read_frame(io.BytesIO(data), 64) == {"a": 1}
    assert read_frame(io.BytesIO(b""), 64) is None
    with pytest.raises(ProtocolError):
        encode_frame({"a": "x" * 100}, 64)
    for bad in [
        HEADER.pack(65) + b"x" * 65,
        HEADER.pack(0),
        HEADER.pack(5) + b"{oo",
        HEADER.pack(3) + b"[1]",
        HEADER.pack(4) + b"\xff\xfe\xfd\xfc",
        b"\x00\x00",
    ]:
        with pytest.raises(ProtocolError):
            read_frame(io.BytesIO(bad), 64)
    # 4,096 characters of 4-byte UTF-8 fit the request limit.
    assert len(request("\U0001f600" * 4096)) <= MAX_REQUEST_BYTES


# --- manifest --------------------------------------------------------------------------------


def test_the_committed_manifest_parses_and_names_its_version():
    manifest = load_manifest(REAL_MANIFEST)
    assert manifest.labels == ("legitimate", "spam", "fraud")
    assert manifest.max_input_chars == 4096 and manifest.max_tokens == 256
    assert manifest.model_version == (
        f"horizon-phishing-scam-base@fa686fc0d6a3+m1:{manifest.sha256[:12]}"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["files"].append(
            {"name": "training_args.bin", "sha256": "a" * 64, "size_bytes": 1}
        ),
        lambda d: d["files"].append({"name": "x.py", "sha256": "a" * 64, "size_bytes": 1}),
        lambda d: d.update(revision="main"),
        lambda d: d.update(calibration={}),
        lambda d: d.update(artifact_dir="../escape"),
        lambda d: d.update(artifact_dir="/abs"),
        lambda d: d["runtime"]["packages"].pop("torch"),
        lambda d: d["self_test"].update(expected_top_label="phishing"),
        lambda d: d["preprocessing"].update(max_tokens=100000),
        lambda d: d.update(files=[f for f in d["files"] if f["name"] != "tokenizer.json"]),
    ],
)
def test_invalid_manifests_are_refused(mutate):
    data = json.loads(REAL_MANIFEST.read_text())
    mutate(data)
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps(data).encode())


# --- artifacts -------------------------------------------------------------------------------


def test_matching_artifacts_verify(artifacts):
    manifest = load_manifest(artifacts / "manifest.json")
    assert artifact_problems(manifest, artifacts) == []


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        (
            lambda d: (d / "model.safetensors").write_bytes(b"fake weights, never loadeX"),
            "model.safetensors: sha256 differs",
        ),
        (
            lambda d: (d / "model.safetensors").write_bytes(b"short"),
            "model.safetensors: size differs",
        ),
        (lambda d: (d / "tokenizer.json").unlink(), "tokenizer.json: missing"),
        (lambda d: (d / "pytorch_model.bin").write_bytes(b"pickle"), "forbidden file present"),
        (lambda d: (d / "modeling_custom.py").write_bytes(b"import os"), "forbidden file present"),
        (lambda d: (d / "extra.json").write_bytes(b"{}"), "unexpected file present"),
    ],
)
def test_corrupted_missing_or_unexpected_artifacts_are_refused(artifacts, damage, expected):
    manifest = load_manifest(artifacts / "manifest.json")
    damage(artifacts / manifest.artifact_dir)
    assert expected in artifact_problems(manifest, artifacts)


def test_a_symlinked_artifact_is_refused(tmp_path):
    directory = write_artifacts(tmp_path)
    outside = tmp_path / "outside.safetensors"
    outside.write_bytes((directory / "model.safetensors").read_bytes())
    (directory / "model.safetensors").unlink()
    (directory / "model.safetensors").symlink_to(outside)
    manifest = load_manifest(tmp_path / "manifest.json")
    assert "model.safetensors: missing" in artifact_problems(manifest, tmp_path)


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (config_bytes(auto_map={"AutoModel": "x.Model"}), "config.json: custom code requested"),
        (
            config_bytes(id2label={"0": "legitimate", "1": "fraud", "2": "spam"}),
            "config.json: label map differs from manifest",
        ),
    ],
)
def test_config_requesting_custom_code_or_other_labels_is_refused(tmp_path, config, expected):
    files = {"config.json": config, "tokenizer.json": b"{}", "model.safetensors": b"w"}
    write_artifacts(tmp_path, files)
    manifest = load_manifest(tmp_path / "manifest.json")
    assert expected in artifact_problems(manifest, tmp_path)


# --- startup ---------------------------------------------------------------------------------


def fake_loader(classifier):
    def load(manifest, directory, threads):
        load.called = True
        return classifier

    load.called = False
    return load


def test_startup_loads_only_after_verification_and_runs_the_self_test(artifacts):
    loader = fake_loader(FakeClassifier())
    result = worker_main.startup(artifacts / "manifest.json", artifacts, 2, loader, False)
    assert not isinstance(result, str) and loader.called


def test_unverified_artifacts_never_reach_the_loader(artifacts):
    manifest = load_manifest(artifacts / "manifest.json")
    (artifacts / manifest.artifact_dir / "model.safetensors").write_bytes(
        b"tampered weightsXXXXXXX"
    )
    loader = fake_loader(FakeClassifier())
    code = worker_main.startup(artifacts / "manifest.json", artifacts, 2, loader, False)
    assert code == "model_unverified" and not loader.called


def test_self_test_mismatch_and_runtime_mismatch_are_fatal(artifacts):
    wrong = fake_loader(FakeClassifier([0.9, 0.05, 0.05]))
    assert worker_main.startup(artifacts / "manifest.json", artifacts, 2, wrong, False) == (
        "self_test_failed"
    )
    # Real runtime check: this test environment has no torch, so the approved runtime is absent.
    assert (
        worker_main.startup(
            artifacts / "manifest.json", artifacts, 2, fake_loader(FakeClassifier()), True
        )
        == "runtime_mismatch"
    )


def test_a_changed_canary_is_fatal(artifacts, monkeypatch):
    monkeypatch.setattr(worker_main, "CANARY_TEXT", "edited canary")
    monkeypatch.setattr(worker_main, "canary_sha256", lambda: "b" * 64)
    loader = fake_loader(FakeClassifier())
    code = worker_main.startup(artifacts / "manifest.json", artifacts, 2, loader, False)
    assert code == "model_unverified" and not loader.called


# --- serve loop ------------------------------------------------------------------------------


def serve(manifest_path: Path, data: bytes, classifier=None) -> tuple[int, list[dict]]:
    manifest = load_manifest(manifest_path)
    out = io.BytesIO()
    code = worker_main.serve(
        manifest,
        classifier or FakeClassifier(),
        io.BytesIO(data),
        out,
        rss=lambda: 900,
        clock=iter(range(0, 10**12, 7_000_000)).__next__,
    )
    return code, frames(out.getvalue())


def test_a_valid_request_returns_numbers_only(artifacts):
    code, replies = serve(artifacts / "manifest.json", request(PRIVATE))
    assert code == 0
    assert replies == [
        {
            "v": 1,
            "type": "result",
            "id": REQUEST_ID,
            "status": "ok",
            "probabilities": [0.0007, 0.0008, 0.9985],
            "truncated": False,
            "duration_ms": 7,
            "rss_mb": 900,
        }
    ]


@pytest.mark.parametrize(
    "frame",
    [
        request(PRIVATE, extra=1),
        request(""),
        request("x" * 4097),
        encode_frame({"v": 1, "type": "classify", "id": "not-hex", "text": PRIVATE}, 1 << 15),
        encode_frame({"v": 2, "type": "classify", "id": REQUEST_ID, "text": PRIVATE}, 1 << 15),
        encode_frame({"v": 1, "type": "shell", "id": REQUEST_ID, "text": PRIVATE}, 1 << 15),
        encode_frame({"v": 1, "type": "classify", "id": REQUEST_ID, "text": ["list"]}, 1 << 15),
    ],
)
def test_invalid_requests_get_a_fixed_code_and_no_echo(artifacts, frame):
    _, replies = serve(artifacts / "manifest.json", frame)
    assert replies[0]["status"] == "error" and replies[0]["code"] == "invalid_input"
    assert "WORKER-CANARY" not in json.dumps(replies)


def test_a_library_failure_is_reported_without_its_text(artifacts):
    classifier = FakeClassifier(fail=True)
    classifier.calls = 1  # past the self-test call
    _, replies = serve(artifacts / "manifest.json", request(PRIVATE), classifier)
    assert replies == [
        {"v": 1, "type": "result", "id": REQUEST_ID, "status": "error", "code": "internal_error"}
    ]


def test_an_oversized_or_broken_request_frame_ends_the_worker(artifacts):
    code, replies = serve(artifacts / "manifest.json", HEADER.pack(MAX_REQUEST_BYTES + 1))
    assert code == worker_main.EXIT_FATAL and replies == []


def test_responses_fit_the_response_limit():
    reply = {
        "v": 1,
        "type": "result",
        "id": REQUEST_ID,
        "status": "ok",
        "probabilities": [0.123456] * 3,
        "truncated": True,
        "duration_ms": 10**6,
        "rss_mb": 10**5,
    }
    assert len(encode_frame(reply, MAX_RESPONSE_BYTES)) < MAX_RESPONSE_BYTES


# --- process hardening, in a fresh interpreter -----------------------------------------------

HARDENING_PROBE = """
import json, os, resource, socket, sys
from kavach_sms_worker import main
main.harden_process()
out = main.private_stdout()
print("stray library print")  # must not reach the frame channel
result = {"core": resource.getrlimit(resource.RLIMIT_CORE),
          "umask": oct(os.umask(0o077)),
          "offline": os.environ.get("HF_HUB_OFFLINE")}
for name, attempt in [("connect", lambda: socket.create_connection(("127.0.0.1", 9))),
                      ("resolve", lambda: socket.getaddrinfo("huggingface.co", 443))]:
    try:
        attempt()
        result[name] = "allowed"
    except main.NetworkDisabled:
        result[name] = "blocked"
out.write(json.dumps(result).encode())
"""


def test_hardening_disables_core_dumps_network_and_stray_stdout():
    done = subprocess.run(
        [sys.executable, "-c", HARDENING_PROBE], capture_output=True, timeout=30, check=True
    )
    result = json.loads(done.stdout)
    assert result["core"] == [0, 0]
    assert result["umask"] == "0o77"
    assert result["offline"] == "1"
    assert result["connect"] == "blocked" and result["resolve"] == "blocked"
    assert b"stray library print" in done.stderr and b"stray" not in done.stdout


def test_end_to_end_process_with_fake_artifacts_answers_and_exits_cleanly(artifacts):
    tests_dir = str(Path(__file__).parent)
    probe = (
        f"import sys; sys.path.insert(0, {tests_dir!r}); from conftest import FakeClassifier; "
        "from kavach_sms_worker.main import main; "
        "raise SystemExit(main(sys.argv[1:], loader=lambda m, d, t: FakeClassifier(), "
        "check_runtime=False))"
    )
    args = [
        sys.executable,
        "-c",
        probe,
        "--manifest",
        str(artifacts / "manifest.json"),
        "--model-dir",
        str(artifacts),
    ]
    done = subprocess.run(
        args, input=request(PRIVATE), capture_output=True, timeout=30, env={"PATH": os.defpath}
    )
    assert done.returncode == 0
    ready, result = frames(done.stdout)
    assert ready["type"] == "ready" and ready["self_test"] == "passed"
    assert ready["manifest_sha256"] == load_manifest(artifacts / "manifest.json").sha256
    assert result["status"] == "ok" and result["id"] == REQUEST_ID
    assert b"WORKER-CANARY" not in done.stdout + done.stderr


def test_startup_failure_sends_one_fatal_frame(tmp_path):
    args = [
        sys.executable,
        "-m",
        "kavach_sms_worker",
        "--manifest",
        str(tmp_path / "missing.json"),
        "--model-dir",
        str(tmp_path),
    ]
    done = subprocess.run(args, capture_output=True, timeout=30)
    assert done.returncode == worker_main.EXIT_FATAL
    assert frames(done.stdout) == [{"v": 1, "type": "fatal", "code": "model_unverified"}]
