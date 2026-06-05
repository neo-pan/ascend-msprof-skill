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
