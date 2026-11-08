"""M4.2 command line (run from the experiments/ directory):

    python -m sms_prep acquire   [--data-dir DIR]   download + verify the approved datasets
    python -m sms_prep verify    [--data-dir DIR]   offline checksum check of stored files
    python -m sms_prep build     [--data-dir DIR]   records, clusters, review, splits, reports
    python -m sms_prep audit     [--data-dir DIR]   evaluate completed human review sheets
    python -m sms_prep pairs     [--sample N]       review cross-split near-duplicate pairs
    python -m sms_prep split     [--version 2]      create a proposed split version beside v1
    python -m sms_prep pilot                        create the blinded calibration pilot
    python -m sms_prep pilot-audit                  agreement and control accuracy of the pilot
    python -m sms_prep solo-prepare                 blinded sheet for ONE reviewer (M4-Q)
    python -m sms_prep solo-preflight               read-only readiness check, no model
    python -m sms_prep solo-evaluate                compare the labels with the pretrained model

Private outputs (raw files, the record store, review sheets) go under the data directory, which
defaults to the ignored `data/m4/` at the repository root. Public outputs (aggregate reports and
split metadata) are written to `experiments/reports/` and `experiments/manifests/`. Nothing
printed contains message text.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from dataset_governance.fingerprints import REPO_ROOT, simulator_overlap
from dataset_governance.manifest import DEFAULT_MANIFEST, MANIFESTS, load_manifest
from sms_prep import pairs as pair_review
from sms_prep import pilot, review, solo, solo_preflight, split_report, synthetic
from sms_prep.acquire import AcquisitionError, acquire, specs_from_manifest, verify_local
from sms_prep.clusters import assign_clusters, build_cluster_infos, read_clusters, write_clusters
from sms_prep.normalize import FEATURE_NORMALIZATION_VERSION
from sms_prep.quality import (
    cluster_threshold_sensitivity,
    contamination_section,
    dedup_section,
    label_section,
    shortcut_feasibility,
    source_section,
    split_section,
)
from sms_prep.records import (
    IMC,
    MISHRA,
    UCI,
    load_imc,
    load_mishra,
    load_uci,
    read_records,
    synthetic_records,
    write_records,
)  # fmt: skip
from sms_prep.split_versions import VERSIONS
from sms_prep.splits import (
    DEFAULT_PROPORTIONS,
    DEFAULT_SEED,
    SPLIT_ALGORITHM_VERSION,
    SPLITS,
    assign_splits,
    read_assignments,
    record_assignments,
    write_assignments,
)  # fmt: skip

DEFAULT_DATA_DIR = REPO_ROOT / "data" / "m4"
REPORTS = Path(__file__).parents[1] / "reports"
CLUSTER_THRESHOLD = 0.7
RAW_FILES = {IMC: "final_dataset_output.csv", UCI: "SMSSpamCollection", MISHRA: "Dataset_5971.csv"}


class BuildError(Exception):
    pass


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def cmd_acquire(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    for spec in specs_from_manifest(manifest):
        stored = acquire(spec, args.data_dir / "raw", manifest.manifest_version)
        version = manifest.manifest_version
        print(f"{spec.id}: verified {len(stored)} file(s) against manifest v{version}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    for spec in specs_from_manifest(manifest):
        verify_local(spec, args.data_dir / "raw" / spec.id)
        print(f"{spec.id}: stored files match the manifest")
    return 0


def audit_status(args: argparse.Namespace) -> dict:
    clusters = args.data_dir / "work" / "clusters.jsonl"
    sizes = (
        {c.cluster_id: c.candidate_records for c in read_clusters(clusters)}
        if clusters.exists()
        else None
    )
    status = review.evaluate_audit(args.data_dir / "review", cluster_sizes=sizes)
    write_json(args.reports_dir / "label_audit_status.json", status)
    return status


def cmd_audit(args: argparse.Namespace) -> int:
    status = audit_status(args)
    progress = status["progress"]
    queued = review.write_adjudication_queue(args.data_dir / "review")
    if queued:
        print(
            f"{queued} disagreement(s) written to review/adjudication_queue.csv for the adjudicator"
        )
    print(
        f"Label approval: {status['label_approval']} "
        f"({progress['reviewer_a_completed']}/{progress['items']} reviewer A, "
        f"{progress['reviewer_b_completed']}/{progress['items']} reviewer B, "
        f"{progress['disagreements_unadjudicated']} unadjudicated disagreements)"
    )
    for klass, entry in status["classes"].items():
        print(f"  {klass}: {entry['status']} (sampled {entry['sampled']})")
    problems = {k: v for k, v in progress["sheet_problems"].items() if v}
    if problems:
        print(f"  sheet problems: {problems}")
    if not progress["answer_key_intact"]:
        print("  the answer key does not match the bundle metadata")
    if not progress["adjudicators_independent"]:
        print("  an adjudicator is also a reviewer")
    for warning in status["reviewer_quality"]["warnings"]:
        print(f"  warning: {warning}")
    return 0 if status["label_approval"] != "BLOCKED" else 3


def ensure_bundle(directory: Path, records, infos, seed: int, per_class: int) -> dict:
    """Create the review bundle once; never overwrite sheets that may hold annotations."""
    key_path = directory / "answer_key.json"
    if key_path.exists():
        existing = set(json.loads(key_path.read_text()))
        planned = {i.item_id for i in review.select_items(records, infos, seed, per_class)}
        if existing != planned:
            raise BuildError("A review bundle with different items already exists; not overwriting")
        meta_path = directory / "bundle_meta.json"
        meta = json.loads(meta_path.read_text())
        rubric_path = directory / "RUBRIC.md"
        if meta.get("rubric_version") != review.RUBRIC_VERSION or (
            rubric_path.read_text() != review.RUBRIC
        ):
            if review.has_annotations(directory):
                raise BuildError("The rubric changed after review began; not overwriting")
            rubric_path.write_text(review.RUBRIC)
            meta["rubric_version"] = review.RUBRIC_VERSION
            write_json(meta_path, meta)
        return meta
    return review.build_bundle(records, infos, directory, seed, per_class)


def cmd_build(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    work = args.data_dir / "work"
    specs = {s.id: s for s in specs_from_manifest(manifest)}
    for spec in specs.values():
        verify_local(spec, args.data_dir / "raw" / spec.id)  # refuses changed or unknown files
    raw = args.data_dir / "raw"
    messages = synthetic.generate(args.seed)
    set_record = manifest.synthetic_sets[0]
    if synthetic.corpus_sha256(messages) != set_record.corpus_sha256:
        raise BuildError("The synthetic corpus differs from the manifest; a new version is needed")
    records = (
        load_imc(raw / IMC / RAW_FILES[IMC]) + load_uci(raw / UCI / RAW_FILES[UCI])
        + load_mishra(raw / MISHRA / RAW_FILES[MISHRA]) + synthetic_records(messages)
    )  # fmt: skip
    if simulator_overlap([r.text for r in records if r.role != "reference"]):
        raise BuildError("A simulator fixture text appears in the data")
    records_sha = write_records(work / "records.jsonl", records)
    assignment = assign_clusters(records, CLUSTER_THRESHOLD)
    infos = build_cluster_infos(records, assignment)
    clusters_sha = write_clusters(work / "clusters.jsonl", infos)
    cluster_split = assign_splits(infos, args.seed, DEFAULT_PROPORTIONS)
    rows = record_assignments(records, infos, cluster_split)
    assignments_sha = write_assignments(work / "assignments.jsonl", rows)

    bundle = ensure_bundle(args.data_dir / "review", records, infos, args.seed, args.per_class)
    status = audit_status(args)

    counts = {s: Counter() for s in SPLITS}
    unique_texts = {s: 0 for s in SPLITS}
    for info in infos:
        split = cluster_split.get(info.cluster_id)
        if split:
            counts[split]["clusters"] += 1
            unique_texts[split] += info.unique_texts
    for row in rows:
        counts[row.split]["records"] += 1
        counts[row.split][f"records_{row.origin}"] += 1
    manifest_sha = file_sha256(args.manifest)
    meta = {
        "split_version": 1,
        "algorithm_version": SPLIT_ALGORITHM_VERSION,
        "seed": args.seed,
        "proportions": DEFAULT_PROPORTIONS,
        "unit": "cluster (exact + near-duplicate + synthetic template family)",
        "stratified_by": "source:label",
        "cluster_jaccard_threshold": CLUSTER_THRESHOLD,
        "manifest": {"version": manifest.manifest_version, "sha256": manifest_sha},
        "feature_normalization_version": FEATURE_NORMALIZATION_VERSION,
        "inputs": {
            "records_sha256": records_sha,
            "clusters_sha256": clusters_sha,
            "synthetic_corpus_sha256": set_record.corpus_sha256,
            "raw_files": {
                f.name: f.sha256
                for d in manifest.datasets
                if d.status != "excluded"
                for f in d.files
                if f.extract
            },
        },
        "assignments_sha256": assignments_sha,
        "counts": {s: {**counts[s], "unique_texts": unique_texts[s]} for s in SPLITS},
        "frozen": True,
        "freeze_policy": (
            "Assignment depends only on the seed and cluster IDs, not on label approval. A class "
            "that fails the label audit drops out of every split; no remaining cluster moves. "
            "The test split is read only through HeldOutGuard for a logged final evaluation."
        ),
        "label_audit_status": status["label_approval"],
        "labels_approved": status["label_approval"] == "APPROVED_CLASSES",
        "real_world_test_excludes_synthetic": True,
        "synthetic_template_families_are_split_groups": True,
    }
    write_json(args.meta_dir / "sms_split.v1.meta.json", meta)

    report = {
        "report_version": 1,
        "manifest": meta["manifest"],
        "inputs": meta["inputs"],
        "records_by_dataset_and_role": {
            f"{d}|{role}": n
            for (d, role), n in sorted(Counter((r.dataset, r.role) for r in records).items())
        },
        "deduplication": dedup_section(records, infos),
        "cluster_threshold_sensitivity": cluster_threshold_sensitivity(records, assign_clusters),
        "labels": label_section(infos),
        "splits": split_section(infos, cluster_split, DEFAULT_PROPORTIONS),
        "contamination": contamination_section(records, rows, infos),
        "source_and_era": source_section(records, rows),
        "source_shortcut_feasibility": shortcut_feasibility(infos, cluster_split),
        "label_audit": {
            "status": status["label_approval"],
            "progress": status["progress"],
            "bundle": {
                k: bundle[k]
                for k in (
                    "items",
                    "reviews_required",
                    "gated_items_by_class",
                    "gated_clusters_available_by_class",
                    "smallest_sample_that_can_pass",
                    "min_correct_for_gate",
                )
            },
        },  # fmt: skip
        "limitations": [
            "Grouped splitting prevents duplicate and template leakage; it does not solve source "
            "or era confounding (UCI 2003-2011 negatives vs IMC 2017-2024 positives).",
            "No IMC class has completed human review, so no class is promoted to phishing.",
            "Synthetic hard negatives are reported separately and are not real-world evidence.",
        ],
    }
    write_json(args.reports_dir / "m4_2_data_quality.json", report)
    print(
        f"records {len(records)} | clusters {len(infos)} | assigned records {len(rows)} | "
        f"label approval {status['label_approval']}"
    )
    for s in SPLITS:
        print(f"  {s}: {dict(counts[s])}, unique texts {unique_texts[s]}")
    print(f"  contamination: {report['contamination']['clusters_spanning_more_than_one_split']} "
          f"clusters span splits, simulator matches "
          f"{report['contamination']['simulator_fixture_matches_in_all_records']}")  # fmt: skip
    return 0


def cmd_pairs(args: argparse.Namespace) -> int:
    """Review near-duplicate pairs that cross the frozen split. Aggregates only; writes no split."""
    work = args.data_dir / "work"
    records = read_records(work / "records.jsonl")
    rows = read_assignments(work / "assignments.jsonl")
    items = pair_review.unique_texts(records, rows)
    crossing, total = pair_review.cross_split_pairs(items, args.threshold)
    report = {
        "frozen_split_assignments_sha256": file_sha256(work / "assignments.jsonl"),
        "threshold": args.threshold,
        "summary": pair_review.summarize(items, crossing, total),
        "v1_leakage_profile": pair_review.leakage_profile(
            items, pair_review.cross_split_pairs(items, min(pair_review.LEAKAGE_LEVELS))[0]
        ),
        "dry_run_stricter_grouping": [
            pair_review.recluster_dry_run(records, rows, t, DEFAULT_SEED) for t in args.dry_run
        ],
        "note": (
            "Aggregates only. The dry runs write no split; creating sms_split.v2 is a separate "
            "decision. Test text was never displayed."
        ),
    }
    write_json(args.reports_dir / "m4_2_pair_review.json", report)
    if args.sample:
        sample = pair_review.masked_sample(records, items, crossing, args.sample_seed, args.sample)
        target = args.data_dir / "pair_review"
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / "sample_train_validation.json", {"pairs": sample})
        print(f"wrote {len(sample)} masked train/validation pairs to the private data directory")
    summary = report["summary"]
    shown = summary["test_texts_in_a_cross_split_pair"]["share"]
    print(
        f"pairs at {args.threshold}: {summary['pairs_at_threshold']}, across splits "
        f"{summary['pairs_across_splits']}; test texts affected {shown:.2%}"
    )
    return 0


SPLIT_LEAKAGE_LEVELS = (0.3, 0.35, 0.4, 0.5, 0.6, 0.7)


def cmd_pilot(args: argparse.Namespace) -> int:
    """Create the blinded calibration pilot once; never overwrite sheets someone has started."""
    directory = args.data_dir / "review_pilot"
    main_key = json.loads((args.data_dir / "review" / "answer_key.json").read_text())
    work = args.data_dir / "work"
    records = read_records(work / "records.jsonl")
    infos = read_clusters(work / "clusters.jsonl")
    if (directory / "answer_key.json").exists():
        planned = {i.item_id for i in pilot.select_pilot(records, infos, main_key, args.seed)}
        existing = set(json.loads((directory / "answer_key.json").read_text()))
        if planned != existing:
            raise BuildError("A pilot with different items already exists; not overwriting")
        if (directory / "RUBRIC.md").read_text() != review.RUBRIC:
            if pilot.pilot_has_annotations(directory):
                raise BuildError("The rubric changed after the pilot began; not overwriting")
            (directory / "RUBRIC.md").write_text(review.RUBRIC)
        print(f"pilot already exists ({len(existing)} items); left unchanged")
        return 0
    meta = pilot.build_pilot(records, infos, main_key, directory, args.seed)
    print(f"pilot created: {meta['items']} items per reviewer, {meta['items_by_kind']}")
    return 0


def cmd_pilot_audit(args: argparse.Namespace) -> int:
    status = pilot.evaluate_pilot(args.data_dir / "review_pilot")
    write_json(args.reports_dir / "pilot_status.json", status)
    agreement = status["agreement"]
    print(
        f"Pilot: {status['status']} (not used by the gate); compared {agreement['items_compared']}"
        f"/{status['progress']['items']}, disagreements {agreement['disagreements']}, "
        f"kappa {agreement['cohen_kappa']}"
    )
    return 0 if status["status"] != "INCOMPLETE" else 3


def frozen_assignments(args: argparse.Namespace, version: int) -> list:
    """A split version's assignments, only if they still match their recorded metadata."""
    spec = VERSIONS[version]
    meta = json.loads((args.meta_dir / spec.meta_name).read_text())
    path = spec.assignments(args.data_dir)
    if file_sha256(path) != meta["assignments_sha256"]:
        raise BuildError(f"The split v{version} assignment file differs from its metadata")
    return read_assignments(path)


def solo_context(args: argparse.Namespace) -> tuple[solo.Revision, Path, Path]:
    """(revision, private bundle folder, registered criteria file) for the chosen revision."""
    revision = solo.REVISIONS[args.revision]
    criteria = args.criteria or args.meta_dir / revision.criteria_file
    return revision, args.data_dir / revision.folder, criteria


def cmd_solo_prepare(args: argparse.Namespace) -> int:
    """Create the blank solo sheet once. Nothing here writes a label or runs the model."""
    revision, directory, criteria = solo_context(args)
    records = read_records(args.data_dir / "work" / "records.jsonl")
    v1, v2 = frozen_assignments(args, 1), frozen_assignments(args, 2)
    keys = [json.loads((args.data_dir / d / "answer_key.json").read_text())
            for d in ("review", "review_pilot")]  # fmt: skip
    if (directory / solo.SHEET).exists() and solo.sheet_has_annotations(directory):
        items, _ = solo.select_solo(records, v1, v2, keys, args.seed, revision.number)
        planned = {i.item_id for i in items}
        existing = set(json.loads((directory / solo.KEY).read_text()))
        if (
            planned != existing
            or solo.sha256_file(criteria)
            != json.loads((directory / solo.META).read_text())["criteria_sha256"]
        ):
            raise BuildError(
                "Labels exist and the sample or criteria would change; not overwriting"
            )
        print(f"solo sheet already has labels ({len(existing)} rows); left unchanged")
        return 0
    meta = solo.build_solo(records, v1, v2, keys, criteria, directory, args.seed, revision.number)
    print(f"solo sheet: {meta['rows']} rows ({meta['items_by_kind']})")
    print(f"strata: {meta['items_by_stratum']}")
    print(f"sheet: {directory / solo.SHEET} (blank; only you write labels)")
    return 0


class LazyScorer:
    """Loads the verified pinned model on first use; any problem is a refusal, never a score."""

    def __init__(self) -> None:
        self.candidate = None
        self.classifier = None

    def info(self) -> dict:
        from pretrained.candidates import selected

        c = selected()
        return {"candidate": c.key, "repo": c.repo, "revision": c.revision,
                "weights_sha256": c.weights.sha256, "device": "cpu", "offline": True}  # fmt: skip

    def __call__(self, texts: list[str]) -> list[list[float]]:
        try:
            from pretrained.candidates import selected
            from pretrained.inference import ModelUnavailable, load_classifier, predict
        except ImportError:
            raise solo.SoloError(
                "The pretrained group is not installed (torch, transformers)"
            ) from None
        if self.classifier is None:
            self.candidate = selected()
            try:
                self.classifier = load_classifier(self.candidate)
            except ModelUnavailable as error:
                raise solo.SoloError(f"The pretrained model is unavailable: {error}") from None
        assert self.candidate is not None
        if tuple(self.candidate.labels) != solo.MODEL_LABELS:
            raise solo.SoloError("The model's label order differs from the registered order")
        out: list[list[float]] = []
        for start in range(0, len(texts), 16):
            for result in predict(self.classifier, self.candidate, texts[start : start + 16]):
                if result.status != "ok" or result.probabilities is None:
                    raise solo.SoloError("The model returned no result; nothing was scored")
                out.append([result.probabilities[label] for label in solo.MODEL_LABELS])
        return out


def cmd_solo_preflight(args: argparse.Namespace) -> int:
    """Read-only: counts and PASS / FAIL / NOT EVALUATED only. No model, no text, no IDs."""
    _, directory, criteria_path = solo_context(args)
    by_id = {r.record_id: r for r in read_records(args.data_dir / "work" / "records.jsonl")}
    checks = solo_preflight.preflight(
        directory, criteria_path, lambda record_id: review.display_text(by_id[record_id].text)
    )
    for check in checks:
        print(f"{check.status:14} {check.detail}")
    print(solo_preflight.summary_line(checks))
    return 0 if solo_preflight.ready(checks) else 3


def cmd_solo_evaluate(args: argparse.Namespace) -> int:
    revision, directory, criteria_path = solo_context(args)
    status_path = args.reports_dir / revision.status_file
    key, meta, criteria, problems = solo.load_bundle(directory, criteria_path)
    labels, progress = solo.read_labels(directory, key)
    done = len(labels) / len(key) >= criteria["completeness"]["min_labeled_share"]
    if problems or progress["problems"] or not done:
        status = {"status": "INCOMPLETE", "progress": progress, "integrity_problems": problems,
                  "note": "Nothing was scored; no model output exists yet."}  # fmt: skip
        write_json(status_path, status)
        print(f"Solo evaluation: INCOMPLETE ({progress['labeled']}/{progress['rows']} labeled)")
        for text in problems + progress["problems"]:
            print(f"  {text}")
        return 3
    by_id = {r.record_id: r for r in read_records(args.data_dir / "work" / "records.jsonl")}
    raw = {i: by_id[e["record_id"]].text for i, e in key.items() if e["kind"] != "repeat"}
    shown = {i: review.display_text(t) for i, t in raw.items()}
    scorer = LazyScorer()
    try:
        report = solo.evaluate_solo(directory, criteria_path, scorer, shown, raw, scorer.info())
    except solo.SoloError as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 4
    write_json(status_path, report)
    decision = report["decision"]
    print(f"Solo evaluation: {report['status']} - {decision['meaning']}")
    fraud = report["collected"]["per_class_one_vs_rest"]["fraud"]
    print(f"  fraud recall {fraud['recall']['rate']} {fraud['recall']['wilson95']}, "
          f"precision {fraud['precision']['rate']} {fraud['precision']['wilson95']}")  # fmt: skip
    for check in decision["go_checks"]:
        print(f"  {'ok  ' if check['passed'] else 'FAIL'} {check['check']}: {check['value']} "
              f"(limit {check['threshold']})")  # fmt: skip
    for line in decision["no_go_rules_fired"] + decision["caps"]:
        print(f"  note: {line}")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    """Create a proposed split version (2 or later) beside v1. v1 is never rewritten."""
    if args.version not in VERSIONS or args.version == 1:
        raise BuildError("Only a registered split version above 1 can be created here")
    spec, previous = VERSIONS[args.version], VERSIONS[args.version - 1]
    records_path = args.data_dir / "work" / "records.jsonl"
    v1_meta = json.loads((args.meta_dir / VERSIONS[1].meta_name).read_text())
    if file_sha256(records_path) != v1_meta["inputs"]["records_sha256"]:
        raise BuildError("The record store differs from the one v1 was built from")
    v1_assignments = VERSIONS[1].assignments(args.data_dir)
    v1_before = file_sha256(v1_assignments)
    if v1_before != v1_meta["assignments_sha256"]:
        raise BuildError("The v1 assignment file no longer matches its frozen metadata")
    records = read_records(records_path)
    infos = build_cluster_infos(records, assign_clusters(records, spec.threshold))
    cluster_split = assign_splits(infos, args.seed, DEFAULT_PROPORTIONS)
    rows = record_assignments(records, infos, cluster_split)
    spec.work_dir(args.data_dir).mkdir(parents=True, exist_ok=True)
    clusters_sha = write_clusters(spec.clusters(args.data_dir), infos)
    assignments_sha = write_assignments(spec.assignments(args.data_dir), rows)
    items = pair_review.unique_texts(records, rows)
    crossing, _ = pair_review.cross_split_pairs(items, min(SPLIT_LEAKAGE_LEVELS))
    report = split_report.build_report(
        records, infos, cluster_split, rows, read_assignments(previous.assignments(args.data_dir)),
        items, crossing, SPLIT_LEAKAGE_LEVELS, spec.threshold,
    )  # fmt: skip
    if file_sha256(v1_assignments) != v1_before:
        raise BuildError("v1 changed while v2 was built")  # defensive: nothing here writes v1
    counts = report["distribution"]["records_by_split"]
    meta = {
        "split_version": spec.version,
        "status": "proposed" if report["all_checks_passed"] else "proposed_failed_checks",
        "owner_decision": (
            "5 November 2026: creating a proposed sms_split.v2 at similarity threshold 0.4 is "
            "approved, subject to final distribution and leakage checks; v1 and its metadata are "
            "preserved. Adoption for M4.3 awaits the owner's manual review."
        ),
        "supersedes_for_evaluation_if_adopted": 1,
        "v1_preserved": {"meta": VERSIONS[1].meta_name, "assignments_sha256": v1_before},
        "algorithm_version": SPLIT_ALGORITHM_VERSION,
        "seed": args.seed,
        "proportions": DEFAULT_PROPORTIONS,
        "grouping": spec.grouping,
        "cluster_jaccard_threshold": spec.threshold,
        "manifest": v1_meta["manifest"],
        "inputs": {**v1_meta["inputs"], "clusters_sha256": clusters_sha},
        "assignments_sha256": assignments_sha,
        "counts": {s: {"records": counts[s]} for s in SPLITS},
        "checks_passed": report["all_checks_passed"],
        "evaluation_boundary": (
            "The threshold was chosen from label-free similarity statistics and hand checks of "
            "train/validation pairs only. No model exists, no score was computed, and no test "
            "text was displayed. The test split is read only through HeldOutGuard for a logged "
            "final evaluation."
        ),
        "real_world_test_excludes_synthetic": True,
    }
    write_json(args.meta_dir / spec.meta_name, meta)
    write_json(args.reports_dir / spec.report_name, report)
    write_registry(args.meta_dir)
    failed = [c["check"] for c in report["checks"] if not c["passed"]]
    print(f"split v{spec.version} at {spec.threshold}: {meta['status']}; records {counts}")
    for name in failed:
        print(f"  FAILED: {name}")
    return 0 if not failed else 4


def write_registry(meta_dir: Path) -> None:
    """Index of split versions and their state; written from the version metadata files."""
    entries = []
    for number, spec in sorted(VERSIONS.items()):
        path = meta_dir / spec.meta_name
        if not path.exists():
            continue
        meta = json.loads(path.read_text())
        entries.append({
            "version": number,
            "meta": spec.meta_name,
            "threshold": spec.threshold,
            "assignments_sha256": meta["assignments_sha256"],
            "status": meta.get("status", "frozen"),
        })  # fmt: skip
    write_json(meta_dir / "sms_splits.json", {
        "versions": entries,
        "rule": "A split version is never edited. The test split of an adopted version is read "
                "only through HeldOutGuard; once a model has been evaluated on it, it cannot be "
                "replaced.",
    })  # fmt: skip


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sms_prep", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    names = ("acquire", "verify", "build", "audit", "pairs", "split", "pilot", "pilot-audit",
             "solo-prepare", "solo-preflight", "solo-evaluate")  # fmt: skip
    for name in names:
        command = sub.add_parser(name)
        command.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
        command.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        command.add_argument("--reports-dir", type=Path, default=REPORTS)
        command.add_argument("--meta-dir", type=Path, default=MANIFESTS)
        if name == "pairs":
            command.add_argument("--threshold", type=float, default=0.6)
            command.add_argument("--dry-run", type=float, nargs="*", default=[0.6, 0.5])
            command.add_argument("--sample", type=int, default=0, help="pairs per similarity band")
            command.add_argument("--sample-seed", type=int, default=20261106)
        if name == "pilot":
            command.add_argument("--seed", type=int, default=DEFAULT_SEED)
        if name.startswith("solo-"):
            command.add_argument("--revision", type=int, choices=sorted(solo.REVISIONS),
                                 default=solo.CURRENT_REVISION)  # fmt: skip
            command.add_argument("--criteria", type=Path, default=None)
        if name == "solo-prepare":
            command.add_argument("--seed", type=int, default=solo.SOLO_SEED)
        if name == "split":
            command.add_argument("--version", type=int, default=2)
            command.add_argument("--seed", type=int, default=DEFAULT_SEED)
        if name == "build":
            command.add_argument("--seed", type=int, default=DEFAULT_SEED)
            command.add_argument("--per-class", type=int, default=review.DEFAULT_PER_CLASS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "acquire": cmd_acquire,
        "verify": cmd_verify,
        "build": cmd_build,
        "audit": cmd_audit,
        "pairs": cmd_pairs,
        "split": cmd_split,
        "pilot": cmd_pilot,
        "pilot-audit": cmd_pilot_audit,
        "solo-prepare": cmd_solo_prepare,
        "solo-preflight": cmd_solo_preflight,
        "solo-evaluate": cmd_solo_evaluate,
    }
    try:
        return handlers[args.command](args)
    except (AcquisitionError, BuildError, solo.SoloError, OSError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
