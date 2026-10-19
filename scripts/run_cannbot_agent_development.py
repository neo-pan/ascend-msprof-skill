#!/usr/bin/env python3
"""Run the caller's existing no-NPU transport canary with pinned code and skill.

This is development validation, not an Agent acceptance result. Load the caller's
direnv before invocation; credentials stay in its existing deployment boundary.
Use an external SIGINT wall timebox as documented by the caller replay harness.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caller-root', type=Path, required=True)
    parser.add_argument('--skill-repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--activity-timeout', type=float, default=120)
    args = parser.parse_args()
    caller, skill = args.caller_root.resolve(), args.skill_repo.resolve()
    imports = [str(caller / 'src'), str(skill / 'src')]
    sys.path[:0] = imports
    os.environ['PYTHONPATH'] = os.pathsep.join(imports)
    from kernel_agent.search_composition import DeploymentInputs

    deployment = DeploymentInputs.load(os.environ['KERNEL_AGENT_DEPLOYMENT'],
                                      environment=os.environ, project_root=caller)
    transport = deployment.codex_cli
    if deployment.runtime_kind != 'codex_cli' or transport is None:
        raise ValueError('The selected caller harness requires codex_cli')
    path = caller / 'scripts/search_behavior_validation/live_checks.py'
    spec = importlib.util.spec_from_file_location('cannbot_caller_replay', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.ReplayAdapter

    class CatalogReplayAdapter(original):
        def __init__(self, **kwargs):
            # The older replay entry omits this resolved production transport
            # field. Preserve it without changing model/provider or Executor.
            kwargs['model_catalog_json'] = transport.model_catalog_json
            super().__init__(**kwargs)

    module.ReplayAdapter = CatalogReplayAdapter
    code = module.main(['--root', str(caller), '--skill-root',
                        str(skill / 'skills/ascend-msprof-skill'),
                        '--output', str(args.output.resolve()), '--scenario', 'canary',
                        '--version', 'development-only', '--repeat', '1',
                        '--timeout', str(args.activity_timeout)])
    receipt = args.output / 'development-entry.json'
    receipt.write_text(json.dumps({'kind': 'development_transport_only',
        'model': transport.model, 'reasoning_effort': transport.reasoning_effort,
        'catalog_forwarded': transport.model_catalog_json is not None,
        'acceptance_trajectory': False, 'npu_measurements': False,
        'exit_code': code}, indent=2) + '\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
