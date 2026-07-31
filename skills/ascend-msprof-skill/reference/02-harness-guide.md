# Harness Guide

Use a standalone harness when you need repeatable, isolated kernel/operator
profiling.

## Required Properties

- deterministic input shapes and values
- explicit tiling or operator attributes
- fixed stream behavior
- device synchronization before timing/profiling completes
- output correctness check before running `msprof`
- build and run commands saved with the harness

For a known single-kernel or multi-launch profiling target, declare the launch
contract in the profile-harness manifest:

```json
{
  "schema_version": 1,
  "application": "run_application.sh",
  "target": {
    "kernel_selector": "program_kernel_*",
    "expected_launches": [
      {"name": "program_kernel_init", "count": 1},
      {"name": "program_kernel_round", "count": 4}
    ]
  }
}
```

`kernel_selector` is passed only to validated `msprof op --kernel-name`.
`--launch-count` is derived from the expected counts, never declared
separately. The same normalized target is persisted for supported Default
follow-up collection. Legacy `expected_kernel_name` and
`expected_kernel_names` metadata remains identity-only and does not filter
collection or prove launch-count completeness.

## Recommended Structure

Start from the packaged `assets/harness_template.cpp` and fill:

- CANN/ACL initialization
- device selection
- host input allocation/loading
- device memory allocation and copies
- operator launch wrapper
- stream synchronization
- device-to-host output copy
- correctness check
- cleanup

## When Not To Harness

Profile through the original app if framework dispatch, graph capture, host API
cost, or surrounding kernels are part of the question.
