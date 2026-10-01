"""QuoteDesk shared library: schema, prompts, normalizers, metrics. Used by datagen, notebook, backend, eval."""
from .schema import Extraction, LineItem, parse_extraction, semantic_errors, to_target_json  # noqa: F401
from .prompt import chat_messages, system_prompt, teacher_system_prompt, user_message  # noqa: F401

__version__ = "1.0.0"
