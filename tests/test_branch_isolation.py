import copy
import importlib.util

import pytest

from fastjsonschema import JsonSchemaValueException, JsonSchemaValuesException, compile, compile_to_code


INVALID_AFTER_DEFAULT = {
    'properties': {
        'a': {'default': 1},
    },
    'patternProperties': {
        '^a$': {'type': 'string'},
    },
}
FIRST_SUCCESS = {
    'properties': {
        'b': {'default': 2},
    },
}
SECOND_SUCCESS = {
    'properties': {
        'c': {'default': 3},
    },
}


@pytest.fixture
def compiled_both(tmp_path):
    def factory(schema, **options):
        dynamic_validator = compile(schema, **options)
        module_path = tmp_path / 'generated_validator.py'
        module_path.write_text(compile_to_code(schema, **options), encoding='utf-8')
        spec = importlib.util.spec_from_file_location('generated_validator', module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return dynamic_validator, module.validate
    return factory


@pytest.mark.parametrize('fast_fail', [True, False])
def test_any_of_discards_failed_branch_and_commits_first_success(compiled_both, fast_fail):
    schema = {
        'type': 'object',
        'anyOf': [INVALID_AFTER_DEFAULT, FIRST_SUCCESS, SECOND_SUCCESS],
    }
    for validator in compiled_both(schema, isolate_branches=True, fast_fail=fast_fail):
        data = copy.deepcopy({})
        result = validator(data)

        assert result == {'b': 2}
        assert result is data
        assert 'a' not in result
        assert 'c' not in result


@pytest.mark.parametrize('fast_fail', [True, False])
def test_one_of_with_two_successes_commits_nothing(compiled_both, fast_fail):
    schema = {
        'type': 'object',
        'oneOf': [FIRST_SUCCESS, SECOND_SUCCESS],
    }
    for validator in compiled_both(schema, isolate_branches=True, fast_fail=fast_fail):
        data = copy.deepcopy({})
        with pytest.raises((JsonSchemaValueException, JsonSchemaValuesException)) as exc_info:
            validator(data)

        assert 'exactly by one definition' in str(exc_info.value)
        assert data == {}


@pytest.mark.parametrize('fast_fail', [True, False])
def test_one_of_with_one_success_commits_that_branch(compiled_both, fast_fail):
    schema = {
        'type': 'object',
        'oneOf': [
            {
                'properties': {'a': {'default': 1}},
                'required': ['missing'],
            },
            FIRST_SUCCESS,
        ],
    }
    for validator in compiled_both(schema, isolate_branches=True, fast_fail=fast_fail):
        data = {}

        assert validator(data) == {'b': 2}
        assert data == {'b': 2}


@pytest.mark.parametrize('fast_fail', [True, False])
def test_not_and_if_do_not_commit_condition_defaults(compiled_both, fast_fail):
    schema = {
        'allOf': [
            {'not': INVALID_AFTER_DEFAULT},
            {'if': FIRST_SUCCESS},
        ],
    }
    for validator in compiled_both(schema, isolate_branches=True, fast_fail=fast_fail):
        data = copy.deepcopy({})
        result = validator(data)

        assert result == {}
        assert result is data


@pytest.mark.parametrize('fast_fail', [True, False])
def test_then_and_else_still_commit_their_own_defaults(compiled_both, fast_fail):
    schema = {
        'if': FIRST_SUCCESS,
        'then': {'properties': {'then_value': {'default': 'ok'}}},
        'else': {'properties': {'else_value': {'default': 'no'}}},
    }
    for validator in compiled_both(schema, isolate_branches=True, fast_fail=fast_fail):
        assert validator({}) == {'then_value': 'ok'}


@pytest.mark.parametrize('fast_fail', [True, False])
def test_nested_composition_with_shared_ref(compiled_both, fast_fail):
    schema = {
        'type': 'object',
        'definitions': {
            'invalid_after_default': INVALID_AFTER_DEFAULT,
            'first_success': FIRST_SUCCESS,
        },
        'anyOf': [
            {
                'oneOf': [
                    {'$ref': '#/definitions/invalid_after_default'},
                    {'$ref': '#/definitions/first_success'},
                ],
            },
        ],
        'not': {'$ref': '#/definitions/invalid_after_default'},
    }
    for validator in compiled_both(schema, isolate_branches=True, fast_fail=fast_fail):
        data = copy.deepcopy({})
        result = validator(data)

        assert result == {'b': 2}
        assert 'a' not in result
