#!/usr/bin/env python3
"""
hook_dispatcher.py — Centralized hook lifecycle dispatcher

Provides a single entry point for firing lifecycle events across all
registered hooks, replacing manual per-callsite wiring.

Lifecycle events:
- "pre_dispatch"         — before a task is dispatched
- "post_completion"      — after a task completes
- "pre_reply"            — before the agent replies
- "on_error"             — when an error occurs
- "post_batch_complete"  — after all tasks in a batch finish

Usage:
```python
from hooks.hook_dispatcher import get_dispatcher, HookResult

d = get_dispatcher()
d.register("pre_reply", my_check_fn, priority=10)
results = d.fire("pre_reply", {"task_id": "t1", "message": "..."})

for r in results:
    if r.action == "block":
        raise RuntimeError(r.reason)
```
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .hook_config import get_hook_enforce_mode
from .hook_exceptions import HookViolationError

__all__ = [
    "HookResult",
    "HookDispatcher",
    "get_dispatcher",
]

logger = logging.getLogger(__name__)

# Supported lifecycle events
LIFECYCLE_EVENTS = frozenset([
    "pre_dispatch",
    "post_completion",
    "pre_reply",
    "on_error",
    "post_batch_complete",
])


@dataclass
class HookResult:
    """Result returned by a hook function.

    Attributes:
        action: "continue" (no-op), "block" (reject), or "modify" (mutate context).
        reason: Human-readable explanation.
        metadata: Arbitrary extra data the hook wants to surface.
    """
    action: str = "continue"   # "continue" | "block" | "modify"
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# Type alias for a registered hook callable.
# Signature: (event: str, context: Dict[str, Any]) -> HookResult
HookFn = Callable[[str, Dict[str, Any]], HookResult]


class HookDispatcher:
    """Centralized dispatcher that manages hook registration and firing.

    Hooks are registered against named lifecycle events and executed in
    priority order (lower number = higher priority).  The dispatcher
    respects the 3-tier enforce mode from ``hook_config``:

    - **audit**: log a violation but always continue.
    - **warn**: log a warning but always continue.
    - **enforce**: raise ``HookViolationError`` when a hook returns "block".

    A hook that raises an exception is caught, logged, and skipped so
    that hooks never break the main orchestration flow.
    """

    def __init__(self) -> None:
        # event -> list of (priority, name, hook_fn)
        self._hooks: Dict[str, List[Tuple[int, str, HookFn]]] = {
            event: [] for event in LIFECYCLE_EVENTS
        }

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        event: str,
        hook_fn: HookFn,
        priority: int = 0,
        name: Optional[str] = None,
    ) -> None:
        """Register *hook_fn* to run when *event* fires.

        Args:
            event: One of the supported lifecycle event names.
            hook_fn: Callable ``(event, context) -> HookResult``.
            priority: Lower runs first.  Default ``0``.
            name: Optional human-readable label (defaults to function name).
        """
        if event not in LIFECYCLE_EVENTS:
            raise ValueError(
                f"Unknown event {event!r}. "
                f"Supported: {sorted(LIFECYCLE_EVENTS)}"
            )
        hook_name = name or getattr(hook_fn, "__name__", repr(hook_fn))
        self._hooks[event].append((priority, hook_name, hook_fn))
        # Keep sorted by priority (stable sort preserves insertion order
        # among equal priorities).
        self._hooks[event].sort(key=lambda t: t[0])
        logger.debug("Registered hook %r on %r (priority=%d)", hook_name, event, priority)

    # ------------------------------------------------------------------
    # Firing
    # ------------------------------------------------------------------

    def fire(self, event: str, context: Dict[str, Any]) -> List[HookResult]:
        """Fire all hooks registered for *event*.

        Hooks run in priority order.  Each receives ``(event, context)``
        and must return a ``HookResult``.

        Enforce-mode handling for ``"block"`` results:

        - **audit** — log and continue.
        - **warn** — emit a warning log and continue.
        - **enforce** — raise ``HookViolationError``.

        If a hook raises an unexpected exception it is logged and skipped.

        Returns:
            List of ``HookResult`` objects (one per registered hook).
        """
        if event not in LIFECYCLE_EVENTS:
            logger.warning("fire() called with unknown event %r — ignored", event)
            return []

        results: List[HookResult] = []
        for _priority, hook_name, hook_fn in self._hooks[event]:
            try:
                result = hook_fn(event, context)
                if not isinstance(result, HookResult):
                    # Gracefully wrap unexpected return values.
                    result = HookResult(
                        action="continue",
                        reason=f"Hook {hook_name!r} returned non-HookResult; treated as continue",
                    )
            except Exception as exc:
                logger.error(
                    "Hook %r on event %r raised %s: %s — skipping",
                    hook_name, event, type(exc).__name__, exc,
                )
                results.append(HookResult(
                    action="continue",
                    reason=f"Hook {hook_name!r} raised {type(exc).__name__}: {exc}",
                    metadata={"error": True},
                ))
                continue

            # Enforce-mode gate for "block" results.
            if result.action == "block":
                mode = get_hook_enforce_mode(hook_name)
                if mode == "enforce":
                    raise HookViolationError(
                        message=result.reason or f"Hook {hook_name!r} blocked on {event!r}",
                        hook_name=hook_name,
                        metadata=result.metadata,
                    )
                elif mode == "warn":
                    logger.warning(
                        "Hook %r wants to block %r (warn mode): %s",
                        hook_name, event, result.reason,
                    )
                else:
                    # audit — just log
                    logger.info(
                        "Hook %r wants to block %r (audit mode): %s",
                        hook_name, event, result.reason,
                    )

            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def list_events(self) -> List[str]:
        """Return sorted list of supported lifecycle event names."""
        return sorted(LIFECYCLE_EVENTS)

    def list_hooks(self, event: Optional[str] = None) -> Dict[str, List[str]]:
        """Return registered hook names, optionally filtered by event."""
        if event:
            entries = self._hooks.get(event, [])
            return {event: [name for _, name, _ in entries]}
        return {
            ev: [name for _, name, _ in entries]
            for ev, entries in self._hooks.items()
            if entries
        }

    def clear(self, event: Optional[str] = None) -> None:
        """Remove all hooks, optionally only for a specific event."""
        if event:
            if event in self._hooks:
                self._hooks[event] = []
        else:
            for ev in self._hooks:
                self._hooks[ev] = []


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_dispatcher: Optional[HookDispatcher] = None


def get_dispatcher() -> HookDispatcher:
    """Return the global ``HookDispatcher`` singleton (created on first call)."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = HookDispatcher()
    return _dispatcher


def _reset_dispatcher() -> None:
    """Reset the singleton (testing only)."""
    global _dispatcher
    _dispatcher = None
