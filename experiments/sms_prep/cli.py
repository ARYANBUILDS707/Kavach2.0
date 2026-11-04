"""M4.2 command line (run from the experiments/ directory):

    python -m sms_prep acquire   [--data-dir DIR]   download + verify the approved datasets
    python -m sms_prep verify    [--data-dir DIR]   offline checksum check of stored files
    python -m sms_prep build     [--data-dir DIR]   records, clusters, review, splits, reports
    python -m sms_prep audit     [--data-dir DIR]   evaluate completed human review sheets

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
from sms_prep import review, synthetic
from sms_prep.acquire import AcquisitionError, acquire, specs_from_manifest, verify_local
from sms_prep.clusters import assign_clusters, build_cluster_infos, write_clusters
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
    synthetic_records,
    write_records,
)  # fmt: skip
from sms_prep.splits import (
    DEFAULT_PROPORTIONS,
    DEFAULT_SEED,
    SPLIT_ALGORITHM_VERSION,
    SPLITS,
    assign_splits,
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
    status = review.evaluate_audit(args.data_dir / "review")
    write_json(args.reports_dir / "label_audit_status.json", status)
    return status


def cmd_audit(args: argparse.Namespace) -> int:
    status = audit_status(args)
    progress = status["progress"]
    print(
        f"Label approval: {status['label_approval']} "
        f"({progress['reviewer_a_completed']}/{progress['items']} reviewer A, "
        f"{progress['reviewer_b_completed']}/{progress['items']} reviewer B, "
        f"{progress['disagreements_unadjudicated']} unadjudicated disagreements)"
    )
    for klass, entry in status["classes"].items():
        print(f"  {klass}: {entry['status']} (sampled {entry['sampled']})")
    return 0 if status["label_approval"] != "BLOCKED" else 3


def ensure_bundle(directory: Path, records, infos, seed: int, per_class: int) -> dict:
    """Create the review bundle once; never overwrite sheets that may hold annotations."""
    key_path = directory / "answer_key.json"
    if key_path.exists():
        existing = set(json.loads(key_path.read_text()))
        planned = {i.item_id for i in review.select_items(records, infos, seed, per_class)}
        if existing != planned:
            raise BuildError("A review bundle with different items already exists; not overwriting")
        return json.loads((directory / "bundle_meta.json").read_text())
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sms_prep", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("acquire", "verify", "build", "audit"):
        command = sub.add_parser(name)
        command.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
        command.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        command.add_argument("--reports-dir", type=Path, default=REPORTS)
        command.add_argument("--meta-dir", type=Path, default=MANIFESTS)
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
    }
    try:
        return handlers[args.command](args)
    except (AcquisitionError, BuildError, OSError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
