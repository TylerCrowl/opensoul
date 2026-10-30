"""OpenSoul command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opensoul import __version__
from opensoul.character_pack import CharacterPack
from opensoul.consistency import (
    DEFAULT_SHEET_THRESHOLD,
    DEFAULT_THRESHOLD,
    filter_candidates,
    recommend_threshold,
    score_consistency,
)


def _cmd_score(args: argparse.Namespace) -> int:
    refs = list(args.ref) if args.ref else []
    if args.pack:
        pack = CharacterPack.load(args.pack)
        refs = pack.ref_images + refs
    if not refs:
        print("error: provide --ref and/or --pack", file=sys.stderr)
        return 2
    mode = args.mode
    threshold = args.threshold
    if threshold is None:
        threshold = recommend_threshold(args.backend, mode)
    result = score_consistency(
        args.candidate,
        refs,
        threshold=threshold,
        backend=args.backend,
        mode=mode,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        gate = "PASS" if result.passed else "REJECT"
        print(f"{gate}\tscore={result.score:.4f}\tthreshold={result.threshold:.4f}\t{result.detail}")
    return 0 if result.passed else 1


def _cmd_filter(args: argparse.Namespace) -> int:
    refs = list(args.ref) if args.ref else []
    if args.pack:
        pack = CharacterPack.load(args.pack)
        refs = pack.ref_images + refs
    if not refs:
        print("error: provide --ref and/or --pack", file=sys.stderr)
        return 2
    mode = args.mode
    threshold = args.threshold
    if threshold is None:
        threshold = recommend_threshold(args.backend, mode)
    kept = filter_candidates(
        args.candidates,
        refs,
        threshold=threshold,
        backend=args.backend,
        mode=mode,
    )
    rows = [
        {"path": str(p), **r.to_dict()}
        for p, r in kept
    ]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"PASS\t{row['score']:.4f}\t{row['path']}")
        print(f"# kept {len(rows)} / {len(args.candidates)}", file=sys.stderr)
    return 0


def _cmd_pack_init(args: argparse.Namespace) -> int:
    out = Path(args.out)
    pack = CharacterPack(
        name=args.name,
        prompt_lock=args.prompt_lock or "",
        seed=args.seed,
        ref_images=list(args.ref),
        notes=args.notes or "",
    )
    path = pack.save(out)
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="opensoul",
        description="OpenSoul — consistent-character toolkit (Comfy SDK + local open weights)",
    )
    p.add_argument("--version", action="version", version=f"opensoul {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="Score one candidate vs references / pack")
    s.add_argument("candidate", type=str)
    s.add_argument("--ref", action="append", default=[], help="Reference image (repeatable)")
    s.add_argument("--pack", type=str, help="Character pack directory")
    s.add_argument("--threshold", type=float, default=None)
    s.add_argument("--backend", choices=("patch", "clip"), default="patch")
    s.add_argument("--mode", choices=("mean", "sheet_max"), default="sheet_max")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_score)

    f = sub.add_parser("filter", help="Filter candidates that pass the consistency gate")
    f.add_argument("candidates", nargs="+")
    f.add_argument("--ref", action="append", default=[])
    f.add_argument("--pack", type=str)
    f.add_argument("--threshold", type=float, default=None)
    f.add_argument("--backend", choices=("patch", "clip"), default="patch")
    f.add_argument("--mode", choices=("mean", "sheet_max"), default="sheet_max")
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=_cmd_filter)

    pk = sub.add_parser("pack-init", help="Create a character pack directory")
    pk.add_argument("--name", required=True)
    pk.add_argument("--ref", action="append", required=True)
    pk.add_argument("--out", required=True)
    pk.add_argument("--prompt-lock", default="")
    pk.add_argument("--seed", type=int, default=42)
    pk.add_argument("--notes", default="")
    pk.set_defaults(func=_cmd_pack_init)

    info = sub.add_parser("info", help="Show defaults and SDK status")
    def _info(_args: argparse.Namespace) -> int:
        from opensoul.comfy_client import sdk_status
        print(json.dumps({
            "version": __version__,
            "default_threshold_mean": DEFAULT_THRESHOLD,
            "default_threshold_sheet_max": DEFAULT_SHEET_THRESHOLD,
            "sdk": sdk_status(),
        }, indent=2))
        return 0
    info.set_defaults(func=_info)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
