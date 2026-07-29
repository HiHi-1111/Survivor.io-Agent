# Survivor.io AI Assistant

A Python-based research and automation agent for the Survivor.io project.

## Goals

- Research current Survivor.io information using live web search
- Store and retrieve verified game knowledge
- Add custom tools for equipment, builds, and damage calculations
- Connect external services safely through Composio
- Require approval before external write actions

## Quick start

1. Install Python 3.10+ and `uv`.
2. Copy `.env.example` to `.env`.
3. Add your API keys to `.env`.
4. Install dependencies:

```bash
uv sync
```

5. Run the agent:

```bash
uv run python agent.py
```

## Safety model

Read-only research can run automatically. Sending messages, publishing content, deleting data, spending money, and changing external systems must require explicit user approval.

## Project status

This repository contains the initial agent scaffold. Composio account authorization and production deployment still require owner-controlled credentials.
