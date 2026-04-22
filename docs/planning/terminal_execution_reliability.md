# Terminal Execution Reliability Guide

Purpose: reduce flaky runs, avoid oversized ad-hoc commands, and document what works by environment.

## Why very large commands happen

1. Ad-hoc JSON analysis in one-liners.
   - Pattern: very long `python -c "..."` commands.
   - Risk: hard to read, hard to retry safely, easy to truncate or edit incorrectly.
2. Agent safety retries after ambiguous output.
   - Pattern: rerunning similar commands when prior output is incomplete, timed out, or contradictory.
   - Risk: duplicate work and noisy logs.
3. Overly broad "do everything" command requests.
   - Pattern: one command expected to run analysis, filtering, ranking, and formatting.
   - Risk: more failure points per execution.

## What works reliably in this repo

### Windows + PowerShell (pwsh)

- Works well:
  - Running script entry points with explicit Python executable.
  - Quoted paths with spaces, for example `"D:\3D Files\FDM"`.
  - OpenSCAD headless rendering with `--render`.
  - Passing subprocess arguments as a list from Python.
- Known constraints:
  - Do not use `--preview=throwntogether` for headless Windows runs.
  - Do not wrap subprocess invocations in PowerShell `-EncodedCommand`.

### Virtual environment selection

- Most reproducible pattern in this repo:
  - `c:/Users/herat/source/stl2scad/venv/Scripts/python.exe`
- Alternative when shell is already activated:
  - `python ...`

## What tends to be flaky

1. Long one-liner Python commands for data slicing/reporting.
2. Running heavy directory scans with no summary script and then manually post-processing in shell.
3. Reconstructing command variants repeatedly instead of using one stable helper script.

## Recommended command patterns

### 1) Run triage

python scripts/build_feature_graph.py "D:\3D Files\FDM" --output artifacts/fdm_graphs.json --triage-output artifacts/feature_graph_triage.json

### 2) Summarize triage (new helper)

python scripts/summarize_feature_triage.py artifacts/feature_graph_triage.json --top 10

This replaces fragile one-liners and gives stable candidate lists for fixture selection.

## Operational rules for agents and humans

1. Prefer short script commands over inline logic.
2. If a command times out, retry once with narrower scope before rerunning full scope.
3. Separate run and analysis steps:
   - Step A: generate artifact JSON.
   - Step B: summarize artifact JSON.
4. Keep command payloads single-purpose.
5. When a summary looks suspicious, validate directly from the artifact file once.

## Suggested VS Code task additions (optional)

- `triage-fdm`
- `triage-summary`

These remove command drift and reduce repeated manual command construction.
