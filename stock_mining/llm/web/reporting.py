from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class WebFetchReporter:
    """Collect non-fatal fetch warnings; never raises to callers."""

    on_warning: Callable[[str], None] | None = None
    warnings: list[str] = field(default_factory=list)

    def warn(self, source: str, exc: BaseException) -> None:
        message = f"[web-search] {source} 失败: {type(exc).__name__}: {exc}"
        self.warnings.append(message)
        if self.on_warning is not None:
            self.on_warning(message)
