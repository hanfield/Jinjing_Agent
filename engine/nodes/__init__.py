from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .guardrail import guardrail_node
    from .supervisor import supervisor_node, route_to_workers
    from .worker import make_worker_node
    from .summarizer import summarizer_node

def __getattr__(name: str):
    if name == "guardrail_node":
        from .guardrail import guardrail_node
        return guardrail_node
    elif name == "supervisor_node":
        from .supervisor import supervisor_node
        return supervisor_node
    elif name == "route_to_workers":
        from .supervisor import route_to_workers
        return route_to_workers
    elif name == "make_worker_node":
        from .worker import make_worker_node
        return make_worker_node
    elif name == "summarizer_node":
        from .summarizer import summarizer_node
        return summarizer_node
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "guardrail_node",
    "supervisor_node",
    "route_to_workers",
    "make_worker_node",
    "summarizer_node",
]
