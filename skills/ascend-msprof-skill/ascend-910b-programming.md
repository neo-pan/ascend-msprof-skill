# Ascend 910B Programming Context

Use this glossary when relating a recorded profiler field to Ascend C source.
Consult official CANN documentation for detailed programming and API semantics.

Ascend C custom operators separate host-side tiling/launch preparation from
device-side AI Core execution. Record the workload, tiling and blockDim used by
the measured run so its profiler observations can be associated with that source.

| Concept | Context for reading profiler evidence |
|---|---|
| Cube | Matrix computation; retain the exact Cube time/ratio fields reported by the selected metric family. |
| Vector | Vector computation, including elementwise and reduction operations; interpret recorded instruction and pipe fields in the context of the workload. |
| Scalar | Address/control and scalar execution context; preserve raw Scalar fields instead of inferring a cause from their relative magnitude. |
| MTE / DataCopy | Data movement context; distinguish transfer fields from compute fields and retain the named memory level. |
| GM, UB, L1 and L0 | Distinct memory levels named in the profiler output; keep volume, bandwidth, usage, time and conflict fields separate. |
| Block Dim / Mix Block Dim | Launch metadata in `OpBasicInfo.csv`; these values alone do not establish per-core load balance. |
| Simulator source / instruction / pipeline | Attribution context from recorded simulator artifacts; simulator duration remains separate from on-device duration. |

For supported file layouts, units and version-specific limits, read
[the metric reference](reference/08-ascend-metric-files.md). The calling agent
uses the actual source, workload and experiment history to evaluate possible
causes; this glossary does not map a metric threshold to a preferred kernel edit.
