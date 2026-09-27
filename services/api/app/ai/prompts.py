"""Loader for version-controlled prompt templates in /prompts.

Templates are Markdown files with a small front-matter block (id, version, task) and `# System` / `# User`
sections. Variables use `{{name}}` and are substituted literally (no code execution, no nested evaluation).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi (हिन्दी)"}
_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def prompts_dir() -> Path:
    env = os.environ.get("PROMPTS_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "prompts"
        if (candidate / "_shared_rules.md").exists():
            return candidate
    raise FileNotFoundError("prompts directory not found; set PROMPTS_DIR")


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: str
    task: str
    system: str
    user: str

    def render(self, **variables: object) -> tuple[str, str]:
        lang = str(variables.get("output_language", "en"))
        variables.setdefault("output_language_name", LANGUAGE_NAMES.get(lang, lang))
        rules = _VAR.sub(lambda m: str(variables.get(m.group(1), m.group(0))), _shared_rules())
        variables["shared_rules"] = rules

        def sub(text: str) -> str:
            # Single pass: substituted values (which may contain untrusted book text) are never re-expanded.
            return _VAR.sub(lambda m: str(variables.get(m.group(1), m.group(0))), text)

        return sub(self.system).strip(), sub(self.user).strip()


@lru_cache
def _shared_rules() -> str:
    raw = (prompts_dir() / "_shared_rules.md").read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()


@lru_cache
def load_prompt(prompt_id: str) -> PromptTemplate:
    for path in prompts_dir().rglob(f"{prompt_id}.md"):
        raw = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, flags=re.S)
        if not m:
            raise ValueError(f"prompt {prompt_id} is missing front matter")
        meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
        meta = {k.strip(): v.strip() for k, v in meta.items()}
        body = m.group(2)
        sys_m = re.search(r"^# System\n(.*?)(?=^# User\n)", body, flags=re.S | re.M)
        usr_m = re.search(r"^# User\n(.*)$", body, flags=re.S | re.M)
        if not sys_m or not usr_m:
            raise ValueError(f"prompt {prompt_id} must have # System and # User sections")
        return PromptTemplate(meta["id"], meta["version"], meta["task"], sys_m.group(1), usr_m.group(1))
    raise FileNotFoundError(f"prompt {prompt_id} not found")


def all_prompt_ids() -> list[str]:
    return sorted(p.stem for p in prompts_dir().rglob("*.md") if not p.name.startswith("_"))
