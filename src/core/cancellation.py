"""Cooperative cancellation token for streaming evaluation."""


class CancellationToken:
    """Simple shared signal between producer (MCP tool caller) and consumer (evaluator).

    Thread-safe for single-threaded async use. Producer checks is_cancelled
    before each tool call; consumer calls cancel() when early exit triggers.
    """

    def __init__(self):
        self._cancelled = False
        self._reason = ""

    def cancel(self, reason: str = ""):
        self._cancelled = True
        self._reason = reason

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason
