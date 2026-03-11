# HPE PCAI — AI-Enabled Build Workflow

## Overview

AI-enabled layer for the HPE Private Cloud AI (PCAI) infrastructure deployment pipeline.
Built using CrewAI + LangGraph agents on top of Apache Airflow.

## Agents

1. Run Workflow Agent
2. Monitor Workflow Agent
3. Log Analyser Agent (LLM + RAG)
4. Root Cause Agent (LLM)
5. Alerting Agent (LLM)

## Project Structure

\`\`\`
agents/ → CrewAI agent definitions
rag/ → ChromaDB RAG setup and query layer
airflow_integration/ → Airflow REST API client
knowledge_base/ → HPE docs and error pattern data
notification/ → Slack / Email alerting
common/ → Shared utilities and config
tests/ → Unit and integration tests
docs/ → Architecture diagrams and documentation
infra/ → Docker, deployment configs
sample_logs/ → Sample Airflow task logs for testing
\`\`\`

## Branch Structure

- \`main\` → stable, protected — no direct pushes
- \`dev\` → integration branch — merge PRs here first
- \`feature/agents\` → AI agents work
- \`feature/rag\` → RAG pipeline work
- \`feature/airflow\` → Airflow DAG and integration work
- \`feature/notification\` → Alerting and notification work
