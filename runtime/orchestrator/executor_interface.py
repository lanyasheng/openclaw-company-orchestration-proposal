"""Pluggable executor interface for multi-agent architecture support.

Defines an abstract base for task executors, allowing the orchestrator
to work with different agent backends: SubagentExecutor (OpenClaw native),
LangChain agents, CrewAI crews, custom HTTP workers, etc.

Usage:
    class MyCustomExecutor(TaskExecutorBase):
        def execute(self, task_id, label, context):
            # Start your agent/worker
            return "handle_123"

        def poll(self, handle):
            # Check if done
            return TaskResult(status="completed", output="done")

    # Register in BatchExecutor:
    executor = BatchExecutor(workspace_dir=".", executor_factory=MyCustomExecutor)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


TaskResultStatus = Literal["pending", "running", "completed", "failed", "timed_out"]


@dataclass
class TaskResult:
    status: TaskResultStatus
    output: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class TaskExecutorBase(ABC):
    """Abstract base for all task executors.

    Subclass this to integrate any agent backend into the orchestrator.
    The orchestrator calls `execute` to start a task and `poll` to check status.
    """

    @abstractmethod
    def execute(self, task_id: str, label: str, context: Dict[str, Any]) -> str:
        """Start task execution. Returns an opaque handle string."""
        ...

    @abstractmethod
    def poll(self, handle: str) -> TaskResult:
        """Poll task status. Returns current state."""
        ...

    def cancel(self, handle: str) -> bool:
        """Cancel a running task. Override if supported."""
        return False

    def cleanup(self, handle: str) -> None:
        """Clean up resources after task completion. Override if needed."""
        pass


class SubagentTaskExecutor(TaskExecutorBase):
    """Default executor using SubagentExecutor."""

    def __init__(self, workspace_dir: str, timeout_seconds: int = 900):
        from subagent_executor import SubagentExecutor, SubagentConfig
        config = SubagentConfig(
            label="batch-task",
            runtime="subagent",
            timeout_seconds=timeout_seconds,
        )
        self._executor = SubagentExecutor(config=config, cwd=workspace_dir)

    def execute(self, task_id: str, label: str, context: Dict[str, Any]) -> str:
        return self._executor.execute_async(label, task_id=task_id)

    def poll(self, handle: str) -> TaskResult:
        result = self._executor.get_result(handle)
        if result is None:
            return TaskResult(status="pending")

        from subagent_executor import TERMINAL_STATES
        if result.status in TERMINAL_STATES:
            if result.status == "completed":
                return TaskResult(status="completed", output=result.result)
            return TaskResult(status="failed", error=result.error or result.status)
        return TaskResult(status="running")

    def cancel(self, handle: str) -> bool:
        return self._executor.cancel(handle)

    def cleanup(self, handle: str) -> None:
        self._executor.cleanup(handle)


class HttpWorkerExecutor(TaskExecutorBase):
    """Example executor that dispatches tasks to HTTP workers.

    Not implemented — provided as a template for custom integrations.
    """

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url
        self.api_key = api_key

    def execute(self, task_id: str, label: str, context: Dict[str, Any]) -> str:
        raise NotImplementedError(
            "HttpWorkerExecutor is a template. "
            "Implement execute() with your HTTP API calls."
        )

    def poll(self, handle: str) -> TaskResult:
        raise NotImplementedError(
            "HttpWorkerExecutor is a template. "
            "Implement poll() with your HTTP API calls."
        )
