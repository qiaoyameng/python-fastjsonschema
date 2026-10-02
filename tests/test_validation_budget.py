from concurrent.futures import ThreadPoolExecutor

import pytest

from fastjsonschema import (
    JsonSchemaBudgetExceeded,
    JsonSchemaValueException,
    ValidationBudget,
    compile,
    compile_to_code,
)


RECURSIVE_OBJECT_SCHEMA = {
    'type': 'object',
    'properties': {
        'next': {'$ref': '#'},
    },
}

RECURSIVE_REF_SCHEMA = {
    '$ref': '#/definitions/node',
    'definitions': {
        'node': {
            'type': 'object',
            'required': ['value'],
            'properties': {
                'next': {'$ref': '#/definitions/node'},
            },
        },
    },
}


def nested_object(depth):
    result = {}
    current = result
    for _ in range(depth):
        current['next'] = {}
        current = current['next']
    return result


@pytest.mark.parametrize(
    ('budget', 'expected_kind'),
    [
        (ValidationBudget(max_depth=3), 'depth'),
        (ValidationBudget(max_nodes=4), 'nodes'),
    ],
)
def test_recursive_data_is_limited(budget, expected_kind):
    validator = compile(RECURSIVE_OBJECT_SCHEMA, validation_budget=budget)

    with pytest.raises(JsonSchemaBudgetExceeded) as exc_info:
        validator(nested_object(8))

    assert exc_info.value.kind == expected_kind
    assert exc_info.value.budget == budget


def test_cumulative_errors_are_limited_behind_refs():
    validator = compile(
        RECURSIVE_REF_SCHEMA,
        fast_fail=False,
        validation_budget=ValidationBudget(max_errors=2),
    )

    with pytest.raises(JsonSchemaBudgetExceeded) as exc_info:
        validator(nested_object(5))

    assert exc_info.value.kind == 'errors'
    assert exc_info.value.used == 3
    assert exc_info.value.errors == 3


def test_budget_exception_is_not_caught_by_any_of():
    schema = {
        'anyOf': [
            {'type': 'integer'},
            {'allOf': [{'type': 'number'}, {'minimum': 1}]},
        ],
    }
    validator = compile(
        schema,
        fast_fail=False,
        validation_budget=ValidationBudget(max_errors=1),
    )

    with pytest.raises(JsonSchemaBudgetExceeded) as exc_info:
        validator('not a number')

    assert exc_info.value.kind == 'errors'
    assert exc_info.value.used == 2


def test_failed_attempt_keeps_consumed_budget():
    schema = {
        'definitions': {'integer': {'type': 'integer'}},
        'anyOf': [
            {'$ref': '#/definitions/integer'},
            {'type': 'integer', 'minimum': 1},
        ],
    }
    validator = compile(
        schema,
        fast_fail=False,
        validation_budget=ValidationBudget(max_nodes=2, max_errors=1),
    )

    with pytest.raises(JsonSchemaBudgetExceeded):
        validator('not an integer')


def test_same_level_ref_does_not_increase_data_depth():
    schema = {
        'definitions': {'integer': {'type': 'integer'}},
        'anyOf': [{'$ref': '#/definitions/integer'}, {'type': 'string'}],
    }
    validator = compile(schema, validation_budget=ValidationBudget(max_depth=1))

    assert validator(42) == 42


def test_each_call_starts_with_independent_counts():
    validator = compile(
        RECURSIVE_OBJECT_SCHEMA,
        validation_budget=ValidationBudget(max_depth=3, max_nodes=8),
    )

    with pytest.raises(JsonSchemaBudgetExceeded):
        validator(nested_object(8))

    assert validator({'next': {}}) == {'next': {}}
    assert validator({}) == {}


def test_concurrent_validator_reuse_does_not_share_state():
    validator = compile(
        RECURSIVE_OBJECT_SCHEMA,
        validation_budget=ValidationBudget(max_depth=3, max_nodes=8),
    )

    def use_validator(index):
        if index % 2:
            with pytest.raises(JsonSchemaBudgetExceeded):
                validator(nested_object(8))
        else:
            assert validator({'next': {}}) == {'next': {}}
        return index

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert list(executor.map(use_validator, range(40))) == list(range(40))


def test_budget_validation():
    with pytest.raises(ValueError):
        ValidationBudget(max_depth=0)
    with pytest.raises(ValueError):
        ValidationBudget(max_nodes=False)
    with pytest.raises(ValueError):
        ValidationBudget(max_errors='2')


def test_unconfigured_validator_keeps_fast_error_path():
    validator = compile({'type': 'integer'})

    with pytest.raises(JsonSchemaValueException):
        validator('nope')


def test_compile_to_code_with_budget(tmp_path, monkeypatch):
    code = compile_to_code(
        RECURSIVE_OBJECT_SCHEMA,
        validation_budget=ValidationBudget(max_depth=2),
    )
    module_path = tmp_path / 'budgeted_validator.py'
    module_path.write_text(code, encoding='utf-8')

    with monkeypatch.context() as context:
        context.syspath_prepend(tmp_path)
        from budgeted_validator import validate

    with pytest.raises(JsonSchemaBudgetExceeded):
        validate(nested_object(4))
    assert validate({'next': {}}) == {'next': {}}


def test_empty_child_schema_keeps_generated_block_valid():
    validator = compile(
        {
            'type': 'object',
            'properties': {'anything': {}},
            'patternProperties': {'.*': {}},
        },
        validation_budget=ValidationBudget(max_nodes=5),
    )

    assert validator({'anything': {'nested': []}}) == {'anything': {'nested': []}}
