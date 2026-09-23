# Sidekick

A security-conscious OpenRouter agent with optional Jupyter connectivity.

## Features

- OpenRouter chat completions from the terminal.
- Interactive mode and JSON one-shot mode.
- Persistent conversation history stored outside the repository by default.
- Safe arithmetic calculator.
- Optional authenticated Jupyter Server health and kernel check.
- No WhatsApp integration, credentials, session files, or private keys.

## Quick start

```bash
export OPENROUTER_API_KEY="your-key"
python3 sidekick.py -p "Explain a TCP handshake"
python3 sidekick.py -p "Summarize this" --json
python3 sidekick.py --calculate "10 * (4 + 2)"
python3 sidekick.py
```

## Jupyter

```bash
export JUPYTER_URL=http://127.0.0.1:8888
export JUPYTER_TOKEN=your-token
python3 sidekick.py --jupyter
```

The Jupyter option checks authentication and returns an existing kernel ID, or starts a Python kernel when none exists. It does not execute arbitrary code.

## Configuration

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OPENROUTER_MODEL` | Model ID, default `deepseek/deepseek-chat-v3-0324:free` |
| `SIDEKICK_CONFIG` | Local config path, default `~/.config/sidekick/config.json` |
| `JUPYTER_URL` | Jupyter Server base URL |
| `JUPYTER_TOKEN` | Jupyter token |

Never commit secrets. The local config file is written with mode `600`.
