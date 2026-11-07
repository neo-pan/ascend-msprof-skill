# TD-001: Generated Kernel Argument Capture Missing Descriptions

**Status: open; explicit simulator workaround validated.** Last verified:
2026-11-05, CANN 9.1.0 / Ascend 910B2. This record covers the tested TileLang
MIX add and its direct-launch library. It does not declare every TileLang or
CANN 9.1 operator unsupported. No upstream fix or public tracking issue has
been established by this project.

## Impact And Recognition

The application computes correctly and ordinary app/op PMU collection succeeds,
but TimelineDetail cannot capture the inputs needed for simulation. The observed
sequence is `Addr info is null, can not dump`, `Kernel context save failed`, then
`TimelineDetail data collection failed`. The profiler can exit 0; the helper must
keep this capture blocked. BasicInfo and independent PMU evidence remain usable.

Read the saved failure without launching another collector:

```bash
ascend-msprof evidence --run-dir "$PROFILE_RUN_DIR" --question collection
```

`kernel_argument_dump_failed` selects `inspect_kernel_argument_capture` recovery.
The `profile-pipeline` receipt also records this read command as
`diagnostic_command`. A log match identifies the capture stage; it cannot alone
establish which metadata is absent from an arbitrary binary.

## Established Cause And Evidence

The checked msopprof commit is `56632dc4a944410c791538451dc2156a151bd105`;
installed msopscommon is `d1564487d9c0b27033f6bb51b19b21bec7be6aa5`. Record both:
the common component can differ from the profiler repository's gitlink.

- [ArgsContext.cpp](https://github.com/Ascend/msopcom/blob/d1564487d9c0b27033f6bb51b19b21bec7be6aa5/csrc/runtime/inject_helpers/ArgsContext.cpp#L64-L71)
  emits the address-info message when the input-parameter description vector
  is empty. It does not identify a null tensor pointer.
- [LaunchContext.cpp](https://github.com/Ascend/msopcom/blob/d1564487d9c0b27033f6bb51b19b21bec7be6aa5/csrc/runtime/inject_helpers/LaunchContext.cpp#L101-L130)
  consumes supplied launch descriptions or reads kernel metadata.
  [KernelMetaDataParser.cpp](https://github.com/Ascend/msopcom/blob/d1564487d9c0b27033f6bb51b19b21bec7be6aa5/csrc/runtime/inject_helpers/KernelMetaDataParser.cpp#L61-L95)
  consumes DFX type 4 argument descriptions.
- Both captured `.ascend.meta.cann910_add_kernel_mix_*` sections contain types
  1, 3, 16 and 17, but no type 4. Parameter types/ABI metadata do not provide the
  buffer-size descriptions needed by this capture parser.
- Reducing the framework application to one launch and running the identical
  library with native ACL allocations each reproduces the failure with correct
  output. Multiple launches and the Torch allocator are not necessary causes.

The 9.1 compiler distribution's
`asc_op_compiler/ascendc_compile_dfx.py`, in `asc_op_compile_base`, computes static
sizes from OpInfo shape/dtype in `_set_level_1_input_output_dfx_info` and emits
DFX records in `generate_dfx_section_for_one_tiling_key`. Emission is conditional
on the operator/tiling configuration. This installed implementation explains
the standard compilation path; it is not a public API for helper-side injection.

Verbatim diagnostic excerpts with source hashes and retained line numbers are
in the repository fixture `tests/fixtures/real_cann910_capture_diagnostics`.
Those excerpts reproduce log handling, not the ELF investigation or a live
TimelineDetail repair. Historical 8.5.2 excerpts retain their own version.

## Long-Term Repair Plan

This is an engineering plan for the generating framework and its CANN
integration. The helper owns diagnosis, evidence preservation and verification.
Completion requires the original framework entry to pass the checks below.

In the inspected TileLang implementation, start at `CythonKernelAdapter`
(`tilelang/jit/adapter/cython/adapter.py`), which already has tensor parameters
and output/workspace indices. Carry the checked descriptions through
`LibraryGenerator` (`tilelang/jit/adapter/libgen.py`), and verify the final
argument order in `CodeGenTileLangAscend::PrintHostFunc`
(`src/target/codegen_ascend.cc`). These are proposed integration points, not
an implemented repair. The existing exception-dump `ParamSizeInfo` callback
uses a separate protocol; enabling it has not been established as a profiler
metadata fix.

1. **Define descriptions from the actual lowered launch ABI.** Record each
   argument's position, role, pointer level, dtype, shape and valid byte extent;
   distinguish inputs, outputs, workspace, tiling and control/scalar values.
   Start with the reproduced contiguous static add: its three FP32 buffers are
   each `1024 * 256 * 4 = 1048576` bytes. Preserve the generated wrapper's extra
   FFTS argument and any compiler-injected arguments. Finish when every argument
   consumed by the launch has an explicit, checked description or exclusion.
2. **Integrate with a supported build/invocation route.** Prefer the documented
   standard operator compilation/deployment workflow carrying input/output
   descriptions; the [9.1 profiler guide](https://github.com/Ascend/msopprof/blob/56632dc4a944410c791538451dc2156a151bd105/docs/zh/user_guide/msopprof_user_guide.md#L82)
   links that workflow. Inspect the resulting ELF/launch metadata rather than
   assuming any standard build emits the required records. If direct launch
   must remain, establish a supported producer/consumer contract with the
   compiler/profiler maintainers before implementing a version-scoped adapter.
   Internal `rtSetExceptionExtInfo` calls and handwritten ELF sections have not
   been validated as a supported repair here. Finish when the installed capture
   consumer receives the correct descriptions for the actual MIX symbols.
3. **Bind metadata to compilation and invocation.** Include ABI/metadata format,
   target, compiler options and shape specialization in cache identity. Resolve
   dynamic byte extents from each supported invocation; keep descriptions and
   buffers valid for capture and avoid stale data between shapes, streams or
   launches. Start with the static supported subset and explicitly reject
   unimplemented layouts/pointer levels. A successful one-shape add is not
   dynamic-shape or second-level-pointer support.
4. **Verify the original entry end to end.** Re-run the original framework
   application with the same workload, target contract and kernel replay. Check
   captured buffer sizes/contents, output correctness, selected launches and
   actual instruction intervals. Test a second shape and repeated invocations
   before extending the supported subset. Keep `-g` source mapping as an
   independent build/validation check. Finish only against the closure criteria.

If the supported compiler/launch contract cannot be established, leave TD-001
open and retain the explicit simulator route. Changing the helper's status or
suppressing the capture error does not complete this plan.

## Validated Workaround And Its Limits

Use a standalone ACL application that loads the same generated library and
preserves its full wrapper/launch ABI, input contents and buffer lifetimes:

```bash
ascend-msprof profile-pipeline --run-dir profile/explicit-simulator \
    --manifest "$NATIVE_MANIFEST" --mode simulator \
    --soc-version Ascend910B2 --core-id 0 --timeout-s 180
```

Supply a manifest for that application with the actual kernel selector and
expected launches; use a fresh run directory. Preserve the profiler-injected
library environment and verify numerical output separately from trace presence.
The identical library passed correctness and generated 3,624 complete X events.
Rebuilding the same source with `-g` passed device/simulator correctness and
produced 3,626 X events, with both selected vector-lane VADD intervals mapped
to the generated Add line. These are selected-lane simulation results, not
complete vector-lane coverage, device latency or a repaired framework capture.

The [simulator application workflow](https://github.com/Ascend/msopprof/blob/56632dc4a944410c791538451dc2156a151bd105/docs/zh/user_guide/msopprof_simulator_user_guide.md#L320-L335)
keeps the original wrapper's ABI. JSON config is a separate interface: its
FFTS packing cannot simply be substituted for this kernel's final scalar
`uint64_t fftsAddr`. `-g` supplies debug lines, not argument byte sizes;
`--custom-input` configures timestamp display, not input tensor descriptions.

## Closure Criteria

| Check | Required evidence |
|---|---|
| Metadata correctness | Actual device ELF or supported launch descriptions bound to source, binary, shape and component versions; argument order, roles and byte extents match the launch. |
| Original framework capture | Original framework application and declared launches captured without argument/context or TimelineDetail failure; input dumps have the expected sizes/contents. A native-only workaround is insufficient. |
| Correctness and instructions | Device/replay output matches the reference and target instruction X intervals exist; requested lanes and launch coverage are accounted for. Exit 0 alone is insufficient. |
| Repeatability | Repeated calls and each advertised shape/dtype/layout work without stale metadata; unsupported cases remain explicit. |
| Regression protection | A missing-description negative case remains blocked even with profiler exit 0; successful captures retain target/coverage checks; mapping-only gaps preserve useful instruction evidence. |

Keep Source binary-view decoding and unknown source-line `:0` records separate.
The former remains outside validated helper decoding; the latter preserves
metrics while reporting unavailable line attribution. Neither closes TD-001.
