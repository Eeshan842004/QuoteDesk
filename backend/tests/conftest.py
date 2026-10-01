"""Backend test fixtures: isolated SQLite DB, fake student and teacher (no network, no model download)."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
_tmp = tempfile.mkdtemp(prefix="qd_test_")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "LOAD_STUDENT_ON_STARTUP": "false",
    "ADMIN_TOKEN": "test-admin-token",
    "TEACHER_LIVE_MODE": "admin_only",
    "ROUTER_CONFIDENCE_THRESHOLD": "0.8",
    "RATE_LIMIT": "1000/minute",
    "KIE_API_KEY": "test-key-not-real",
    "HF_MODEL_REPO": "",
    "STUDENT_ADAPTER_REVISION": "",
    "QD_WORK_DIR": f"{_tmp}/work",
})

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import init_db  # noqa: E402
from app.models.student import StudentOutput  # noqa: E402

ADMIN = {"X-Admin-Token": "test-admin-token"}


def ext(intent="quote_request", items=(), urgency="normal", needed_by=None, missing=()):
    return {"intent": intent, "urgency": urgency, "needed_by": needed_by, "items": list(items),
            "missing_info": list(missing)}


def item(description, quantity=None, unit=None, part_number=None, compatible_with=None, reference=None):
    return {"description": description, "quantity": quantity, "unit": unit, "part_number": part_number,
            "compatible_with": compatible_with, "reference": reference}


class FakeStudent:
    """Returns queued outputs (text, mean_logprob) in order; repeats the last one."""
    version = "vtest"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def generate(self, messages, max_new_tokens=None):
        text, lp = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return StudentOutput(text=text if isinstance(text, str) else json.dumps(text), mean_logprob=lp,
                             min_token_prob=0.5, n_tokens=60, prompt_tokens=200, latency_s=0.01)


@pytest.fixture(autouse=True)
def _db():
    init_db()
    yield


@pytest.fixture
def student(monkeypatch):
    from app.models import registry as reg_mod

    def install(outputs):
        fake = FakeStudent(outputs)
        r = reg_mod.get_registry()
        monkeypatch.setattr(r, "model", fake)
        monkeypatch.setattr(r, "state", "ready")
        monkeypatch.setattr(r, "version", "vtest")
        return fake
    return install


@pytest.fixture
def teacher(monkeypatch):
    from app.models.teacher import TeacherOutput, get_teacher

    t = get_teacher()
    state = {"calls": 0, "fail": False, "output": None}

    def fake_extract(sender, subject, body, deadline_s):
        state["calls"] += 1
        if state["fail"]:
            from evallib.llm import LLMError
            raise LLMError("simulated 524 from KIE")
        return TeacherOutput(text=json.dumps(state["output"]), prompt_tokens=900, output_tokens=200,
                             cost_usd=0.0015, credits=0.08, latency_s=0.02, cached=False, model="fake-teacher")

    monkeypatch.setattr(t, "extract", fake_extract)
    monkeypatch.setattr(type(t), "configured", property(lambda self: True))
    return state


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app
    with TestClient(create_app(load_student=False)) as c:
        yield c
