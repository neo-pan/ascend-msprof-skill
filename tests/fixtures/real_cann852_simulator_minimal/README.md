# Positive CANN 8.5.2 standalone AIV simulator fixture

Captured on Ascend 910B2 with CANN 8.5.2 on 2026-10-11 using
`msprof op simulator --soc-version=Ascend910B2
--aic-metrics=PipeUtilization,ResourceConflictRatio --core-id=0` and one
selected `biu_native_vector_kernel` launch. The standalone native kernel
uses a 32-iteration Add loop and AIV_ONLY task type. Retained stdout identifies
the selected kernel, records correctness `exact_pass`, and reports completion.

This fixture retains the complete root trace (802 X records, including 689
positive durations), 76 source rows, 176 instruction rows, and the actual
kernel source with its original line numbers. There are 32 VADD trace events
whose source stack includes kernel.cpp:37, which is the Add statement.
The instruction CSV records VADD call_count=32, cycles=1728 and
running_time(us)=0.96; the source row at line 37 has cycles=6272 and
running_time(us)=1.07. These are different attribution scopes, not additive
elapsed-time measurements. Trace time units are microseconds even though
the viewer displayTimeUnit is ns.

Only source/toolkit/TileLang include/application/output paths and identifying hardware fields
are sanitized. Trace event order, numeric tokens, addresses, columns and CSV
row order are preserved. The caller's original source is copied byte-for-byte
into `kernel/kernel.cpp`; source references are rewritten there for portable
inline context. TileLang include references use `/opt/tilelang-ascend`.
The live run's source is outside its run directory, so the
helper correctly labels its inline context `outside_run_dir`; the actual
line mapping was separately verified against the source hash and line 37.

Every retained artifact has original/fixture hashes and transformation notes
in origin.json. The duplicate per-core trace, binary dump and visualization
are omitted with source hashes and sizes. No binary-presence inference or
fabricated timeline interval is used. This demonstrates the selected core's
simulator path; it does not establish all-core coverage, real-device overlap,
natural-performance speedup, or framework/DFT simulator compatibility.
