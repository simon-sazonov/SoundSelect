"""The step runner: a pipeline is a fixed chain of named steps, each saving its output.

Every step's output is stored under a fingerprint made of the step's name and version and the
fingerprints of what it reads. Running again with the same input reuses saved outputs; a
correction or an improved step (a new version) re-runs only that step and what comes after it.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, TypeAdapter
from pydantic_core import to_json


class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...

    def put(self, key: str, value: Any) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self.items: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self.items.get(key)

    def put(self, key: str, value: Any) -> None:
        self.items[key] = value


class DirCache:
    """Saved outputs as JSON files in a folder (the library database takes over in Phase 1)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.root / digest[:2] / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, key: str, value: Any) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def fingerprint_of(value: Any) -> str:
    """A stable fingerprint for a step input or output."""
    fp = getattr(value, "fingerprint", None)
    if callable(fp):
        return fp("input")
    data = value.model_dump_json().encode() if isinstance(value, BaseModel) else to_json(value)
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Step:
    """One step: ``run`` is called with the values named in ``needs``, in that order."""

    name: str
    version: str
    needs: tuple[str, ...]
    run: Callable[..., Any]
    output: Any  # the output type, used to restore saved outputs


@dataclass(frozen=True)
class StepRecord:
    name: str
    fingerprint: str
    cached: bool
    seconds: float


@dataclass
class RunResult:
    outputs: dict[str, Any]
    records: list[StepRecord] = field(default_factory=list)

    @property
    def ran(self) -> list[str]:
        """Names of the steps that actually ran (the others came from saved outputs)."""
        return [r.name for r in self.records if not r.cached]

    def __getitem__(self, name: str) -> Any:
        return self.outputs[name]


StepEvent = Callable[[str, str, int, int], None]
"""Called as (step name, 'start' or 'done', step number from 1, number of steps)."""


class Pipeline:
    def __init__(self, name: str, steps: list[Step]) -> None:
        names = [s.name for s in steps]
        if len(set(names)) != len(names):
            raise ValueError("step names must be unique")
        self.name = name
        self.steps = steps
        self._adapters = {s.name: TypeAdapter(s.output) for s in steps}

    @property
    def versions(self) -> dict[str, str]:
        return {s.name: s.version for s in self.steps}

    def run(
        self,
        inputs: Mapping[str, Any],
        *,
        cache: Cache | None = None,
        on_step: StepEvent | None = None,
    ) -> RunResult:
        values: dict[str, Any] = dict(inputs)
        prints: dict[str, str] = {k: fingerprint_of(v) for k, v in inputs.items()}
        result = RunResult(outputs={})
        total = len(self.steps)
        for number, step in enumerate(self.steps, start=1):
            missing = [n for n in step.needs if n not in values]
            if missing:
                raise KeyError(f"step {step.name!r} needs {missing}")
            parts = [self.name, step.name, step.version, *(prints[n] for n in step.needs)]
            fp = hashlib.sha256(json.dumps(parts).encode()).hexdigest()
            key = f"{self.name}/{step.name}/{fp}"
            if on_step:
                on_step(step.name, "start", number, total)
            started = time.perf_counter()
            saved = cache.get(key) if cache is not None else None
            adapter = self._adapters[step.name]
            if saved is not None:
                output = adapter.validate_python(saved["value"])
                cached = True
            else:
                output = step.run(*(values[n] for n in step.needs))
                if cache is not None:
                    cache.put(key, {"value": adapter.dump_python(output, mode="json")})
                cached = False
            values[step.name] = output
            prints[step.name] = fp
            result.outputs[step.name] = output
            result.records.append(
                StepRecord(step.name, fp, cached, round(time.perf_counter() - started, 4))
            )
            if on_step:
                on_step(step.name, "done", number, total)
        return result
