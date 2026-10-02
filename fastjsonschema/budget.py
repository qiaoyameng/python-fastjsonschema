from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType

from .exceptions import JsonSchemaBudgetExceeded, JsonSchemaValueException


@dataclass(frozen=True)
class ValidationBudget:
    """Limits applied during a single validator call."""

    max_depth: int | None = None
    max_nodes: int | None = None
    max_errors: int | None = None

    def __post_init__(self) -> None:
        for name in ('max_depth', 'max_nodes', 'max_errors'):
            value = getattr(self, name)
            if (
                value is not None
                and (not isinstance(value, int) or isinstance(value, bool) or value < 1)
            ):
                raise ValueError(f'{name} must be a positive integer or None')


class _ValidationState:
    __slots__ = ('budget', 'depth', 'nodes', 'errors')

    def __init__(self, budget: ValidationBudget) -> None:
        self.budget = budget
        self.depth = 0
        self.nodes = 0
        self.errors = 0

    def enter_root(self) -> None:
        self.depth = 1
        self.nodes = 1
        self._check_limit('depth')
        self._check_limit('nodes')

    def enter_ref(self) -> None:
        self.nodes += 1
        self._check_limit('nodes')

    def enter_child(self) -> None:
        self.depth += 1
        self._check_limit('depth')
        self.nodes += 1
        self._check_limit('nodes')

    def enter_ref_child(self) -> None:
        self.depth += 1
        self._check_limit('depth')

    def exit_child(self) -> None:
        self.depth -= 1

    def child(self) -> "_ChildBudgetContext":
        return _ChildBudgetContext(self)

    def ref_child(self) -> "_RefChildBudgetContext":
        return _RefChildBudgetContext(self)

    def error(self, error: JsonSchemaValueException) -> JsonSchemaValueException:
        self.errors += 1
        self._check_limit('errors')
        return error

    def _exceeded(self, kind: str) -> JsonSchemaBudgetExceeded:
        labels = {
            'depth': 'data path depth',
            'nodes': 'visited data nodes',
            'errors': 'validation errors',
        }
        limit = getattr(self.budget, f'max_{kind}')
        used = getattr(self, 'errors' if kind == 'errors' else kind)
        return JsonSchemaBudgetExceeded(
            f'validation budget for {labels[kind]} exceeded: {used} > {limit}',
            kind=kind,
            limit=limit,
            used=used,
            depth=self.depth,
            nodes=self.nodes,
            errors=self.errors,
            budget=self.budget,
        )

    def _check_limit(self, kind: str) -> None:
        limit = getattr(self.budget, f'max_{kind}')
        used = getattr(self, 'errors' if kind == 'errors' else kind)
        if limit is not None and used > limit:
            raise self._exceeded(kind)


class _ChildBudgetContext:
    __slots__ = ('state',)

    def __init__(self, state: _ValidationState) -> None:
        self.state = state

    def __enter__(self) -> "_ChildBudgetContext":
        self.state.enter_child()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.state.exit_child()
        return False


class _RefChildBudgetContext:
    __slots__ = ('state',)

    def __init__(self, state: _ValidationState) -> None:
        self.state = state

    def __enter__(self) -> "_RefChildBudgetContext":
        self.state.enter_ref_child()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.state.exit_child()
        return False
