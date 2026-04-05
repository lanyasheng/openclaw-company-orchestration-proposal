from __future__ import annotations

import re
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .scheduler import StepContext

_TEMPLATE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def render_context_value(value: Any, context: "StepContext") -> Any:
    if isinstance(value, str):
        return render_context_string(value, context)
    if isinstance(value, list):
        return [render_context_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_context_value(item, context) for key, item in value.items()}
    return value


def render_context_string(template: str, context: "StepContext") -> str:
    def replace(match: re.Match[str]) -> str:
        resolved = resolve_context_path(match.group(1), context)
        if resolved is None:
            return ""
        return str(resolved)

    return _TEMPLATE_RE.sub(replace, template)


def resolve_context_path(path: str, context: "StepContext") -> Any:
    path = path.strip()
    roots: Dict[str, Any] = {
        "request": context.request,
        "signal": context.signal or {},
        "steps": context.step_outputs,
        "record": context.record,
        "workflow": context.workflow,
    }
    segments = path.split(".")
    root = roots.get(segments[0])
    if root is None:
        return None
    current: Any = root
    for segment in segments[1:]:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current
