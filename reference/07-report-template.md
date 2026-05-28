# Final Report Template

Save as `$PROFILE_RUN_DIR/REPORT.md`.

```markdown
# <kernel_or_operator> Ascend Profiling Report

**Target:** Ascend 910B
**CANN / driver / firmware:** <versions>
**Profile date:** YYYY-MM-DD
**Run directory:** `profile/<run_name>/`

## 0. Setup

- Harness/application:
- Workload shape and dtype:
- Tiling path and blockDim:
- Commands:
- Raw artifacts:

## 1. Headline Numbers

| Metric | Value | Source |
|---|---:|---|
| Top operator duration | | `op_summary_*.csv` |
| Call count | | `op_summary_*.csv` |
| Top task duration | | `task_time_*.csv` |
| Dominant pipe | | `PipeUtilization.csv` |
| Top memory signal | | `Memory*.csv` |
| Top conflict signal | | `ResourceConflictRatio.csv` |

**One-line read:** <main bottleneck and why>

## 2. Analysis

### Duration And Calls

### Pipe Utilization

### Memory Movement

### Conflicts

### Tiling And Core Balance

### Simulator Hotspots

## 3. Diagnosis

| Finding | Evidence | Impact |
|---|---|---|

## 4. Optimization Directions

1. <highest-impact change>
2. <next change>
3. <next change>

## 5. Confidence And Caveats

## 6. Reproduction
```

Keep the report short. Put large tables in `analysis/`.

