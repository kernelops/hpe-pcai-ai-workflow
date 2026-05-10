# Agents Folder Setup (LLM Only)

This folder contains a minimal Gemini 2.5 Flash workflow for Airflow log analysis.

## What This Implements

- Lightweight Airflow log parsing for DAG/task/error/exit code extraction.
- Gemini 2.5 Flash multi-agent pipeline with explicit agents:
  - Analyzer Agent
  - Root Cause Agent
  - Fix Suggestion Agent

## Files

- `main.py`: CLI entry point.
- `log_tools.py`: Minimal log parsing utilities.
- `llm_agents.py`: Gemini-based Analyzer, Root Cause, and Fix Suggestion agents.
- `schemas.py`: Structured result models.

## Quick Run

From repo root:

```powershell
python agents/main.py sample_logs/minio_error_log
```

Outputs are generated in `agents/output/`.

## Run With Gemini LLM Agents (Detailed Agent Outputs)

Put your key in repo `.env` (already supported):

```env
GEMINI_API_KEY=<your_api_key>
```

Then run directly:

```powershell
python agents/main.py path/to/your_log_file
```

This adds three sections in the output report:

- Analyzer Agent Output
- Root Cause Agent Output
- Fix Suggestion Agent Output

## Demo Commands (Single Log)

```powershell
python agents/main.py sample_logs/nfs_configuration_error_log
python agents/main.py sample_logs/os_validationerror__logs
python agents/main.py sample_logs/minio_error_log
```
