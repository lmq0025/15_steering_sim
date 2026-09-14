"""Lifecycle contract shared by simulation components."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class ObservableComponent(ABC):
    """Separates state reset, truth observation, and sensor measurement."""

    @abstractmethod
    def reset(self, state: Any | None = None) -> Mapping[str, Any]:
        """Reset deterministic internal state and return a truth observation."""

    @abstractmethod
    def observe(self) -> Mapping[str, Any]:
        """Return noise-free truth and diagnostic values."""

    @abstractmethod
    def measure(self) -> Mapping[str, Any]:
        """Return the signals available to a controller or data acquisition layer."""

