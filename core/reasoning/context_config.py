#!/usr/bin/env python3
"""
Context Configuration
=====================
Configuration dataclass for context management system

Author: Dominion Labs
Version: 1.0
"""

import os
import warnings
from dataclasses import dataclass, field
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


def _from_env(name: str, default: T, cast: Callable[[str], T]) -> T:
    """Read one setting, falling back to `default` and SAYING SO.

    A malformed setting is silently replaced today, via `logging.warning`. The
    difference matters: a log line is a message, `warnings.warn` is a signal a
    caller can catch, escalate, or turn into an error. Falling back to a
    default without a catchable signal is how a process runs a whole session on
    a 4096 context window it was explicitly configured out of.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        warnings.warn(
            f"Invalid value for {name}: {raw!r}; using default {default!r}",
            UserWarning,
            stacklevel=3,
        )
        return default


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() == "true"


@dataclass
class ContextConfig:
    """Context management configuration.

    Every setting is resolved PER INSTANCE, via default_factory.

    These were previously computed in the class body, which runs exactly once
    at import. Anything that set CONTEXT_WINDOW_SIZE after this module was
    first imported -- a launcher reading .env, a worker configuring itself, a
    test -- was silently ignored, and the values here were whatever the
    environment happened to hold at import time. The bare `try/except ValueError`
    around each one could never fire either: the exception was raised while the
    class body executed, so an invalid setting was an import-time crash rather
    than the documented fallback.
    """

    # Compression settings
    compression_interval: int = field(
        default_factory=lambda: _from_env('CONTEXT_COMPRESSION_INTERVAL', 5, int))
    preserve_recent: int = field(
        default_factory=lambda: _from_env('CONTEXT_PRESERVE_RECENT', 3, int))
    target_compression_ratio: float = field(
        default_factory=lambda: _from_env('CONTEXT_COMPRESSION_RATIO', 0.5, float))

    # Token budget settings
    safety_margin: int = field(
        default_factory=lambda: _from_env('CONTEXT_SAFETY_MARGIN', 500, int))
    n_ctx: int = field(
        default_factory=lambda: _from_env('CONTEXT_WINDOW_SIZE', 4096, int))

    # Feature flags
    enable_auto_compression: bool = field(
        default_factory=lambda: _env_flag('ENABLE_AUTO_COMPRESSION'))
    enable_memory_storage: bool = field(
        default_factory=lambda: _env_flag('ENABLE_MEMORY_STORAGE'))
    enable_task_resumption: bool = field(
        default_factory=lambda: _env_flag('ENABLE_TASK_RESUMPTION'))

    # Performance settings
    compression_timeout_seconds: int = field(
        default_factory=lambda: _from_env('COMPRESSION_TIMEOUT', 30, int))
    max_compression_retries: int = field(
        default_factory=lambda: _from_env('MAX_COMPRESSION_RETRIES', 2, int))


    @classmethod
    def from_dict(cls, config_dict: dict) -> 'ContextConfig':
        """
        Create ContextConfig from dictionary

        Args:
            config_dict: Dictionary with configuration values

        Returns:
            ContextConfig instance
        """
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        """
        Convert to dictionary

        Returns:
            Dict with all configuration values
        """
        return {
            'compression_interval': self.compression_interval,
            'preserve_recent': self.preserve_recent,
            'target_compression_ratio': self.target_compression_ratio,
            'safety_margin': self.safety_margin,
            'n_ctx': self.n_ctx,
            'enable_auto_compression': self.enable_auto_compression,
            'enable_memory_storage': self.enable_memory_storage,
            'enable_task_resumption': self.enable_task_resumption,
            'compression_timeout_seconds': self.compression_timeout_seconds,
            'max_compression_retries': self.max_compression_retries
        }


# Default configuration instance
DEFAULT_CONFIG = ContextConfig()
