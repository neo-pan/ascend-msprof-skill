# Ascend 910B Programming Context

Use this glossary when relating a recorded profiler field to Ascend C source.
Consult official CANN documentation for detailed programming and API semantics.

Ascend C custom operators separate host-side tiling/launch preparation from
device-side AI Core execution. Record the workload, tiling and blockDim used by
the measured run so its profiler observations can be associated with that source.

Common data-movement paths, not a complete product map:

```text
matrix: GM/L2 → MTE2 → L1 → MTE1 → L0A/L0B → Cube → L0C → Fixpipe
vector: GM/L2 → MTE2 → UB → Vector → UB → MTE3
```

| Concept | Context for reading profiler evidence |
|---|---|
| Cube | Matrix computation; retain the exact Cube time/ratio fields reported by the selected metric family. |
| Vector | Vector computation, including elementwise and reduction operations; interpret recorded instruction and pipe fields in the context of the workload. |
| Scalar | Address/control and scalar execution context; preserve raw Scalar fields instead of inferring a cause from their relative magnitude. |
| MTE / DataCopy | Data movement context; distinguish transfer fields from compute fields and retain the named memory level. |
| GM, UB, L1 and L0 | Distinct memory levels named in the profiler output; keep volume, bandwidth, usage, time and conflict fields separate. |
| AIC / AIV / block / `sub_block_id` | Distinct execution-unit and report identities; do not treat them as one count. Keep core class and mapping when comparing cells. |
| Block Dim / Mix Block Dim | Launch metadata in `OpBasicInfo.csv`; these values alone do not establish per-core load balance. |
| Simulator source / instruction / pipeline | Attribution context from recorded simulator artifacts; simulator duration remains separate from on-device duration. |

For supported file layouts, units and version-specific limits, read
[the metric reference](reference/08-ascend-metric-files.md). The calling agent
uses the actual source, workload and experiment history to evaluate possible
causes; this glossary does not map a metric threshold to a preferred kernel edit.

## A2 Launch Units And Available Resources

[CANN 8.5 SetBlockDim](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/API/basicdataapi/atlasopapi_07_00236.html)
defines the split-architecture launch units:

| Compiled kernel type | What `blockDim` counts | Source/profiler check |
|---|---|---|
| Pure AIC / Cube | AIC instances | Confirm compiler kernel type, actual launch dimension and AIC rows. |
| Pure AIV / Vector | AIV instances | Confirm no unintended MIX launch and inspect AIV rows. |
| MIX | Logical combinations of 1 AIC + 2 AIV | Keep `Block Dim`, `Mix Block Dim` and sub-block mapping. MIX 24 does not mean only 24 of 48 AIVs were used. |

Use `PlatformAscendC` from the **Host Tiling context** with `GetCoreNumAic` /
[GetCoreNumAiv](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/API/ascendcopapi/atlasascendc_api_07_1031.html)
when choosing launch dimensions under device resource limits. Record the query
object/context and configured limits. Static SKU configuration, direct launch
or a framework's platform cache do not by themselves establish resources
available to the current stream. Physical card ID, visible device index,
logical simulator core ID and CSV block/sub-block ID need explicit mapping.

## Capacity Ledger Before Tile Or Buffer Changes

[GetCoreMemSize](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/API/ascendcopapi/atlasascendc_api_07_1034.html)
returns bytes for the selected memory kind. Query the actual platform; save the
SoC, toolkit version and query origin. For each memory level, build this ledger
from source/generated code before proposing a larger tile or more buffers:

| Allocation | Required record |
|---|---|
| Input/output queues | Rounded bytes per buffer × queue buffer count; simultaneous lifetimes. |
| Intermediate tensors | Shape, dtype, padding/alignment and whether storage can be reused. |
| Higher-level API workspace | API's version-specific temporary-space query/result and lifetime. |
| Compiler/library reservation | Actual compiler/API constraints; unresolved reservations stay explicit. |
| Peak live allocation | Sum allocations whose lifetimes overlap; compare with usable capacity. |

A larger tile, double buffering and UB padding compete for the same capacity.
L2 is shared cache capacity, not a private per-kernel allocation. Configuration
rate fields are not measured GB/s or a universal roofline: [GetCoreMemBw](https://www.hiascend.com/document/detail/zh/canncommercial/850/API/ascendcopapi/atlasascendc_api_07_1035.html)
returns Byte/cycle for supported L2/HBM kinds. Document memory path, core scope
and frequency before using any such value. Unresolved bank/rate configuration
semantics must not generate physical mappings or peak-utilization claims.

## Source Checks And Conditional Experiments

These are mechanism checks, not measured improvements. For every experiment,
keep correctness, natural timing and mechanism evidence as separate judgments.

### GM Address Alignment And Cross-Core Regions

[A2 GM alignment guidance](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/opdevg/Ascendcopdevg/atlas_ascendc_best_practices_10_0014.html)
recommends 512-byte alignment for transfer efficiency. Separately,
[concurrent same-region accesses](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/opdevg/Ascendcopdevg/atlas_ascendc_best_practices_10_00013.html)
can serialize GM requests from different cores within one 512-byte region.
Derive `floor(address / 512)` for the actual per-core concurrent ranges. For
example, distinct 32-byte slices can still share a 512-byte region: disjoint
logical elements alone do not rule out this mechanism.

If source ranges support the hypothesis, change only traversal or partitioning
while preserving payload and correctness. Compare same-scope
`aiv_mte2_time(us)` / `aiv_mte3_time(us)`, core time, movement volume and natural
time. The time fields alone cannot prove an address conflict. The official
example's SyncAll and disabled-L2 controls serve that experiment; carry them
into a production candidate only if they belong to its intended behavior.

For fine-grained transfers, inspect each DataCopy's length, stride **units**,
block count, alignment and tail. [Larger transfer guidance](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/opdevg/Ascendcopdevg/atlas_ascendc_best_practices_10_0013.html)
and [batched transfer APIs](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/opdevg/Ascendcopdevg/atlas_ascendc_best_practices_10_0015.html)
suggest reducing repeated commands where legal. The illustrative 16 KiB rule
is an empirical direction, not a minimum legal length or a universal tile size.

### UB Operand Layout

The [CANN 8.5 A2/A3 UB guidance](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/opdevg/Ascendcopdevg/atlas_ascendc_best_practices_10_0025.html)
distinguishes bank and bank-group conflicts. Record operand base offsets,
block/repeat strides and simultaneous reads/writes. Correlate bank-group
hypotheses with `vec_bankgroup_cflt_ratio`, operand bank conflicts with
`vec_bank_cflt_ratio`, and execution-resource competition with
`vec_resc_cflt_ratio`, using the [metric's own denominator](https://www.hiascend.com/doc_center/source/en/canncommercial/850/devaids/optool/atlasopdev_16_0100.html).
These ratios cannot be added or converted into removable wall time.

A padding/stride variant is useful only when source mapping supports it. Repeat
the capacity ledger because padding changes addresses and storage, and may
change transfers. A lower conflict ratio with slower natural time does not
establish a successful optimization. Preserve conflicting platform bank-count
metadata as unresolved rather than inventing a physical address decoder.

### L2 Policy And Small Kernels

For reused plus streaming data, [CacheMode guidance](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/opdevg/Ascendcopdevg/atlas_ascendc_best_practices_10_00014.html)
suggests testing whether one-pass traffic displaces useful data. Hold replay,
warmup and input rotation fixed, change policy for the relevant stream, and
inspect `L2Cache.csv` together with `aiv_gm_to_ub_bw(GB/s)` and
`aiv_main_mem_write_bw(GB/s)` when collected. A hit-rate increase alone is not
a speedup. Constants in the [L2 partition example](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/opdevg/Ascendcopdevg/atlas_ascendc_best_practices_10_0036.html)
are illustrative assumptions, not 910B2 peak specifications.

For microsecond kernels, inspect compiled type and per-core useful work before
increasing core count. [Appropriate core count/kernel type guidance](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/opdevg/Ascendcopdevg/atlas_ascendc_best_practices_10_00012.html)
explains initialization cost and unnecessary Cube startup for Vector work.
Test fewer legal cores or the intended pure-Vector type as separate changes;
record work reassignment, core distributions and natural timing. Interpret MIX
ratios using SetBlockDim above, since the best-practice page contains conflicting
ratio wording. More balanced or more numerous cores need not be faster.

For buffering experiments, draw producer-complete, consumer-complete and
buffer-reuse dependencies. Different independent tiles can overlap; the same
tile's required copy/compute dependencies remain. [Ascend C pipeline guidance](https://www.hiascend.com/zh/developer/techArticles/20240819-1)
explains why extra buffers are useful only with capacity and overlap opportunity.
Keep intra-core flag dependencies separate from cross-core synchronization.
