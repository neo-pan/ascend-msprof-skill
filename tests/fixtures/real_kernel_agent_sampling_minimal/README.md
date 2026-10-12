# Kernel-agent sampling context regression

Retained from the 2026-10-10 DFT latency20 profile. All 23 timestamped
OpBasicInfo CSVs, launch 0 PipeUtilization CSV, and caller profile_context.json
are byte-for-byte originals. origin.json records their original relative paths
and SHA-256 values. Only the command receipt replaces the absolute run path
with a relative placeholder; it is an audit receipt, not a runnable harness.

The caller records 23 captured program launches and skips the first 3 for
Executor timing. The selected PMU artifact is deliberately from launch 0,
which is outside that declared timing subset. Sampling context must accompany
its observations; the helper must not filter those observations or claim a
validated steady-state benchmark.

Only one of 23 PipeUtilization artifacts is retained; arithmetic files, other
PMU families, binaries, source, environment and timing reports are omitted.
This preserves observed launch-count coverage but intentionally incomplete
metric coverage. It is not complete original-run timing or environment evidence.
No new collection or retrospective environment claim was made for this fixture.
