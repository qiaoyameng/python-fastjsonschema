from .exceptions import JsonSchemaDefinitionException


def _check_limit(name, value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JsonSchemaDefinitionException(
            '{} must be a non-negative integer or None'.format(name),
        )
    return value


class ValidationBudget:
    """
    Optional limits for a single validation run, passed to
    :any:`fastjsonschema.compile` as the ``budget`` parameter:

     * ``max_depth`` limits depth of the currently validated data path
       (the root value has depth 0, its direct children depth 1, ...),
     * ``max_nodes`` limits the total number of visited data nodes
     * and ``max_errors`` limits the cumulative number of validation errors.

    Counters are shared between functions generated for ``$ref`` and between
    composition branches, so a recursive schema cannot escape the budget.
    When a limit is exceeded, :any:`JsonSchemaBudgetExceededException` is
    raised. Every validation call gets a fresh set of counters, so a compiled
    validator can be safely shared between threads.
    """

    __slots__ = ('max_depth', 'max_nodes', 'max_errors')

    def __init__(self, max_depth=None, max_nodes=None, max_errors=None):
        self.max_depth = _check_limit('max_depth', max_depth)
        self.max_nodes = _check_limit('max_nodes', max_nodes)
        self.max_errors = _check_limit('max_errors', max_errors)

    def __repr__(self):
        return 'ValidationBudget(max_depth={!r}, max_nodes={!r}, max_errors={!r})'.format(
            self.max_depth, self.max_nodes, self.max_errors,
        )


class BudgetState:
    """
    Mutable per-call counters referenced from generated validation code.
    A fresh instance is created for every validation call, so concurrent
    calls of the same validator never share counters.
    """

    __slots__ = ('max_depth', 'max_nodes', 'max_errors', 'depth', 'nodes', 'errors')

    def __init__(self, max_depth=None, max_nodes=None, max_errors=None):
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.max_errors = max_errors
        self.depth = 0
        self.nodes = 0
        self.errors = 0

    def __repr__(self):
        return (
            'BudgetState(max_depth={!r}, max_nodes={!r}, max_errors={!r}, '
            'depth={!r}, nodes={!r}, errors={!r})'
        ).format(
            self.max_depth, self.max_nodes, self.max_errors,
            self.depth, self.nodes, self.errors,
        )
