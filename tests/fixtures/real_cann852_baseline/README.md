# CANN 8.5.2 native kernel baseline

Actual 2026-10-11 Ascend 910B2 collections with CANN toolkit 8.5.2.
Each workload has independent application, operator PipeUtilization, and
operator Default segments. These fixtures validate those collection formats,
target/launch binding, provenance, analysis, and report generation. They do
not certify simulator, instruction sampling, or natural-runtime speedup.

`vector_basic`, `cube_memory_detail`, and `vector_source` retain separate
focused operator collections using BasicInfo, Default,MemoryDetail, and
Default,Source respectively. BasicInfo emits only OpBasicInfo.csv.
MemoryDetail exposes numeric AIC MTE1/MTE2 active bandwidth where the same
columns in Default were NA; NA is not zero. Source retains ordinary PMU
CSVs, while its source mapping/cache/timeline products remain unparsed.
Successful collection and a binary inventory do not prove source hotspots.

All retained CSV bytes, headers, numeric values, and rows are unchanged.
Profiler directory names and timestamped application CSV filenames are
normalized. The `origin.json` in each run records original and retained
SHA-256 values for every copied artifact, with transformation descriptions.
Omitted binary and Source mapping products also have source hashes and sizes
in the origin inventory; their full original files remain local run artifacts.

Commands, process results, caller target context, workflow metadata, and
same-collection environment receipts are retained. Host application/output
paths become relative placeholders; the toolkit uses `/opt/ascend/toolkit`.
Hardware serial/MAC lines are omitted and PCI addresses redacted. These
placeholders are not runnable harnesses. Physical NPU IDs and profiler device
IDs retain their original domains; the fixture does not infer their mapping.

Unlike the earlier workload-pair fixture, toolkit install metadata was
captured during this collection. There is no retroactive version supplement
and no rewrite of historical 8.3 fixture data. Driver/firmware receipts also
come from this collection; an unavailable board probe remains unavailable.

The unrequested, empty `biu_perf.db` emitted by normal application profiling
is retained byte-for-byte to guard against a false instruction-sampling
failure. The current helper closes explicit device instruction sampling and
retains any historical BIU files as raw audit inventory only.
Vector metric CSVs retain 48 rows; the mixed Cube kernel retains 72 rows
(24 Cube and 48 Vector lanes). Row counts are observations of these launches.

Other profiler binary databases, full stdout, timelines, executable harnesses, and
generated analysis are omitted. Tests regenerate analysis from the retained
raw files; the absence of these omitted products does not indicate a failure
of the original collection.
