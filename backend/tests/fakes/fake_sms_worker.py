"""TEST DOUBLE ONLY: a stand-in SMS worker that speaks the real protocol with scripted faults.

Never packaged or shipped, and never imported by `kavach`. It loads no model and its numbers are
fixed. Fault injection:
- Start-up mode comes from `--mode`.
- Per-request behavior comes from a `fake:` prefix in the (fictional) message text.

Start modes: ready (default), fatal, hang, crash, wrong_manifest, garbage, no_self_test.

Request directives: `fake:sleep:<seconds>`, `fake:crash`, `fake:garbage`, `fake:wrong_id`,
`fake:nan`, `fake:sum`, `fake:count`, `fake:extra`, `fake:error`, `fake:oversize`, `fake:stderr`
(echoes the text to stderr, as a leaky library might), `fake:stdout` (prints to fd 1),
`fake:rss:<mb>`, `fake:exit_after`.
"""

import argparse
import json
import os
import sys
import time

from kavach.models.protocol import HEADER, MAX_REQUEST_BYTES, encode_frame, read_frame

PROBABILITIES = [0.1, 0.2, 0.7]


def send(out, message: dict, limit: int = 1 << 20) -> None:
    out.write(encode_frame(message, limit))
    out.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="ready")
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--report", default="")  # test-only: where to write env keys and pid
    args = parser.parse_args()
    if args.report:
        with open(args.report, "w") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "pgid": os.getpgrp(),
                    "env": dict(os.environ),
                    "argv": sys.argv,
                },
                handle,
            )
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    stdin = sys.stdin.buffer
    ready = {
        "v": 1,
        "type": "ready",
        "manifest_sha256": args.manifest_sha256,
        "model_version": args.model_version,
        "self_test": "passed",
        "rss_mb": 50,
    }
    if args.mode == "fatal":
        send(out, {"v": 1, "type": "fatal", "code": "model_unverified"})
        return 3
    if args.mode == "hang":
        time.sleep(3600)
    if args.mode == "crash":
        return 1
    if args.mode == "garbage":
        out.write(b"\xff\xff\xff\xffnot a frame")
        return 1
    if args.mode == "wrong_manifest":
        ready["manifest_sha256"] = "0" * 64
    if args.mode == "no_self_test":
        ready["self_test"] = "skipped"
    send(out, ready)
    while True:
        message = read_frame(stdin, MAX_REQUEST_BYTES)
        if message is None:
            return 0
        text, request_id = message["text"], message["id"]
        result = {
            "v": 1,
            "type": "result",
            "id": request_id,
            "status": "ok",
            "probabilities": PROBABILITIES,
            "truncated": False,
            "duration_ms": 3,
            "rss_mb": 50,
        }
        if text.startswith("fake:sleep:"):
            time.sleep(float(text.split(":")[2].split()[0]))
        elif text.startswith("fake:crash"):
            os._exit(1)
        elif text.startswith("fake:garbage"):
            out.write(HEADER.pack(5) + b"{oops")
            continue
        elif text.startswith("fake:wrong_id"):
            result["id"] = "f" * 32
        elif text.startswith("fake:nan"):
            out.write(encode_frame(result, 1 << 20).replace(b"0.7", b"NaN"))
            continue
        elif text.startswith("fake:sum"):
            result["probabilities"] = [0.5, 0.5, 0.5]
        elif text.startswith("fake:count"):
            result["probabilities"] = [0.5, 0.5]
        elif text.startswith("fake:extra"):
            result["text"] = text
        elif text.startswith("fake:error"):
            result = {
                "v": 1,
                "type": "result",
                "id": request_id,
                "status": "error",
                "code": "internal_error",
            }
        elif text.startswith("fake:oversize"):
            result["padding"] = "x" * 8192
        elif text.startswith("fake:stderr"):
            sys.stderr.write(f"library warning while processing: {text}\n")
            sys.stderr.flush()
        elif text.startswith("fake:stdout"):
            print(f"stray print: {text}")
            sys.stdout.flush()
        elif text.startswith("fake:rss:"):
            result["rss_mb"] = int(text.split(":")[2].split()[0])
        send(out, result)
        if text.startswith("fake:exit_after"):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
