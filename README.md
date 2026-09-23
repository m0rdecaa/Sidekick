# Sidekick

A security-conscious multi-channel AI agent for OpenRouter, Jupyter, and WhatsApp Cloud API.

## Features

- OpenRouter-compatible chat completions with streaming support.
- Persistent conversation history stored locally outside the repository by default.
- Explicit, opt-in tools: calculator and Jupyter code execution.
- JupyterLab integration through the Jupyter Server REST API.
- WhatsApp Cloud API webhook verification and message delivery.
- No embedded credentials, unofficial WhatsApp session files, or private keys.

## Quick start

```bash
python3 sidekick.py --set-key "$OPENROUTER_API_KEY"
python3 sidekick.py -p "Explain a TCP handshake" --json
python3 sidekick.py
```

For Jupyter, configure:

```bash
export JUPYTER_URL=http://127.0.0.1:8888
export JUPYTER_TOKEN=...
python3 sidekick.py --jupyter "print(2 + 2)"
```

For WhatsApp Cloud API, configure `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN`, and `WHATSAPP_PHONE_NUMBER_ID`, then run:

```bash
python3 sidekick.py --whatsapp-host 0.0.0.0 --whatsapp-port 8080
```

Expose the webhook at `/webhook` and set the Meta callback URL to that endpoint. Use the official WhatsApp Cloud API only. Existing WhatsApp auth/session JSON files must be revoked and deleted; they are never read by Sidekick.

## Configuration

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OPENROUTER_MODEL` | Model ID, default `deepseek/deepseek-chat-v3-0324:free` |
| `SIDEKICK_CONFIG` | Local config path, default `~/.config/sidekick/config.json` |
| `JUPYTER_URL` | Jupyter Server base URL |
| `JUPYTER_TOKEN` | Jupyter token |
| `WHATSAPP_ACCESS_TOKEN` | Meta Graph API token |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verification secret |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp business phone number ID |

Never commit secrets. Copy `.env.example` to a local environment manager instead of adding credentials to the repository.

## Safety

Jupyter execution is disabled unless `--allow-jupyter` is supplied. Code runs in the configured Jupyter server with that server's permissions, so use a dedicated server and authentication token. WhatsApp messages are accepted only from configured allowed numbers when `WHATSAPP_ALLOWED_NUMBERS` is set.
