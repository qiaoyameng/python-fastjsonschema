import pytest

from fastjsonschema import (
    JsonSchemaValueException,
    JsonSchemaValuesException,
    compile,
    compile_to_code,
)


def build_validators(validators, schema):
    return validators(schema)


@pytest.fixture(params=[True, False])
def validators(request):
    def build(schema):
        fast_fail = request.param
        validator = compile(
            schema,
            fast_fail=fast_fail,
            isolate_branches=True,
        )

        code = compile_to_code(
            schema,
            fast_fail=fast_fail,
            isolate_branches=True,
        )
        namespace = {}
        exec(code, namespace)
        return validator, namespace['validate']

    return build


def test_any_of_commits_first_successful_candidate_in_order(validators):
    schema = {
        'anyOf': [
            {
                'properties': {'a': {'default': 1}},
                'additionalProperties': False,
            },
            {
                'properties': {'b': {'default': 2}},
            },
        ],
    }

    for validator in build_validators(validators, schema):
        data = {'x': 1}
        assert validator(data) == {'x': 1, 'b': 2}


def test_one_of_with_two_successful_candidates_commits_nothing(validators):
    schema = {
        'oneOf': [
            {'properties': {'a': {'default': 1}}},
            {'properties': {'b': {'default': 2}}},
        ],
    }

    for validator in build_validators(validators, schema):
        data = {}
        with pytest.raises((JsonSchemaValueException, JsonSchemaValuesException)):
            validator(data)
        assert data == {}


def test_one_of_commits_only_unique_successful_candidate(validators):
    schema = {
        'oneOf': [
            {
                'properties': {'a': {'default': 1}},
                'additionalProperties': False,
            },
            {'required': ['y'], 'properties': {'b': {'default': 2}}},
        ],
    }

    for validator in build_validators(validators, schema):
        data = {'y': 1}
        assert validator(data) == {'y': 1, 'b': 2}


def test_failed_one_of_does_not_leave_nested_defaults(validators):
    schema = {
        'type': 'object',
        'properties': {
            'later': {'default': 3},
            'value': {
                'oneOf': [
                    {'properties': {'a': {'default': 1}}},
                    {'properties': {'b': {'default': 2}}},
                ],
            },
        },
    }

    for validator in build_validators(validators, schema):
        data = {'value': {}}
        with pytest.raises((JsonSchemaValueException, JsonSchemaValuesException)):
            validator(data)
        assert data == {'later': 3, 'value': {}}


@pytest.mark.parametrize('data, is_valid', [
    ({'keep': 1}, True),
    ({'x': 1}, False),
])
def test_not_is_only_a_probe(validators, data, is_valid):
    schema = {
        'not': {
            'properties': {'a': {'default': 1}},
            'required': ['x'],
        },
    }

    for validator in build_validators(validators, schema):
        value = dict(data)
        if is_valid:
            assert validator(value) == data
        else:
            with pytest.raises((JsonSchemaValueException, JsonSchemaValuesException)):
                validator(value)
        assert value == data


def test_if_is_only_a_probe(validators):
    schema = {
        'if': {'properties': {'a': {'default': 1}}},
    }

    for validator in build_validators(validators, schema):
        data = {'keep': 1}
        assert validator(data) == {'keep': 1}


def test_failed_if_probe_discards_default_before_else(validators):
    schema = {
        'if': {
            'properties': {'a': {'default': 1}},
            'required': ['x'],
        },
        'else': {'properties': {'b': {'default': 2}}},
    }

    for validator in build_validators(validators, schema):
        data = {'keep': 1}
        assert validator(data) == {'keep': 1, 'b': 2}


def test_if_probe_through_shared_ref_is_not_committed(validators):
    schema = {
        'definitions': {
            'probe': {
                'properties': {'a': {'default': 1}},
                'required': ['x'],
            },
        },
        'if': {'$ref': '#/definitions/probe'},
        'else': {'properties': {'b': {'default': 2}}},
    }

    for validator in build_validators(validators, schema):
        data = {'keep': 1}
        assert validator(data) == {'keep': 1, 'b': 2}


def test_contains_probe_is_rolled_back(validators):
    schema = {
        'contains': {
            'properties': {'a': {'default': 1}},
            'required': ['x'],
        },
    }

    for validator in build_validators(validators, schema):
        data = [{'keep': 1}]
        with pytest.raises((JsonSchemaValueException, JsonSchemaValuesException)):
            validator(data)
        assert data == [{'keep': 1}]


def test_nested_combinations_keep_inner_and_outer_isolation(validators):
    schema = {
        'anyOf': [
            {
                'oneOf': [
                    {'properties': {'a': {'default': 1}}},
                    {'properties': {'b': {'default': 2}}},
                ],
            },
            {'properties': {'z': {'default': 9}}},
        ],
    }

    for validator in build_validators(validators, schema):
        data = {}
        assert validator(data) == {'z': 9}


def test_shared_ref_candidate_is_rolled_back(validators):
    schema = {
        'definitions': {
            'branch': {
                'properties': {'a': {'default': 1}},
                'additionalProperties': False,
            },
        },
        'anyOf': [
            {'$ref': '#/definitions/branch'},
            {'properties': {'b': {'default': 2}}},
        ],
    }

    for validator in build_validators(validators, schema):
        data = {'x': 1}
        assert validator(data) == {'x': 1, 'b': 2}
