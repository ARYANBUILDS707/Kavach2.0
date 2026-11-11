"""Controlled synthetic simulator (M3.3).

    python -m kavach.simulator list
    python -m kavach.simulator run --all --dry-run [--run-id ID] [--seed N]
    python -m kavach.simulator run --scenario S05 [--scenario S07] [--run-id ID] [--seed N]
        [--base-url http://127.0.0.1:8000] [--max-per-minute 20] [--key-stdin] [--json]

Submits through the ordinary event endpoints with an ingestion key for source `simulator`
(`python -m kavach.cli key create --source simulator ...`). The key is read from the
KAVACH_SIMULATOR_API_KEY environment variable or, with --key-stdin, from one line of standard
input; it is never an argument and never printed. Only loopback targets are accepted.

Exit codes: 0 every scenario passed; 1 a scenario failed or the run was aborted;
2 refused before sending anything (bad arguments, target or key).
"""

import argparse
import json
import os
import secrets
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import TextIO

from kavach.core.clock import utc_now
from kavach.simulator.catalog import ScenarioCatalog, load_catalog
from kavach.simulator.runner import (
    DEFAULT_PER_MINUTE,
    DEFAULT_TARGET,
    LoopbackTransport,
    Pacer,
    Runner,
    SimulatorRefused,
    Transport,
    describe_plan,
    dry_run,
    report_dict,
    report_lines,
    validate_target,
)

KEY_VARIABLE = "KAVACH_SIMULATOR_API_KEY"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kavach.simulator", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the catalog scenarios")
    run = commands.add_parser("run", help="run scenarios against a local backend")
    which = run.add_mutually_exclusive_group(required=True)
    which.add_argument("--all", action="store_true", help="every scenario in catalog order")
    which.add_argument("--scenario", action="append", help="scenario ID (repeatable)")
    run.add_argument("--run-id", help="1-16 lower-case letters/digits (default: random)")
    run.add_argument("--seed", type=int, default=0, help="derives subscriber tokens (default 0)")
    run.add_argument("--dry-run", action="store_true", help="print the plan; send nothing")
    run.add_argument("--base-url", default=DEFAULT_TARGET, help="loopback http(s) URL only")
    run.add_argument("--max-per-minute", type=int, default=DEFAULT_PER_MINUTE)
    run.add_argument("--key-stdin", action="store_true", help="read the API key from stdin")
    run.add_argument("--json", action="store_true", help="machine-readable report")
    return parser


def selected(catalog: ScenarioCatalog, args: argparse.Namespace) -> list[str]:
    known = [scenario.id for scenario in catalog.scenarios]
    if args.all:
        return known
    unknown = sorted(set(args.scenario) - set(known))
    if unknown:
        raise SimulatorRefused(f"Unknown scenario: {', '.join(unknown)}")
    return list(dict.fromkeys(args.scenario))


def read_key(args: argparse.Namespace, stdin: TextIO, environ: Mapping[str, str]) -> str:
    key = stdin.readline().strip() if args.key_stdin else environ.get(KEY_VARIABLE, "").strip()
    if not key:
        raise SimulatorRefused(f"Provide the API key in {KEY_VARIABLE} or with --key-stdin")
    return key


def list_scenarios(catalog: ScenarioCatalog, out: TextIO) -> None:
    print(
        f"Catalog version {catalog.catalog_version}, source {catalog.source} (synthetic only)",
        file=out,
    )
    for scenario in catalog.scenarios:
        provisional = f" [provisional: {', '.join(scenario.provisional)}]"
        count = len(scenario.steps)
        print(
            f"{scenario.id} v{scenario.version}  {scenario.name}  ({count} "
            f"step{'s' if count != 1 else ''}, truth={scenario.truth})"
            f"{provisional if scenario.provisional else ''}",
            file=out,
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
    environ: Mapping[str, str] = os.environ,
    clock: Callable[[], datetime] = utc_now,
    transport: Transport | None = None,
    pacer: Pacer | None = None,
) -> int:
    """`transport` and `pacer` are injectable for tests; the CLI builds the loopback ones."""
    args = build_parser().parse_args(argv)
    catalog = load_catalog()
    if args.command == "list":
        list_scenarios(catalog, out)
        return 0
    run_id = args.run_id or secrets.token_hex(4)
    try:
        scenario_ids = selected(catalog, args)
        if args.dry_run:
            report, planned = dry_run(
                catalog, scenario_ids, seed=args.seed, run_id=run_id, anchor=clock()
            )
            if args.json:
                print(json.dumps(report_dict(report), indent=2), file=out)
            else:
                print("\n".join(report_lines(report) + describe_plan(planned)), file=out)
            return 0
        target = validate_target(args.base_url)
        runner = Runner(
            catalog,
            transport or LoopbackTransport(target),
            read_key(args, stdin, environ),
            clock=clock,
            pacer=pacer or Pacer(args.max_per_minute),
            seed=args.seed,
            run_id=run_id,
        )
        report = runner.run(scenario_ids)
    except SimulatorRefused as refused:
        print(f"Refused: {refused}", file=err)
        return 2
    if args.json:
        print(json.dumps(report_dict(report), indent=2), file=out)
    else:
        print("\n".join(report_lines(report)), file=out)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
