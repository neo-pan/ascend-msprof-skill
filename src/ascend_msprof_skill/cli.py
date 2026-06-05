"""Command dispatcher for Ascend msprof profiling helpers."""
from __future__ import annotations

import argparse
from importlib import resources
from pathlib import Path
from typing import Callable

from . import (
    analyze_msprof_outputs,
    collect_tilelang_context,
    compare_runs,
    extract_simulator_hotspots,
    generate_provenance,
    generate_report,
    plot_timeline,
    prepare_tilelang_profile_run,
    summarize_candidate,
)

CommandMain = Callable[[list[str] | None], int | None]


COMMANDS: dict[str, tuple[str, CommandMain]] = {
    "analyze": ("Analyze CANN msprof outputs and write analysis artifacts.", analyze_msprof_outputs.main),
    "provenance": ("Generate run provenance from command and environment logs.", generate_provenance.main),
    "report": ("Generate an evidence-cited REPORT.md.", generate_report.main),
    "timeline": ("Render a text timeline from msprof timeline JSON.", plot_timeline.main),
    "sim-hotspots": ("Extract simulator source/instruction hotspots.", extract_simulator_hotspots.main),
    "compare": ("Compare baseline and candidate profiling runs.", compare_runs.main),
    "collect-tilelang": ("Collect TileLang workload context for a run.", collect_tilelang_context.main),
    "prepare-tilelang": ("Prepare a TileLang profiling run from existing artifacts.", prepare_tilelang_profile_run.main),
    "summarize-candidate": ("Summarize candidate profiling evidence and verdict.", summarize_candidate.main),
}


def skill_path() -> Path:
    return Path(str(resources.files(__package__).joinpath("skill")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ascend-msprof")
    parser.add_argument("--version", action="version", version="ascend-msprof-skill 0.1.0")
    subparsers = parser.add_subparsers(dest="command")

    for name, (help_text, _main) in COMMANDS.items():
        subparsers.add_parser(name, help=help_text, add_help=False)

    skill_parser = subparsers.add_parser("skill", help="Inspect packaged Codex skill resources.")
    skill_subparsers = skill_parser.add_subparsers(dest="skill_command")
    skill_subparsers.add_parser("path", help="Print the packaged skill bundle path.")

    args, rest = parser.parse_known_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "skill":
        if args.skill_command == "path":
            print(skill_path())
            return 0
        skill_parser.print_help()
        return 0

    command = COMMANDS[args.command][1]
    result = command(rest)
    return int(result or 0)
