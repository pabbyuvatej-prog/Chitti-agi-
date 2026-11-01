# CHITTI Cognitive Core V2.0

Offline-first Python cognitive orchestration prototype for Android/ARM64.

## What it is
- Standard-library-only Python application.
- SQLite persistent conversation, memory, feedback, knowledge and evaluation records.
- Six agents with distinct responsibilities: Primary, Critical, Alternative, Research, Decision Judge and Self-Review.
- Adaptive, Autonomous and Collaborative orchestration modes.
- Heuristic emotion/context detection and response-style adaptation.
- Optional Wikipedia search (off by default).
- Optional OpenAI-compatible external model endpoint (off by default).
- No shell execution, `eval`, `exec`, phone-control actions or background task execution.

This is a research prototype, not AGI. Its agents are software components with different algorithms, not independent conscious minds or independently trained neural networks. Emotion labels are keyword/context heuristics, not reliable psychological measurements. Confidence values are heuristic scores, not calibrated probabilities.

## Device fit
Designed to minimize storage and RAM use. It uses only Python's standard library and creates a small SQLite database under `~/.chitti_v2/`. It does not download a language model. A real local LLM may require substantial additional storage and RAM, so it is not bundled.

## Installation / execution
Open the HyperDroid terminal and first check:

```sh
python --version
python3 --version
uname -m
```

Use whichever Python command exists. Then place `chitti_v2.py` in a folder accessible to the terminal and run:

```sh
python chitti_v2.py
```

or:

```sh
python3 chitti_v2.py
```

No `pip install` command is required.

If HyperDroid cannot access the Downloads folder, use its file manager's **Open in terminal / Copy path** feature and `cd` to the folder containing the script. Do not assume Android paths are identical across terminal apps.

## First test
At the `YOU >` prompt, try:

```text
/status
/remember project = CHITTI Cognitive Core V2
What are three ways to test a small offline assistant?
/memory
/feedback good The answer was clear
/exit
```

## Commands
- `/help`
- `/status`
- `/mode adaptive`
- `/mode autonomous`
- `/mode collaborative`
- `/online on` or `/online off`
- `/model on` or `/model off`
- `/remember KEY = VALUE`
- `/memory`
- `/forget ID`
- `/forget all` (requires typing `DELETE`)
- `/knowledge TOPIC = CONTENT`
- `/feedback good [note]`
- `/feedback bad [note]`
- `/exit`

## Optional online research
Online research is disabled by default. To enable Wikipedia search snippets:

```text
/online on
```

Disable it again with `/online off`. Online snippets are leads, not verified evidence. Check important claims against reliable primary sources.

## Optional external model
The external model adapter uses an OpenAI-compatible `/chat/completions` endpoint. It is disabled by default. Never paste an API key into chat or hard-code it in the script. Set environment variables in the terminal session using the provider's secure instructions:

- `CHITTI_API_KEY`
- `CHITTI_MODEL`
- Optional `CHITTI_API_BASE` (defaults to `https://api.openai.com/v1`)

Then use `/model on`. API calls may incur charges and send the task text to the configured provider. Use only with permission and after reviewing the provider's privacy and pricing terms. `/model off` returns to the local engine.

## Memory and privacy
The database is stored at `~/.chitti_v2/chitti_memory.sqlite3`. It contains chat turns, saved memories, knowledge notes, feedback and evaluation metrics. It is local to the app's accessible home directory. Protect the device and its backups. `/forget ID` deletes one saved memory; `/forget all` deletes saved memories after confirmation. Conversation history and other tables are not erased by that command.

## Troubleshooting
- `python: not found`: try `python3 --version`; if neither exists, install a Python 3 interpreter supported by your HyperDroid environment.
- `Permission denied`: move the script to a user-writable folder and run it there.
- `No module named sqlite3`: the Python build lacks SQLite support; use a Python distribution that includes the standard `sqlite3` module.
- Online lookup fails: confirm internet permission/connectivity; the core continues offline.
- External model fails: check endpoint, model name, key and provider compatibility; local mode remains available.
- Storage warning: the database grows with conversation history. Back up important data and manage the app's storage using Android settings. Do not delete the database unless you intend to erase its stored records.

## Current limitations and next research milestones
1. Test on-device and record Python version, architecture and first-run output.
2. Add retrieval ranking and evidence provenance.
3. Add structured task planning and bounded multi-step execution (with user approval for consequential actions).
4. Add evaluation datasets and repeatable benchmark scores.
5. Add optional local-model adapter only after measuring actual memory/storage headroom.
6. Add voice modules as separate optional components.

The system does not self-train its underlying model from ordinary conversation. Feedback is stored for later evaluation and can inform future explicit software improvements.
