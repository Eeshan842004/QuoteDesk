"""Prompt construction. The ONLY place prompts are defined, so training and inference stay identical."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def system_prompt() -> str:
    """Short, fixed system prompt used for the student at training AND inference time."""
    return (_HERE / "system_prompt.txt").read_text(encoding="utf-8").strip()


@lru_cache(maxsize=None)
def teacher_system_prompt() -> str:
    """Student prompt + explicit labeling rules. Used for the teacher, the datagen verifier, and escalation."""
    rules = (_HERE / "teacher_rules.txt").read_text(encoding="utf-8").strip()
    return f"{system_prompt()}\n\n{rules}"


def user_message(sender: str, subject: str, body: str) -> str:
    """The user turn. The email is delimited so the model treats it as data, not instructions."""
    body = body.replace("</email>", "</ email>")  # prevent delimiter spoofing
    return f"From: {sender}\nSubject: {subject}\n\n<email>\n{body.strip()}\n</email>"


def chat_messages(sender: str, subject: str, body: str, target_json: str | None = None) -> list[dict]:
    """Chat-format messages. With target_json it is a training example; without, an inference prompt."""
    msgs = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_message(sender, subject, body)},
    ]
    if target_json is not None:
        msgs.append({"role": "assistant", "content": target_json})
    return msgs


def fewshot_messages(examples: list[dict], sender: str, subject: str, body: str) -> list[dict]:
    """Base-model baseline: same system prompt + k worked examples as prior turns."""
    msgs = [{"role": "system", "content": system_prompt()}]
    for ex in examples:
        msgs.append({"role": "user", "content": user_message(ex["sender"], ex["subject"], ex["body"])})
        msgs.append({"role": "assistant", "content": ex["target"]})
    msgs.append({"role": "user", "content": user_message(sender, subject, body)})
    return msgs
