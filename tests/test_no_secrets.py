"""Fails if any file that git would track contains a secret.

Two checks:
1. Every non-empty value from the local .env file that looks secret (KEY/TOKEN/SECRET/URL with a password)
   must not appear in any trackable file.
2. Generic key patterns (HF tokens, Google API keys, 32-hex keys next to key-ish words) must not appear.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL)", re.I)
PATTERNS = [
    re.compile(r"hf_[A-Za-z0-9]{30,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|bearer)[\"'\s:=]+[0-9a-f]{32}\b"),
]
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".safetensors", ".bin", ".pdf"}


def trackable_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line and Path(line).suffix.lower() not in BINARY_SUFFIXES]


def env_secret_values() -> list[str]:
    env = ROOT / ".env"
    if not env.exists():
        return []
    values = []
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        value = value.split("#", 1)[0].strip().strip("\"'")
        if SECRET_NAME.search(name) and len(value) >= 12 and not value.startswith("sqlite"):
            values.append(value)
    return values


def test_env_file_is_ignored():
    res = subprocess.run(["git", "check-ignore", ".env"], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, ".env must be gitignored"


def test_no_env_secret_values_in_trackable_files():
    secrets = env_secret_values()
    leaks = []
    for f in trackable_files():
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except (IsADirectoryError, FileNotFoundError):
            continue
        leaks += [f"{f.relative_to(ROOT)}" for s in secrets if s in text]
    assert not leaks, f"secret values from .env found in: {sorted(set(leaks))}"


def test_no_key_patterns_in_trackable_files():
    hits = []
    for f in trackable_files():
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except (IsADirectoryError, FileNotFoundError):
            continue
        for p in PATTERNS:
            if p.search(text):
                hits.append(f"{f.relative_to(ROOT)}: {p.pattern}")
    assert not hits, f"key-like strings found: {hits}"
