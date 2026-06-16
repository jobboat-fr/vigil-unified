"""Safe strategy loader for mcp-algo.

Loads WinnyStrategy subclasses by dotted path from user input. The MCP server
accepts strategy specs over the wire — that's user-controlled input, so we
restrict imports to a known-safe namespace.

Allowed: winny.strategies.<anything>:<ClassName>
Rejected: anything else, including absolute or relative escapes.

This is defense-in-depth — the MCP server is invoked by Hermes which is invoked
by the user, so in theory the user can do anything they want anyway. But the
restriction means a typo or a compromised LLM cannot import arbitrary code
through the backtest tool surface.
"""

from __future__ import annotations

import importlib

from winny.common.errors import WinnyValidationError
from winny.engine.strategy import WinnyStrategy

ALLOWED_PREFIX = "winny.strategies."


def load_strategy_class(spec: str) -> type[WinnyStrategy]:
    """Load a WinnyStrategy subclass from a 'module:ClassName' spec.

    Args:
        spec: string of the form "winny.strategies.buy_and_hold:BuyAndHold".

    Returns:
        The strategy class (not an instance — caller constructs).

    Raises:
        WinnyValidationError: spec is malformed, namespace-disallowed,
            module not importable, class not found, or class is not a
            WinnyStrategy subclass.
    """
    if not isinstance(spec, str) or ":" not in spec:
        raise WinnyValidationError(f"strategy spec must be 'module:ClassName', got {spec!r}")
    module_path, class_name = spec.split(":", 1)
    module_path = module_path.strip()
    class_name = class_name.strip()

    if not module_path.startswith(ALLOWED_PREFIX):
        raise WinnyValidationError(
            f"strategy module must be in {ALLOWED_PREFIX}* namespace; got {module_path!r}"
        )
    if ".." in module_path or module_path.startswith("."):
        raise WinnyValidationError(f"relative imports rejected: {module_path!r}")
    if not class_name.isidentifier():
        raise WinnyValidationError(f"invalid class name: {class_name!r}")

    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise WinnyValidationError(f"cannot import strategy module {module_path!r}: {e}") from e

    cls = getattr(module, class_name, None)
    if cls is None:
        raise WinnyValidationError(f"class {class_name!r} not found in {module_path!r}")
    if not isinstance(cls, type) or not issubclass(cls, WinnyStrategy):
        raise WinnyValidationError(f"{spec!r} is not a WinnyStrategy subclass (got {cls!r})")
    return cls
