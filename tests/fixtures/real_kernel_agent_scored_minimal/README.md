# Saved caller launch populations

Original CANN 8.5.2 / Ascend 910B2 `OpBasicInfo` and `PipeUtilization` CSVs,
plus `ArithmeticUtilization` for the DFT cases, from saved kernel-agent
Executor experiments:

- `dft23`: 2026-10-10 DFT candidate `dft-327f77fe07f1aaf4`, one kernel,
  23 captured program launches, skip the first 3 for the declared scored range.
- `multi23`: 2026-10-10 DFT candidate `dft-6c31c5332b7c69b8`, two kernels
  per program, 23 program launches each. Populations remain separate by kernel.
- `inverse8`: 2026-09-28 shifted Hermitian inverse A, attempt 01, 8 launches,
  skip the first 3. Historical target count=1 is intentionally reproduced by
  the test's caller declaration and remains a run-level coverage issue.

Each case's `origin.json` lists retained files and original-byte SHA-256.
No CSV cells are edited or truncated. Other metric families, source code,
opaque profiler products, hardware receipts and formal reports are omitted.
The tests create explicit sampling declarations in temporary runs; these are
test inputs and do not amend historical metadata or certify a benchmark.

Across-launch PMU medians describe one captured process per case. They are
neither independent process samples nor a program Task Duration score.
