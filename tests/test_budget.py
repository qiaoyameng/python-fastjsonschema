from concurrent.futures import ThreadPoolExecutor

import pytest

from fastjsonschema import (
    JsonSchemaBudgetExceededException,
    JsonSchemaDefinitionException,
    JsonSchemaException,
    JsonSchemaValueException,
    JsonSchemaValuesException,
    ValidationBudget,
    compile,
    compile_to_code,
    validate,
)


RECURSIVE_SCHEMA = {
    'type': 'object',
    'properties': {'next': {'$ref': '#'}},
    'additionalProperties': False,
}


def deep_value(depth):
    value = {}
    current = value
    for _ in range(depth):
        current['next'] = {}
        current = current['next']
    return value


def test_budget_exception_is_not_a_validation_error():
    assert issubclass(JsonSchemaBudgetExceededException, JsonSchemaException)
    assert not issubclass(JsonSchemaBudgetExceededException, JsonSchemaValueException)
    assert not issubclass(JsonSchemaBudgetExceededException, JsonSchemaValuesException)


@pytest.mark.parametrize('limit', [
    {'max_depth': -1},
    {'max_depth': 1.5},
    {'max_depth': True},
    {'max_nodes': '10'},
    {'max_errors': -2},
])
def test_invalid_budget_limit(limit):
    with pytest.raises(JsonSchemaDefinitionException):
        ValidationBudget(**limit)


def test_depth_budget():
    validator = compile(RECURSIVE_SCHEMA, budget=ValidationBudget(max_depth=5))
    assert validator(deep_value(5)) == deep_value(5)
    with pytest.raises(JsonSchemaBudgetExceededException) as exc:
        validator(deep_value(6))
    assert exc.value.budget == 'depth'
    assert exc.value.limit == 5
    assert exc.value.current == 6


def test_nodes_budget_shared_with_ref_functions():
    validator = compile(RECURSIVE_SCHEMA, budget=ValidationBudget(max_nodes=10))
    # Root plus five nested objects is exactly ten visited nodes.
    assert validator(deep_value(9)) == deep_value(9)
    with pytest.raises(JsonSchemaBudgetExceededException) as exc:
        validator(deep_value(10))
    assert exc.value.budget == 'nodes'
    assert exc.value.limit == 10


def test_nodes_budget_for_inline_items():
    validator = compile(
        {'type': 'array', 'items': {'type': 'integer'}},
        budget={'max_nodes': 5},
    )
    assert validator([1, 2, 3, 4]) == [1, 2, 3, 4]
    with pytest.raises(JsonSchemaBudgetExceededException) as exc:
        validator([1, 2, 3, 4, 5])
    assert exc.value.budget == 'nodes'


def test_errors_budget():
    validator = compile(
        {'type': 'array', 'items': {'type': 'integer'}},
        fast_fail=False,
        budget=ValidationBudget(max_errors=3),
    )
    with pytest.raises(JsonSchemaValuesException) as exc:
        validator(['a', 'b', 'c'])
    assert len(exc.value.errors) == 3
    with pytest.raises(JsonSchemaBudgetExceededException) as exc:
        validator(['a', 'b', 'c', 'd'])
    assert exc.value.budget == 'errors'
    assert exc.value.limit == 3


def test_failed_trials_consume_error_budget_and_it_escapes_any_of():
    validator = compile(
        {'type': 'array', 'items': {'anyOf': [{'type': 'integer'}, {'type': 'string'}]}},
        budget=ValidationBudget(max_errors=1),
    )
    # The first anyOf branch consumes the single allowed error, the failure of
    # the second branch exceeds the budget inside the trial. It must propagate
    # instead of being caught by anyOf as an ordinary mismatch.
    with pytest.raises(JsonSchemaBudgetExceededException) as exc:
        validator([1.5])
    assert exc.value.budget == 'errors'


def test_depth_budget_escapes_any_of():
    schema = {
        'anyOf': [
            RECURSIVE_SCHEMA,
            {'type': 'integer'},
        ],
    }
    validator = compile(schema, budget=ValidationBudget(max_depth=3))
    with pytest.raises(JsonSchemaBudgetExceededException):
        validator(deep_value(10))


def test_depth_restored_after_failed_trial():
    validator = compile(
        {
            'type': 'object',
            'properties': {
                'child': {
                    'anyOf': [
                        {'type': 'object', 'properties': {'x': {'type': 'string'}}, 'required': ['x']},
                        {'type': 'object'},
                    ],
                },
                'other': {'type': 'object', 'properties': {'y': {'type': 'integer'}}},
            },
        },
        budget=ValidationBudget(max_depth=2),
    )
    # The failed first anyOf branch descends to depth 2 and must not leak it,
    # otherwise validating "other" afterwards would falsely exceed the budget.
    assert validator({'child': {'x': 1}, 'other': {'y': 2}}) == {'child': {'x': 1}, 'other': {'y': 2}}


def test_no_residual_state_between_calls():
    validator = compile(
        RECURSIVE_SCHEMA,
        fast_fail=False,
        budget=ValidationBudget(max_depth=3, max_nodes=10, max_errors=2),
    )
    with pytest.raises(JsonSchemaBudgetExceededException):
        validator(deep_value(10))
    # Counters and collected errors of the previous call must not leak into
    # the next one.
    assert validator({}) == {}
    assert validator(deep_value(3)) == deep_value(3)
    with pytest.raises(JsonSchemaValuesException) as exc:
        validator({'next': {}, 'bogus': 1})
    assert len(exc.value.errors) == 1


def test_validator_reusable_concurrently():
    validator = compile(RECURSIVE_SCHEMA, budget=ValidationBudget(max_depth=5, max_nodes=100))

    def run(index):
        if index % 2:
            with pytest.raises(JsonSchemaBudgetExceededException):
                validator(deep_value(20))
            return None
        return validator(deep_value(5))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(64)))
    for index, result in enumerate(results):
        if index % 2 == 0:
            assert result == deep_value(5)


def test_no_budget_keeps_existing_code_path():
    schema = {
        'type': 'object',
        'properties': {'next': {'$ref': '#'}},
    }
    assert compile_to_code(schema) == compile_to_code(schema, budget=None)
    assert '_budget' not in compile_to_code(schema)


def test_compile_to_code_with_budget_is_self_contained():
    code = compile_to_code(RECURSIVE_SCHEMA, budget=ValidationBudget(max_depth=2))
    namespace = {}
    exec(code, namespace)
    validator = namespace['validate']
    assert validator(deep_value(2)) == deep_value(2)
    with pytest.raises(JsonSchemaBudgetExceededException):
        validator(deep_value(3))


def test_validate_function_accepts_budget():
    assert validate(RECURSIVE_SCHEMA, deep_value(2), budget={'max_depth': 2}) == deep_value(2)
    with pytest.raises(JsonSchemaBudgetExceededException):
        validate(RECURSIVE_SCHEMA, deep_value(3), budget={'max_depth': 2})
