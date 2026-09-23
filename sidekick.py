#!/usr/bin/env python3
"""Sidekick: OpenRouter agent with Jupyter and WhatsApp Cloud API adapters.

Standard-library-only implementation. Credentials are read from environment
variables or a local config file and are never printed or committed.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "deepseek/deepseek-chat-v3-0324:free"
DEFAULT_PROMPT = "You are Sidekick, a concise and helpful assistant. Never claim to have performed an action you did not perform."


def config_path() -> Path:
    return Path(os.environ.get("SIDEKICK_CONFIG", "~/.config/sidekick/config.json")).expanduser()


def load_config() -> dict[str, Any]:
    data: dict[str, Any] = {}
    path = config_path()
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
    data.setdefault("model", os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL))
    data.setdefault("api_key", os.environ.get("OPENROUTER_API_KEY", ""))
    data.setdefault("system", DEFAULT_PROMPT)
    data.setdefault("history", [])
    return data


def save_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def http_json(url: str, *, method: str = "GET", payload: Any = None, headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, method=method, headers={"Accept": "application/json", "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc.reason}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Provider returned invalid JSON") from exc


def calculate(expression: str) -> str:
    """Safely evaluate arithmetic only; no names, calls, attributes, or strings."""
    tree = ast.parse(expression, mode="eval")
    allowed = (ast.Expression, ast.Constant, ast.UnaryOp, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.FloorDiv)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError("only arithmetic expressions are allowed")
    value = eval(compile(tree, "<calculator>", "eval"), {"__builtins__": {}}, {})
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("expression did not produce a number")
    return str(value)


class Sidekick:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def complete(self, prompt: str, *, history: list[dict[str, str]] | None = None) -> str:
        key = self.config.get("api_key") or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        messages = [{"role": "system", "content": self.config.get("system", DEFAULT_PROMPT)}]
        messages.extend(history if history is not None else self.config.get("history", []))
        messages.append({"role": "user", "content": prompt})
        data = http_json("https://openrouter.ai/api/v1/chat/completions", method="POST", payload={"model": self.config.get("model", DEFAULT_MODEL), "messages": messages, "temperature": 0.7}, headers={"Authorization": f"Bearer {key}", "HTTP-Referer": self.config.get("app_url", "https://github.com/m0rdecaa/Sidekick"), "X-Title": "Sidekick"}, timeout=180)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected completion response: {data}") from exc

    def ask(self, prompt: str) -> str:
        answer = self.complete(prompt)
        history = self.config.setdefault("history", [])
        history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}])
        self.config["history"] = history[-40:]
        save_config(self.config)
        return answer

    def jupyter(self, code: str) -> dict[str, Any]:
        url = os.environ.get("JUPYTER_URL", "").rstrip("/")
        token = os.environ.get("JUPYTER_TOKEN", "")
        if not url or not token:
            raise RuntimeError("JUPYTER_URL and JUPYTER_TOKEN are required")
        kernels = http_json(f"{url}/api/kernels", headers={"Authorization": f"token {token}"})
        kernel = kernels[0] if kernels else http_json(f"{url}/api/kernels", method="POST", payload={"name": "python3"}, headers={"Authorization": f"token {token}"})
        kernel_id = kernel["id"]
        # Kernel channels use WebSockets; this REST fallback is intentionally explicit.
        return {"kernel_id": kernel_id, "message": "Kernel available. Use JupyterLab or a kernel-gateway client to execute code.", "code": code}


class WhatsAppHandler(BaseHTTPRequestHandler):
    agent: Sidekick | None = None
    verify_token: str = ""
    access_token: str = ""
    phone_id: str = ""
    allowed: set[str] = set()

    def log_message(self, fmt: str, *args: Any) -> None:
        print("whatsapp:", fmt % args, file=sys.stderr)

    def do_GET(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if query.get("hub.verify_token", [""])[0] == self.verify_token:
            self.send_response(200); self.end_headers(); self.wfile.write(query.get("hub.challenge", [""])[0].encode()); return
        self.send_response(403); self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/webhook":
            self.send_response(404); self.end_headers(); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            event = json.loads(self.rfile.read(length))
            for entry in event.get("entry", []):
                for change in entry.get("changes", []):
                    for message in change.get("value", {}).get("messages", []):
                        sender = message.get("from", "")
                        text = message.get("text", {}).get("body", "")
                        if text and (not self.allowed or sender in self.allowed):
                            answer = self.agent.ask(text) if self.agent else "Sidekick is not configured."
                            send_whatsapp(sender, answer, self.phone_id, self.access_token)
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        except Exception as exc:
            print(f"webhook error: {exc}", file=sys.stderr)
            self.send_response(400); self.end_headers()


def send_whatsapp(recipient: str, text: str, phone_id: str, token: str) -> None:
    http_json(f"https://graph.facebook.com/v20.0/{phone_id}/messages", method="POST", payload={"messaging_product": "whatsapp", "to": recipient, "type": "text", "text": {"body": text[:4096]}}, headers={"Authorization": f"Bearer {token}"})


def run_whatsapp(agent: Sidekick, host: str, port: int) -> None:
    WhatsAppHandler.agent = agent
    WhatsAppHandler.verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    WhatsAppHandler.access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
    WhatsAppHandler.phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    WhatsAppHandler.allowed = {x.strip() for x in os.environ.get("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if x.strip()}
    if not all((WhatsAppHandler.verify_token, WhatsAppHandler.access_token, WhatsAppHandler.phone_id)):
        raise RuntimeError("WHATSAPP_VERIFY_TOKEN, WHATSAPP_ACCESS_TOKEN, and WHATSAPP_PHONE_NUMBER_ID are required")
    server = ThreadingHTTPServer((host, port), WhatsAppHandler)
    print(f"WhatsApp webhook listening on http://{host}:{port}/webhook")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sidekick multi-channel AI agent")
    parser.add_argument("-p", "--prompt")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--set-key")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--calculate")
    parser.add_argument("--jupyter")
    parser.add_argument("--allow-jupyter", action="store_true")
    parser.add_argument("--whatsapp-host", default="")
    parser.add_argument("--whatsapp-port", type=int, default=8080)
    args = parser.parse_args(argv)
    config = load_config(); agent = Sidekick(config)
    if args.set_key:
        config["api_key"] = args.set_key; save_config(config); print("API key saved securely."); return 0
    if args.clear:
        config["history"] = []; save_config(config); print("Conversation history cleared."); return 0
    try:
        if args.calculate:
            print(calculate(args.calculate)); return 0
        if args.jupyter:
            if not args.allow_jupyter: raise RuntimeError("Jupyter is disabled; pass --allow-jupyter explicitly")
            print(json.dumps(agent.jupyter(args.jupyter), indent=2)); return 0
        if args.whatsapp_host:
            run_whatsapp(agent, args.whatsapp_host, args.whatsapp_port); return 0
        if args.prompt:
            answer = agent.ask(args.prompt)
            print(json.dumps({"ok": True, "response": answer}, indent=2) if args.json else answer)
            return 0
        while True:
            try: prompt = input("you > ").strip()
            except (EOFError, KeyboardInterrupt): print(); return 0
            if prompt in {"/exit", "/quit"}: return 0
            if prompt == "/clear": config["history"] = []; save_config(config); print("cleared"); continue
            if prompt: print("sidekick >", agent.ask(prompt))
    except (RuntimeError, ValueError) as exc:
        if args.json: print(json.dumps({"ok": False, "error": str(exc)}))
        else: print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
