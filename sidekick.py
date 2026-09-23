#!/usr/bin/env python3
"""Sidekick: a secure OpenRouter CLI agent with optional Jupyter support."""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "deepseek/deepseek-chat-v3-0324:free"
DEFAULT_PROMPT = (
    "You are Sidekick, a concise and helpful assistant. "
    "Never claim to have performed an action you did not perform."
)


def config_path() -> Path:
    return Path(
        os.environ.get("SIDEKICK_CONFIG", "~/.config/sidekick/config.json")
    ).expanduser()


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


def http_json(
    url: str,
    *,
    method: str = "GET",
    payload: Any = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
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
    """Evaluate arithmetic without allowing names, calls, attributes, or strings."""
    tree = ast.parse(expression, mode="eval")
    allowed = (
        ast.Expression,
        ast.Constant,
        ast.UnaryOp,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.FloorDiv,
    )
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError("only arithmetic expressions are allowed")
    value = eval(compile(tree, "<calculator>", "eval"), {"__builtins__": {}}, {})
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("expression did not produce a number")
    return str(value)


class Sidekick:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def complete(
        self, prompt: str, *, history: list[dict[str, str]] | None = None
    ) -> str:
        key = self.config.get("api_key") or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")

        messages = [
            {"role": "system", "content": self.config.get("system", DEFAULT_PROMPT)}
        ]
        messages.extend(history if history is not None else self.config.get("history", []))
        messages.append({"role": "user", "content": prompt})

        data = http_json(
            "https://openrouter.ai/api/v1/chat/completions",
            method="POST",
            payload={
                "model": self.config.get("model", DEFAULT_MODEL),
                "messages": messages,
                "temperature": 0.7,
            },
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": self.config.get(
                    "app_url", "https://github.com/m0rdecaa/Sidekick"
                ),
                "X-Title": "Sidekick",
            },
            timeout=180,
        )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected completion response: {data}") from exc

    def ask(self, prompt: str) -> str:
        answer = self.complete(prompt)
        history = self.config.setdefault("history", [])
        history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": answer},
            ]
        )
        self.config["history"] = history[-40:]
        save_config(self.config)
        return answer

    def jupyter(self) -> dict[str, Any]:
        """Check that an authenticated Jupyter server has a usable kernel."""
        url = os.environ.get("JUPYTER_URL", "").rstrip("/")
        token = os.environ.get("JUPYTER_TOKEN", "")
        if not url or not token:
            raise RuntimeError("JUPYTER_URL and JUPYTER_TOKEN are required")
        kernels = http_json(
            f"{url}/api/kernels", headers={"Authorization": f"token {token}"}
        )
        if kernels:
            return {"ok": True, "kernel_id": kernels[0]["id"]}
        kernel = http_json(
            f"{url}/api/kernels",
            method="POST",
            payload={"name": "python3"},
            headers={"Authorization": f"token {token}"},
        )
        return {"ok": True, "kernel_id": kernel["id"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sidekick OpenRouter agent")
    parser.add_argument("-p", "--prompt")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--set-key")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--calculate")
    parser.add_argument("--jupyter", action="store_true")
    args = parser.parse_args(argv)

    config = load_config()
    agent = Sidekick(config)

    if args.set_key:
        config["api_key"] = args.set_key
        save_config(config)
        print("API key saved securely.")
        return 0
    if args.clear:
        config["history"] = []
        save_config(config)
        print("Conversation history cleared.")
        return 0

    try:
        if args.calculate:
            print(calculate(args.calculate))
            return 0
        if args.jupyter:
            print(json.dumps(agent.jupyter(), indent=2))
            return 0
        if args.prompt:
            answer = agent.ask(args.prompt)
            print(json.dumps({"ok": True, "response": answer}, indent=2) if args.json else answer)
            return 0

        while True:
            try:
                prompt = input("you > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if prompt in {"/exit", "/quit"}:
                return 0
            if prompt == "/clear":
                config["history"] = []
                save_config(config)
                print("cleared")
            elif prompt:
                print("sidekick >", agent.ask(prompt))
    except (RuntimeError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
