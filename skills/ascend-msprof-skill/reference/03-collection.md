# Profile Collection Commands

## Contents

- [Application-Level Profile](#application-level-profile)
- [Operator-Level Profile](#operator-level-profile)
- [Simulator Profile](#simulator-profile)

The current environment baseline is CANN `8.5.2` on Ascend 910B2.
The [capability matrix](15-cann852-capabilities.md) distinguishes accepted
commands, usable live outputs and parsed fields. Historical CANN
`8.3.0.2.220:8.3.RC2` fixtures remain versioned regression evidence. Check
installed `msprof --help`, `msprof op --help`, and `msprof op simulator --help`
for each new environment; a listed option does not establish successful capture.

## Bind The Application Device

Resolve and reserve one runtime logical device before launching the profiler.
The [official CANN 8.5.0 environment-variable reference](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/maintenref/envvar/envref_07_0028.html)
excludes Profiling use with `ASCEND_RT_VISIBLE_DEVICES`. This is adjacent-version
guidance; an exact 8.5.2 exception has not been verified. Prepare a separate
profiling child environment without that variable after resolving the original
target. Keep the caller's reservation environment and natural benchmark unchanged.

The application must select the same logical device explicitly before device
allocation or stream creation: `torch.npu.set_device(N)` and `npu:N` for a
framework harness, or `aclrtSetDevice(N)` with matching reset for native ACL.
Removing a visibility pin while retaining a default-device application can
change the target. The profiler's `--devices` filter does not select the
application device. Reject ambiguous bindings instead of guessing a card.
Logical IDs and host physical-card IDs need separately sourced mapping evidence.
On the first collection using a new launch path, check the application's chosen
device against profiler device identity within that mapping.

Before running the examples, start from an existing application path and make
the run directory absolute so recorded profiler commands preserve run-internal
`reports/...` paths in provenance:

```bash
PROFILE_RUN_DIR=profile/<run_name>
APPLICATION=path/to/run.sh
mkdir -p "$PROFILE_RUN_DIR"/{reports,logs,analysis}
PROFILE_RUN_DIR=$(realpath "$PROFILE_RUN_DIR")
APPLICATION=$(realpath "$APPLICATION")
```

For manual collection, capture the current environment once before invoking
msprof:

```bash
ascend-msprof provenance --collect-env --run-dir "$PROFILE_RUN_DIR"
```

`profile-harness` captures it automatically before its first profiler call;
do not prepopulate its fresh run's logs. Caller input registrations created
by `collect-tilelang` or `collect-benchmark` may precede collection; previous
profiler outputs and derived analysis still require a new run. Plain `provenance --run-dir ...`
only rebuilds from saved logs and does not query today's installation.
Saved logs are never overwritten by environment capture.

Device environment capture gives each `npu-smi` query 60 seconds. After a
successful inventory query, it queries visible physical cards for board
identity with up to four concurrent calls. This environment budget is separate
from a profiler segment timeout; four cards can require roughly 120 seconds in
total. `logs/npu_smi_info.receipt.json` and
`logs/npu_smi_board_<physical-id>.receipt.json` retain command, elapsed time,
status and stdout/stderr paths. Timeout, missing tool and partial identity
remain explicit; valid profiler evidence is preserved.

Board fields retain their physical-card and source scope, including driver
Software Version, Firmware Version and Compatibility. Inventory chip/bus IDs
help establish mappings; `ASCEND_VISIBLE_DEVICES` alone does not prove a
physical-to-runtime mapping. An existing inventory snapshot is historical:
missing board fields are not filled by querying today's host.

If bounded management queries have timed out and device mapping or health is
unresolved, preserve their receipts and resolve the environment before a new
live acceptance run. Do not poll or extend timeouts as a substitute for repair.
The [official compatibility table](https://www.hiascend.com/llms-content/document/detail/canncommercial/canncommercial_900_releasenote_release-notes_md.md)
includes CANN 8.5.2 with HDK 25.5.X; this does not certify an exact installed
driver/firmware package pair. Record package manifests when available and keep
unverified pairing fields unknown.

The helper records the resolved msprof path and installation root in
`logs/msprof_environment.json`. It preserves `version.cfg` as
`logs/cann_version.cfg` and, for the verified toolkit installation layout,
`ascend_toolkit_install.info` as `logs/toolkit_install.info`. The latter's exact
`package_name=Ascend-cann-toolkit` and `version` keys provide a fallback when
running-version fields are absent, including an empty/comment-only cfg.
Version evidence cites the actual artifact and key. Component-version or
installation-root conflicts block comparison; short and detailed versions
are not assumed equivalent. Toolkit metadata does not prove the loaded
runtime library's version. A historical run without saved evidence remains
missing; separately supplied historical evidence must retain its origin.

The official [package version query guide](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/850alpha001/softwareinst/instg/instg_0064.html)
documents the toolkit `version` field. The install-info fallback has local
8.5.2 fixture coverage; installation identity alone does not validate every
profiler schema or prove the loaded runtime version.

If a benchmark skill or calling agent supplies a profile harness manifest,
the generic wrapper can run the app/op collection against that supplied
application:

```bash
ascend-msprof profile-harness \
    --run-dir "$PROFILE_RUN_DIR" \
    --manifest "$PROFILE_RUN_DIR/harness/profile_harness.json" \
    --verify-json "$PROFILE_RUN_DIR/context/verify.json"
```

The helper supports `--preset triage`, `--preset default-depth`, and
`--preset full`. Omitting `--preset` uses `triage`: app-level `msprof` plus
`msprof op --aic-metrics=PipeUtilization`. `default-depth` adds a separate
Default metric follow-up segment, and `full` currently adds that same Default
segment plus optional simulator collection only when `--simulator` is supplied.

After a triage run, the helper can append the supported Default follow-up when
`analysis/summary.json` lists `collect_default_metric_followup` and the current
question needs its missing fields:

```bash
ascend-msprof profile-harness \
    --run-dir "$PROFILE_RUN_DIR" \
    --follow-next-actions \
    --continue-from-summary \
    --follow-action collect_default_metric_followup
```

This continue mode reuses `analysis/profile_harness_run.json`, refuses to
overwrite existing follow-up output, and records run/skipped/blocked actions in
that workflow metadata, including the executed action's `necessity` and
`unlocks_claims`. Only blocking or explicitly selected actions execute.
Before collecting, it checks the recorded application fingerprint in
`analysis/profile_context.json` (`sources.application.sha256`, optional
`sources.implementation[]` when the manifest declares kernel/source paths, and
any run-local manifest/verify digests) against the live files, then checks the
current resolved msprof path, toolkit root, and version fields against the
saved environment receipt and snapshots. If the implementation fingerprint,
CANN environment, or original evidence changed or is missing, start a new run.
Do not merge follow-up segments from a mutated application into the prior run;
keep still-valid raw observations, and treat the mismatch as a comparability
limit rather than an optimization failure.
Use `--follow-target-json <target.json>` for a count-bounded subset of the
persisted target. Its selector must match only the declared subset, not another
program target. The helper records focused Default output under a
deterministic separate segment/path, so the canonical complete-program path
remains collectable later; focused coverage remains local to its segment.
When CANN writes that single-target focused segment or an exact single-launch
complete-program follow-up as flat CSVs directly under one `OPPROF_*` root,
analysis treats it as one launch only when the persisted target expects exactly
one launch, exactly one parsed one-row `OpBasicInfo` names that target, and the
root is otherwise unambiguous.
Other recommended actions are recorded as skipped until the helper supports
safe automation for them.

Use `--summarize-candidate` on either the initial or continue command to write
`analysis/candidate_summary.json` and `.md` after analysis without recollection.
The JSON records the SHA-256 of the `analysis/summary.json` it consumed so
callers can reject stale candidate summaries after follow-up collection.

The wrapper profiles only the supplied manifest/application. It does not own
benchmark-specific harness rendering. `--verify-json` is optional caller
context and is written to `analysis/profile_context.json` for workload,
correctness, and timing context only; profiler diagnoses still cite `reports/`
artifacts and `analysis/summary.json`.
For a declared single-kernel or multi-launch target, include the collection and
coverage contract at the top level of the supplied manifest:

```json
{
  "application": "run_application.sh",
  "implementation": ["kernel.cpp"],
  "target": {
    "kernel_selector": "main_kernel*",
    "expected_launches": [
      {"name": "main_kernel", "count": 1}
    ]
  }
}
```

When the launched `application` is only a wrapper, list the real kernel or
source files in optional `implementation` (string or list). Continue collection
fingerprints those paths when present; when omitted, it still checks the
application file and any recorded run-local manifest/verify digests.
The helper validates this contract before invoking `msprof`, derives
`--launch-count` from the expected counts, and applies the selector, count,
`--warm-up=0`, and application replay behavior to onboard op and supported
Default follow-up collection. Continue mode reuses the persisted target and
does not reconstruct it from the summary. Existing `expected_kernel_name` and
`expected_kernel_names` metadata remains supported for identity only; it does
not change collection or enable count completeness.

The analyzer compares the declared names with the authoritative observed names
from the app `op_summary_*.csv` and per-launch `OpBasicInfo` records. For
TileLang-Ascend kernels, TileLang context implies
expected `main_kernel` by default unless the generated JIT source names a
different `__global__ __aicore__` entrypoint; `main_kernel_mix_aic` from
`msprof op` is treated as matching `main_kernel`.
`--simulator` is optional and disabled by default. Use it when source,
instruction, or pipeline attribution is needed; simulator collection can add
substantial runtime. If optional simulator collection fails, the wrapper records
the failure as a warning and continues analysis/report generation from app/op
artifacts.
Append `--simulator` to the `profile-harness` command for that optional
collection. Use `--simulator-timeout-s <seconds>` only with `--simulator`.

## Application-Level Profile

Use this first when you need operator ranking or host/runtime timeline:

```bash
MSPROF_APP_CMD=(
    msprof
    --output="$PROFILE_RUN_DIR/reports/app"
    --application="$APPLICATION"
    --runtime-api=on
    --task-time=on
    --ai-core=on
    --aic-metrics=PipeUtilization
    --type=text
    --summary-format=csv
)
printf "%q " "${MSPROF_APP_CMD[@]}" > "$PROFILE_RUN_DIR/logs/command_msprof.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof.txt"
"${MSPROF_APP_CMD[@]}"
```

Expected output normally includes a `PROF_*` directory with
`mindstudio_profiler_output/`. In CANN 8.5.2 help, the app-level flags above
are documented in `msprof --help`; cite the exact command and resulting
`PROF_*` files in the report.

## Operator-Level Profile

Use `msprof op` when the target is one Ascend C/custom operator and you need AI
Core metrics:

```bash
MSPROF_OP_CMD=(
    msprof
    op
    --output="$PROFILE_RUN_DIR/reports/op"
    --application="$APPLICATION"
    --aic-metrics=PipeUtilization
)
printf "%q " "${MSPROF_OP_CMD[@]}" > "$PROFILE_RUN_DIR/logs/command_msprof_op.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof_op.txt"
"${MSPROF_OP_CMD[@]}"
```

The CANN 8.5.2 `msprof op --help` output documents `--application` and
`--aic-metrics`. Record the selected metric set in the report.

Use `PipeUtilization` as the starter metric when the immediate question is
which AI Core pipe is active. For broader metric sets, first check the
installed `msprof op --help`: CANN 8.5.2 lists `Default`, `KernelScale`,
`ResourceConflictRatio`, `MemoryDetail`, `Source`, `BasicInfo`, `Occupancy`,
and `Roofline`. `PMSampling` belongs to the separate simulator metric set.
Use [field prerequisites and data origins](15-cann852-capabilities.md#field-prerequisites-and-data-origins)
for MemoryDetail and Source, and preserve the selected replay/warmup protocol.
Do not assume the helpers parse a newly selected metric output unless that
file is already listed in `data/output-files.yaml` or covered by a controlled
fixture. Some `msprof op` metric information can appear only in selected
profiler stdout rather than in a CSV or JSON artifact; the analyzer extracts
only stdout sections that already have controlled fixture coverage.

When the current question needs missing Default fields and
`analysis/summary.json` lists the supported follow-up,
collect it as a separate raw output segment in the same run:

```bash
MSPROF_FOLLOWUP_CMD=(
    msprof
    op
    --output="$PROFILE_RUN_DIR/reports/followups/collect_default_metric_followup"
    --application="$APPLICATION"
    --aic-metrics=Default
)
printf "%q " "${MSPROF_FOLLOWUP_CMD[@]}" \
    > "$PROFILE_RUN_DIR/logs/command_msprof_followup_collect_default_metric_followup.txt"
printf "\n" >> "$PROFILE_RUN_DIR/logs/command_msprof_followup_collect_default_metric_followup.txt"
"${MSPROF_FOLLOWUP_CMD[@]}"
```

The follow-up is part of the same run but a distinct raw output segment. It
must contain `OpBasicInfo.csv`, `PipeUtilization.csv`,
`ArithmeticUtilization.csv`, `Memory.csv`, `MemoryL0.csv`, `MemoryUB.csv`, and
`ResourceConflictRatio.csv`. Record the follow-up command under
`logs/command_msprof_followup_collect_default_metric_followup.txt` before
regenerating provenance, analysis, timeline, and report artifacts.
This canonical path is for complete-program collection. Use
`profile-harness --follow-target-json` for focused collection so the helper
assigns its separate segment and logs.

## Simulator Profile

Use optional simulator output for source-line, instruction, and pipeline
detail:

```bash
msprof op simulator --output="$PROFILE_RUN_DIR/reports/sim" \
    --application="$APPLICATION" \
    --aic-metrics=PipeUtilization
```

Simulator output can differ from on-device timing. Use it for attribution and
pipeline shape, not as the final elapsed-time source.

Simulator `--aic-metrics` choices are separate from onboard `msprof op`
choices. In the installed CANN 8.5.2 help, simulator metrics include
`PipeUtilization`, `ResourceConflictRatio`, and `PMSampling`, with
`PipeUtilization` required. Keep simulator analysis tied to the generated
simulator artifacts rather than carrying over onboard metric assumptions.

## Focused Pipeline Evidence

For instruction timelines, use the TimelineDetail or explicit simulation
`ascend-msprof profile-pipeline` routes in [pipeline evidence](14-pipeline-evidence.md).
Device instruction BIU collection is closed: `--mode sampled` returns 2
immediately, and historical BIU artifacts are raw audit only. Ordinary app/op
PMU and simulator PMSampling retain their existing support boundaries.
`ascend-msprof pipeline` exposes collection-stage diagnostics; `analyze` also
surfaces them automatically. `ascend-msprof timeline --svg` renders obtained
complete simulator intervals without merging trace clocks.

## Import Existing Natural Measurements

`ascend-msprof collect-benchmark --run-dir profile/<run> --benchmark-json caller.json`
imports the caller's top-level `assessment`, preserving its bytes and sources.
It creates only context/analysis artifacts and does not execute the benchmark.
TileLang `--benchmark-json` and harness `--verify-json` accept the same optional
record. See [the measurement contract](11-candidate-comparison-schema.md) for
single-case fields, conflicts and offline replay. New TileLang contexts use
schema 2; profile contexts use schema 5. Harness workflow metadata uses schema 4.

Use the caller's actual timer and synchronization semantics in the record.
[Official Ascend synchronization guidance](https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/850alpha001/appdevg/acldevg/aclcppdevg_000013.html)
distinguishes device completion from stream and event synchronization. This is
API context, not an expansion of this helper's profiler-version support.
For a framework caller, verify the implementation and version of its wrapper;
[Ascend PyTorch synchronization](https://github.com/Ascend/pytorch/blob/master/torch_npu/npu/utils.py)
waits for kernels in all streams of the selected device. A timer name alone
does not establish the measured scope or exclude compilation and allocation.
