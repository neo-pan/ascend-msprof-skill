# Commands

Run: `profile/tilelang-controlled-pipelined-input-20260605`

This run attempted to collect a pipeline-stage candidate. It stopped after
benchmark verification because the payload did not compile.

## Verify

```bash
env ASCEND_RT_VISIBLE_DEVICES=0 TL_ASCEND_DEBUG_INFO=1 TMPDIR=<abs-path> PYTHONPATH=<abs-path> <abs-path> -u -m ascend_svd_benchmark.runner verify --task svd --kernel-payload-src <abs-path> --warmups 0 --repeats 1 --timeout-s 300 --output <abs-path> --baseline-ms 1.0 --jit-debug-root <abs-path>
```

Result:

- `compiled`: `false`;
- `correctness`: `false`;
- error stage: `compile`;
- preserved error context:
  `profile/tilelang-controlled-pipelined-input-20260605/benchmark_result.error.json`.

Compile failure headline:

```text
ValueError: Check failed: (pipeline_body_seq) is false: The body of the software pipeline should be SeqStmt, got tir.For for j in range(32):
```

## Follow-Up Boundary

No `msprof` app/op/Default collection was run because there is no compiled,
correctness-passing kernel for this candidate.
