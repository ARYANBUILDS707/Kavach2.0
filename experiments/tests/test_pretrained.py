"""Pretrained proof-of-concept tests. No network, no torch, no real weights: downloads are served
from in-memory bytes and the classifier is a fake defined here, never used outside tests."""

import hashlib
import io
import json
import re
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from pretrained import cli
from pretrained.candidates import (
    CANDIDATES,
    HORIZON,
    REVISION,
    SHA256,
    ModelFile,
    allowed_file_name,
    selected,
)
from pretrained.demo import DEMO_MESSAGES
from pretrained.fetch import ModelFetchError, fetch, model_dir, verify
from pretrained.inference import (
    MAX_INPUT_CHARS,
    ModelUnavailable,
    check_config,
    load_classifier,
    predict,
)

CONFIG = json.dumps({"id2label": {"0": "legitimate", "1": "spam", "2": "fraud"}}).encode()
WEIGHTS = b"not real weights"


def spec(name: str, data: bytes) -> ModelFile:
    return ModelFile(name, hashlib.sha256(data).hexdigest(), len(data))


def fake_candidate(files: dict[str, bytes] | None = None):
    files = files or {"config.json": CONFIG, "model.safetensors": WEIGHTS}
    return replace(HORIZON, files=tuple(spec(n, d) for n, d in files.items())), files


class Response(io.BytesIO):
    status = 200


class Server:
    """Serves fixed bytes per URL and records (url, start) requests.

    `cut` ends each response after that many bytes, like a network that drops long transfers;
    `ranges=False` ignores Range requests and always sends the whole file.
    """

    def __init__(self, files: dict[str, bytes], cut: int | None = None, ranges: bool = True):
        self.files, self.cut, self.ranges, self.requested = files, cut, ranges, []

    def __call__(self, url: str, start: int = 0):
        self.requested.append((url, start))
        data = self.files[url.rsplit("/", 1)[1]]
        offset = start if self.ranges else 0
        response = Response(data[offset:][: self.cut])
        response.status = 206 if offset else 200
        return response


class FakeClassifier:
    """Test double: fixed probabilities per call, in the candidate's label order."""

    labels = HORIZON.labels

    def __init__(self, rows: list[list[float]]) -> None:
        self.rows, self.seen = rows, []

    def probabilities(self, texts):
        self.seen.extend(texts)
        return self.rows[: len(texts)]


# --- candidates ------------------------------------------------------------------------------


def test_exactly_one_candidate_is_selected_and_every_pin_is_exact():
    assert selected() is HORIZON
    for c in CANDIDATES.values():
        assert REVISION.match(c.revision)
        assert c.weights.name == "model.safetensors"
        assert all(SHA256.match(f.sha256) and f.size_bytes > 0 for f in c.files)
        assert set(c.fraud_labels) <= set(c.labels) and set(c.spam_labels) <= set(c.labels)


def test_no_candidate_lists_a_pickle_or_code_file():
    for c in CANDIDATES.values():
        assert all(allowed_file_name(f.name) for f in c.files)
    names = ["training_args.bin", "pytorch_model.bin", "model.pt", "x.pkl", "modeling.py",
             "../config.json", "onnx/model.onnx", ".hidden.json"]  # fmt: skip
    assert not any(allowed_file_name(n) for n in names)
    assert all(allowed_file_name(n) for n in ["config.json", "model.safetensors", "LICENSE"])


# --- fetch and verify ------------------------------------------------------------------------


def test_fetch_keeps_only_verified_files_from_the_pinned_revision(tmp_path):
    candidate, files = fake_candidate()
    server = Server(files)
    assert fetch(candidate, tmp_path, server) == ["config.json", "model.safetensors"]
    assert all(f"/resolve/{candidate.revision}/" in u for u, _ in server.requested)
    assert all(u.startswith("https://huggingface.co/") for u, _ in server.requested)
    assert verify(candidate, tmp_path) == []
    assert fetch(candidate, tmp_path, server) == []  # already verified: nothing re-downloaded


def test_a_dropped_transfer_is_resumed_by_range_and_still_verified(tmp_path):
    candidate, files = fake_candidate({"model.safetensors": WEIGHTS})  # 16 bytes
    server = Server(files, cut=5)  # every response ends after 5 bytes: four attempts
    fetch(candidate, tmp_path, server)
    assert verify(candidate, tmp_path) == []
    starts = [s for u, s in server.requested if u.endswith("model.safetensors")]
    assert starts == list(range(0, len(WEIGHTS), 5))


def test_a_server_that_ignores_ranges_restarts_from_zero(tmp_path):
    candidate, files = fake_candidate({"model.safetensors": WEIGHTS})
    directory = model_dir(candidate, tmp_path)
    directory.mkdir(parents=True)
    fetch(candidate, tmp_path, Server(files, ranges=False))
    assert (directory / "model.safetensors").read_bytes() == WEIGHTS


def test_a_transfer_that_never_completes_is_abandoned_without_a_partial(tmp_path):
    candidate, files = fake_candidate({"model.safetensors": WEIGHTS * 100})
    with pytest.raises(ModelFetchError, match="incomplete"):
        fetch(candidate, tmp_path, Server(files, cut=3))
    assert not list(model_dir(candidate, tmp_path).iterdir())


def test_a_leftover_partial_is_discarded_not_resumed(tmp_path):
    candidate, files = fake_candidate({"model.safetensors": WEIGHTS})
    directory = model_dir(candidate, tmp_path)
    directory.mkdir(parents=True)
    (directory / "model.safetensors.partial").write_bytes(b"planted")
    server = Server(files)
    fetch(candidate, tmp_path, server)
    assert server.requested[0][1] == 0
    assert (directory / "model.safetensors").read_bytes() == WEIGHTS


@pytest.mark.parametrize("served", [b"tampered weights", WEIGHTS + b"x", WEIGHTS[:-1]])
def test_a_substituted_or_truncated_file_is_never_kept(tmp_path, served):
    candidate, files = fake_candidate()
    with pytest.raises(ModelFetchError):
        fetch(candidate, tmp_path, Server({**files, "model.safetensors": served}))
    directory = model_dir(candidate, tmp_path)
    assert not (directory / "model.safetensors").exists()
    assert not list(directory.glob("*.partial"))


def test_an_existing_different_file_is_not_overwritten(tmp_path):
    candidate, files = fake_candidate()
    directory = model_dir(candidate, tmp_path)
    directory.mkdir(parents=True)
    (directory / "model.safetensors").write_bytes(b"something else")
    with pytest.raises(ModelFetchError, match="not overwritten"):
        fetch(candidate, tmp_path, Server(files))
    assert (directory / "model.safetensors").read_bytes() == b"something else"


def test_unselected_candidates_and_disallowed_files_are_refused(tmp_path):
    with pytest.raises(ModelFetchError, match="not the selected"):
        fetch(CANDIDATES["scamshield"], tmp_path, Server({}))
    candidate, files = fake_candidate({"training_args.bin": b"pickle"})
    with pytest.raises(ModelFetchError, match="not allowed"):
        fetch(candidate, tmp_path, Server(files))
    with pytest.raises(ModelFetchError, match="40-character"):
        fetch(replace(HORIZON, revision="main"), tmp_path, Server({}))


def test_the_default_opener_refuses_hosts_outside_the_hub():
    from pretrained.fetch import default_opener
    from sms_prep.acquire import AcquisitionError

    for url in [
        "http://huggingface.co/x",
        "https://evil.example/x",
        "https://user@huggingface.co/x",
    ]:
        with pytest.raises(AcquisitionError):
            default_opener(url)


def test_verify_reports_missing_modified_and_stray_files(tmp_path):
    candidate, files = fake_candidate()
    assert verify(candidate, tmp_path) == ["model directory missing"]
    fetch(candidate, tmp_path, Server(files))
    directory = model_dir(candidate, tmp_path)
    (directory / "model.safetensors").write_bytes(b"x" * len(WEIGHTS))
    (directory / "pytorch_model.bin").write_bytes(b"pickle")
    (directory / "config.json").unlink()
    problems = verify(candidate, tmp_path)
    assert "pytorch_model.bin: forbidden file in the model directory" in problems
    assert "config.json: missing" in problems
    assert any(p.startswith("model.safetensors: size or SHA-256") for p in problems)


# --- loading ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"id2label": {"0": "legitimate", "1": "spam", "2": "fraud"}, "auto_map": {"x": "y"}},
         "custom code"),
        ({"id2label": {"0": "legitimate", "1": "fraud", "2": "spam"}}, "label map"),
        ({}, "label map"),
    ],
)  # fmt: skip
def test_config_with_custom_code_or_a_changed_label_map_is_refused(tmp_path, config, message):
    (tmp_path / "config.json").write_text(json.dumps(config))
    with pytest.raises(ModelUnavailable, match=message):
        check_config(HORIZON, tmp_path)


def test_unverified_files_never_reach_the_loader(tmp_path, monkeypatch):
    import pretrained.inference as inference

    def must_not_load(*_):
        raise AssertionError("loader reached")

    monkeypatch.setattr(inference, "TransformersClassifier", must_not_load)
    with pytest.raises(ModelUnavailable, match="do not verify"):
        load_classifier(HORIZON, tmp_path)
    candidate, files = fake_candidate()
    fetch(candidate, tmp_path, Server(files))
    (model_dir(candidate, tmp_path) / "extra.pkl").write_bytes(b"pickle")
    with pytest.raises(ModelUnavailable, match="do not verify"):
        load_classifier(candidate, tmp_path)


def test_the_real_loader_is_offline_safetensors_only_and_never_runs_remote_code(
    tmp_path, monkeypatch
):
    import os
    import sys
    import types

    import pretrained.inference as inference

    calls = {}

    class Auto:
        def __init__(self, kind, id2label):
            self.kind, self.id2label = kind, id2label

        def from_pretrained(self, directory, **kwargs):
            calls[self.kind] = (directory, kwargs, os.environ.get("HF_HUB_OFFLINE"))
            model = types.SimpleNamespace(config=types.SimpleNamespace(id2label=self.id2label))
            model.eval = lambda: None
            return model

    def install(id2label):
        fake_torch = types.SimpleNamespace(float32="float32")
        fake_transformers = types.SimpleNamespace(
            AutoTokenizer=Auto("tokenizer", {}),
            AutoModelForSequenceClassification=Auto("model", id2label),
        )
        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    for key in inference.OFFLINE_ENV:
        monkeypatch.delenv(key, raising=False)
    install(dict(enumerate(HORIZON.labels)))
    inference.TransformersClassifier(HORIZON, tmp_path)
    for kind in ("tokenizer", "model"):
        directory, kwargs, offline = calls[kind]
        assert directory == tmp_path and offline == "1"
        assert kwargs["local_files_only"] is True and kwargs["trust_remote_code"] is False
    assert calls["model"][1]["use_safetensors"] is True

    install({0: "legitimate", 1: "fraud", 2: "spam"})  # weights disagree with the pinned labels
    with pytest.raises(ModelUnavailable, match="label map"):
        inference.TransformersClassifier(HORIZON, tmp_path)


# --- prediction ------------------------------------------------------------------------------


def test_unavailable_predictions_carry_null_scores_never_zero():
    results = predict(None, HORIZON, ["a", "b"], "model files do not verify")
    assert [r.status for r in results] == ["unavailable"] * 2
    for r in results:
        assert r.label is None and r.fraud_score is None and r.unwanted_score is None
        assert r.probabilities is None and r.reason == "model files do not verify"


def test_scores_follow_the_candidate_label_map():
    classifier = FakeClassifier([[0.1, 0.2, 0.7], [0.6, 0.3, 0.1]])
    first, second = predict(classifier, HORIZON, ["one", "two"])
    assert (first.label, first.fraud_score, first.unwanted_score) == ("fraud", 0.7, 0.9)
    assert (second.label, second.fraud_score) == ("legitimate", 0.1)
    assert second.unwanted_score == pytest.approx(0.4)
    assert first.probabilities == {"legitimate": 0.1, "spam": 0.2, "fraud": 0.7}


def test_input_is_bounded_and_empty_input_is_rejected():
    classifier = FakeClassifier([[1.0, 0.0, 0.0]])
    predict(classifier, HORIZON, ["x" * (MAX_INPUT_CHARS + 500)])
    assert len(classifier.seen[0]) == MAX_INPUT_CHARS
    with pytest.raises(ValueError):
        predict(classifier, HORIZON, ["   "])


def test_a_wrong_output_shape_is_unavailable_not_a_score():
    with pytest.raises(ModelUnavailable):
        predict(FakeClassifier([[0.5, 0.5]]), HORIZON, ["x"])
    with pytest.raises(ModelUnavailable):
        predict(FakeClassifier([]), HORIZON, ["x"])


# --- demo set and runner ---------------------------------------------------------------------


def test_demo_messages_are_fictional_and_carry_no_real_identifiers():
    assert len({m.id for m in DEMO_MESSAGES}) == len(DEMO_MESSAGES) == 14
    assert {m.intent for m in DEMO_MESSAGES} == {"phishing", "scam", "spam", "legitimate"}
    for m in DEMO_MESSAGES:
        assert m.fictional and m.text.startswith("FICTIONAL DEMO: ")
        hosts = re.findall(r"https?://([^/\s]+)", m.text)
        assert all(h.endswith(".example") for h in hosts)
        assert not re.search(r"\d{10}|\+\d", m.text)  # no phone numbers


def test_run_without_a_model_reports_unavailable_with_null_scores_and_no_text(tmp_path, capsys):
    code = cli.main(["--model-root", str(tmp_path / "none"), "--reports", str(tmp_path), "run"])
    assert code == 3
    report = json.loads((tmp_path / cli.REPORT_NAME).read_text())
    assert report["status"] == "unavailable"
    assert all(m["fraud_score"] is None for m in report["messages"])
    dumped = json.dumps(report) + capsys.readouterr().out
    assert not any(m.text[16:60] in dumped for m in DEMO_MESSAGES)


def test_the_runner_accepts_no_free_text_or_file_input():
    with pytest.raises(SystemExit):
        cli.main(["run", "--input", "messages.csv"])
    with pytest.raises(SystemExit):
        cli.main(["run", "some message text"])


def test_the_deployment_manifest_matches_the_audited_pins():
    """The runtime manifest (deployment/models) must describe exactly the audited candidate."""
    path = Path(__file__).parents[2] / "deployment" / "models" / "sms_classifier.horizon.v1.json"
    manifest = json.loads(path.read_text())
    assert manifest["repo"] == HORIZON.repo and manifest["revision"] == HORIZON.revision
    assert tuple(manifest["labels"]) == HORIZON.labels
    assert {(f["name"], f["sha256"], f["size_bytes"]) for f in manifest["files"]} == {
        (f.name, f.sha256, f.size_bytes) for f in HORIZON.files
    }
    assert manifest["artifact_dir"] == f"{HORIZON.key}/{HORIZON.revision}"
    pins = {
        r.split("==")[0]: r.split("==")[1]
        for r in tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())[
            "dependency-groups"
        ]["pretrained"]
    }
    assert manifest["runtime"]["packages"] == pins
    assert manifest["calibration"] is None and manifest["kavach_validation"] == "not_validated"
