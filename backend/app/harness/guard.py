"""GUARD step: input limits and prompt-injection heuristics. Email text is untrusted DATA.

Injection detection never blocks the email (a real customer may paste odd text); it raises the
`prompt_injection_suspected` flag shown in the UI and forces human review. Prices can't be affected anyway:
they come only from the pricing tool.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

INJECTION_PATTERNS = [
    (r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your)\b[^.\n]{0,20}"
     r"\b(instructions?|prompts?|rules|task)\b", "ignore-instructions"),
    (r"\b(system|developer)\s*(instruction|override|prompt|message|note)s?\b", "fake system message"),
    (r"\byou are now\b|\bact as\b|\bnew instructions\b|\bfrom now on\b", "role change"),
    (r"\b(ai|llm|gpt|assistant|bot|model|parser|automated)\b[^.\n]{0,30}\b(ignore|apply|append|add|mark|respond|"
     r"output|authoriz|approve|set)", "addressed to the AI"),
    (r"^\s*(assistant|system)\s*:", "role prefix"),
    (r"<!--|-->|\[\[|\]\]|\{\{|\}\}", "hidden markup"),
    (r"\b(respond|reply|answer|output)\s+only\s+with\b", "output hijack"),
    (r"\b\d{1,3}\s*%\s*(off|discount)\b|\bdiscount of \d{1,3}\s*%|\bapply (a |an |the )?\d{1,3}\s*%", "discount demand"),
    (r"\bat \$\s?0\b|\bfree of charge\b|\bat no (charge|cost)\b|\b\$1 each\b|\bevery item at \$", "price manipulation"),
    (r"\bmark (the )?(order|quote) (as )?(approved|paid)\b", "approval hijack"),
]
_COMPILED = [(re.compile(p, re.I | re.M), label) for p, label in INJECTION_PATTERNS]


@dataclass
class GuardResult:
    ok: bool
    injection_suspected: bool
    matches: list[dict] = field(default_factory=list)
    error: str | None = None


def check(body: str, subject: str, max_chars: int) -> GuardResult:
    if not body or not body.strip():
        return GuardResult(ok=False, injection_suspected=False, error="empty email")
    if len(body) > max_chars:
        return GuardResult(ok=False, injection_suspected=False,
                           error=f"email too long ({len(body)} chars, max {max_chars})")
    matches = []
    for rx, label in _COMPILED:
        for m in rx.finditer(f"{subject}\n{body}"):
            snippet = m.group(0).strip()
            matches.append({"rule": label, "text": snippet[:80]})
            break
    return GuardResult(ok=True, injection_suspected=bool(matches), matches=matches)
