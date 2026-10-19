# Inspect An Existing Compiled Object

Use this optional reference for a supplied ELF, generated object or PC question.
It does not execute the input, compile a replacement or collect performance.
Finish with the available static facts and the specific mapping gap; complete
Source or simulator evidence is not a prerequisite for answering a static question.

## Establish Tool And Input Identity

Use the toolchain selected by the caller and record resolved tool paths, help,
version output where supported, input path and SHA256. The installed CANN
8.5.2 `msobjdump` interface exposes dump/list/extract and verbose metadata,
but not `--sass`. Its `--verbose` is not a version option. The matching LLVM
can list symbols without necessarily decoding the device instructions.

These commands are grounded in the distributed CANN 8.5.2 `msobjdump` package's
`msobjdump_main.py::parse_args` / `FileAction`, `utils.py` and the matching
LLVM help. Record the actual installed implementation hash when checking a
different installation. The upstream CANNBot design reference is not a tool
compatibility guarantee. Metadata capability was checked on retained native
AIV and MIX device objects; instruction decoding and runtime binding remain
separate validation items.

Work in a fresh caller-selected output directory, separate from the input and
its build tree. Some archive handling extracts members into cwd even during
metadata operations. Keep before/after input hashes and inspect output files;
do not run dump/list in a source directory and assume the operation cannot write.
Use the module entry below with the selected Python environment to preserve
quoted argument boundaries through older shell launchers.

```bash
# DEVICE_ELF and OBJECT_OUTPUT are caller-selected absolute paths.
# OBJECT_OUTPUT is a fresh directory, outside the input/build directory.
mkdir -p "$OBJECT_OUTPUT"
(
    cd "$OBJECT_OUTPUT" || exit
    sha256sum "$DEVICE_ELF" > input.before.sha256
    python3 -m msobjdump --help > msobjdump.help.txt 2>&1
    llvm-objdump --version > llvm.version.txt 2>&1
    llvm-objdump --help > llvm.help.txt 2>&1
)
```

Read the saved help before selecting a supported operation. For the checked
interface, run each operation separately and retain stdout, stderr and status:

```bash
(
    cd "$OBJECT_OUTPUT" || exit
    python3 -m msobjdump --dump-elf "$DEVICE_ELF" --verbose > metadata.txt 2> metadata.stderr
    printf '%s\n' "$?" > metadata.status
    llvm-objdump --syms "$DEVICE_ELF" > symbols.txt 2> symbols.stderr
    printf '%s\n' "$?" > symbols.status
    sha256sum "$DEVICE_ELF" > input.after.sha256
)
```

For a container, use supported list/extract operations in this isolated output
directory, then verify each actual extracted file's format and hash. A standalone
device ELF may have nothing to list; that does not make it invalid. Extensions,
printable strings and a zero exit status do not establish a device object or a
successful extraction. Unknown formats remain explicit limits.

## Separate Content From Runtime Binding

| Evidence | What it establishes |
|---|---|
| Input hash, ELF header, sections and function symbols | The content of this supplied object. |
| `_mix_aic` / `_mix_aiv` physical symbols | The separate symbol locations in this object; not two independently timed operators. |
| Matching runtime export/dump identity for the target launch | A link to that execution, within the export's identity guarantees. |
| Debug information | Potential source mapping; not measured source-line time. |

A matching filename, Op Name or source wrapper alone does not bind an object
to a run. If runtime evidence is absent, return static facts with binding
unverified. A hash mismatch blocks that mapping while retaining the object's
static description.

## Check A Bounded Instruction Window

Locate the exact function in the symbol table and calculate its half-open
range as `[value, value + size)` in the table's address domain and units.
Check that addition independently before using it to accept a PC or bound a
window. A paginated prefix only establishes what that prefix contains: search
the full saved table for the requested function and retain its original line,
or finish the table before claiming that no matching function exists.
Select the AIC/AIV side using evidence of the core
type. Distinguish object VMA, symbol-relative byte offset and runtime address.
For runtime PC, subtract a documented, same-domain load base; when the base or
unit is unknown, preserve the raw PC and stop address conversion.

Only after the installed LLVM help confirms the options, a static window can
use `--disassemble-symbols=<exact-symbol>`, `--start-address=<object-address>`
and `--stop-address=<exclusive-end>` with the verified device ELF. Bound the
window within the selected function and record the normalization formula.

Inspect the output semantically. In the checked 8.5.2 tools, a missing symbol
or nonoverlapping address range can return **0 with a warning**. A valid symbol
and address can also return `<not available>` instead of an instruction.
These results do not pass instruction-window validation. Require a decoded
instruction at the requested address, within the chosen symbol, before claiming
success. Preserve usable metadata if decoding is unavailable; do not repeatedly
retry unsupported options or run the target program to repair a disassembler.

Static instructions cannot establish elapsed time or a unique performance cause.
For Source performance questions, retain the separate [viewer validation route](15-cann852-capabilities.md#on-demand-native-operator-probes).
