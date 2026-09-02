"""Canonical design-pattern implementations owned by the tools.

Each entry is a correct, runnable Python implementation of a Gang-of-Four
pattern (not a stub, not model output). ``generate_design_pattern`` looks a
pattern up here; an unknown name returns the list of what is available.
"""
from __future__ import annotations

from typing import Dict, List, Optional

PATTERNS: Dict[str, dict] = {
    "singleton": {
        "aliases": ["single instance"],
        "intent": "Ensure a class has only one instance and provide a global access point.",
        "code": '''class Singleton:
    """Only one instance ever exists; construction returns the same object."""
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
''',
    },
    "observer": {
        "aliases": ["publish subscribe", "pub sub", "pubsub"],
        "intent": "Notify a set of dependents automatically when a subject changes.",
        "code": '''class Subject:
    """Maintains observers and notifies them of state changes."""

    def __init__(self):
        self._observers = []

    def subscribe(self, observer):
        if observer not in self._observers:
            self._observers.append(observer)

    def unsubscribe(self, observer):
        if observer in self._observers:
            self._observers.remove(observer)

    def notify(self, *args, **kwargs):
        for observer in list(self._observers):
            observer.update(*args, **kwargs)


class Observer:
    """Reacts to notifications from a Subject."""

    def update(self, *args, **kwargs):
        raise NotImplementedError("an Observer must define update()")
''',
    },
    "factory": {
        "aliases": ["factory method", "simple factory"],
        "intent": "Create objects without exposing the instantiation logic to the caller.",
        "code": '''class Factory:
    """Registers creators by key and builds products on request."""

    def __init__(self):
        self._creators = {}

    def register(self, key, creator):
        self._creators[key] = creator

    def create(self, key, *args, **kwargs):
        creator = self._creators.get(key)
        if creator is None:
            raise ValueError(f"no creator registered for {key!r}")
        return creator(*args, **kwargs)
''',
    },
    "strategy": {
        "aliases": ["policy"],
        "intent": "Encapsulate interchangeable algorithms behind a common call.",
        "code": '''class Context:
    """Runs whichever strategy (a callable) it currently holds."""

    def __init__(self, strategy):
        self._strategy = strategy

    def set_strategy(self, strategy):
        self._strategy = strategy

    def execute(self, *args, **kwargs):
        return self._strategy(*args, **kwargs)
''',
    },
    "decorator": {
        "aliases": ["wrapper"],
        "intent": "Attach responsibilities to an object dynamically by wrapping it.",
        "code": '''class Component:
    """The interface being decorated."""

    def operation(self):
        raise NotImplementedError


class ConcreteComponent(Component):
    def operation(self):
        return "base"


class Decorator(Component):
    """Wraps a component and can augment its behavior."""

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def operation(self):
        return self._wrapped.operation()


class UpperDecorator(Decorator):
    def operation(self):
        return self._wrapped.operation().upper()
''',
    },
    "adapter": {
        "aliases": ["wrapper adapter"],
        "intent": "Let an incompatible interface be used through an expected one.",
        "code": '''class Adapter:
    """Adapts an adaptee's method to the target interface `request()`."""

    def __init__(self, adaptee, method_name):
        self._adaptee = adaptee
        self._method_name = method_name

    def request(self, *args, **kwargs):
        return getattr(self._adaptee, self._method_name)(*args, **kwargs)
''',
    },
    "builder": {
        "aliases": ["fluent builder"],
        "intent": "Construct a complex object step by step with a fluent interface.",
        "code": '''class Builder:
    """Accumulates parts, then builds the final product dict."""

    def __init__(self):
        self._parts = {}

    def set(self, key, value):
        self._parts[key] = value
        return self  # fluent

    def build(self):
        return dict(self._parts)
''',
    },
    "command": {
        "aliases": ["action", "transaction"],
        "intent": "Encapsulate a request as an object, allowing queueing and undo.",
        "code": '''class Invoker:
    """Stores and executes commands (callables), keeping a history."""

    def __init__(self):
        self._history = []

    def run(self, command, *args, **kwargs):
        result = command(*args, **kwargs)
        self._history.append((command, args, kwargs))
        return result

    def history(self):
        return list(self._history)
''',
    },
}


def _norm(name: str) -> str:
    cleaned = name.lower().strip().replace("_", " ")
    return "".join(ch for ch in cleaned if ch.isalnum() or ch == " ").strip()


def lookup(name: str) -> Optional[dict]:
    key = _norm(name)
    compact = key.replace(" ", "_")
    for canonical, entry in PATTERNS.items():
        if compact == canonical or key == canonical:
            return {"name": canonical, **entry}
        for alias in entry.get("aliases", []):
            if key == _norm(alias):
                return {"name": canonical, **entry}
    return None


def available() -> List[str]:
    return sorted(PATTERNS)
