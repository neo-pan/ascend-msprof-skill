#!/usr/bin/env python3
"""Command adapter for Ascend msprof / msprof op analysis."""
from __future__ import annotations

import argparse
from pathlib import Path

from .evidence_model import *  # noqa: F403
from . import evidence_model


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args(argv)

    artifacts = evidence_model.write_evidence_model(args.run_dir.resolve())
    print(f"wrote {artifacts.summary_path}")
    print(f"wrote {artifacts.raw_artifact_index_path}")
    print(f"wrote {artifacts.key_metrics_path}")


if __name__ == "__main__":
    main()
