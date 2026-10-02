import importlib.util
from pathlib import Path

import pytest

from fastjsonschema import JsonSchemaValueException, JsonSchemaValuesException, compile, compile_to_code


DRAFT_2019 = 'https://json-schema.org/draft/2019-09/schema'


def _multi_ref_schema():
    return {
        '$schema': DRAFT_2019,
        'type': 'object',
        'allOf': [
            {'allOf': [{'$ref': '#/$defs/name'}]},
            {'$ref': '#/$defs/address'},
        ],
        'unevaluatedProperties': False,
        '$defs': {
            'name': {'type': 'object', 'properties': {'name': {'type': 'string'}}},
            'address': {
                'type': 'object',
                'properties': {'address': {'type': 'object'}},
            },
        },
    }


def test_multiple_refs_and_allof_share_evaluated_properties():
    validator = compile(_multi_ref_schema())

    assert validator({'name': 'Ada', 'address': {'city': 'London'}}) == {
        'name': 'Ada',
        'address': {'city': 'London'},
    }

    with pytest.raises(JsonSchemaValueException) as exc_info:
        validator({'name': 'Ada', 'address': {}, 'unexpected': True})

    assert exc_info.value.rule == 'unevaluatedProperties'
    assert exc_info.value.name == 'data'
    assert "{'unexpected'}" in exc_info.value.message


def test_failed_ref_branch_does_not_claim_properties():
    schema = {
        '$schema': DRAFT_2019,
        'type': 'object',
        'allOf': [{'$ref': '#/$defs/name'}],
        'unevaluatedProperties': False,
        '$defs': {
            'name': {'type': 'object', 'properties': {'name': {'type': 'string'}}},
        },
    }

    with pytest.raises(JsonSchemaValueException) as exc_info:
        compile(schema)({'name': 1, 'unexpected': True})

    assert exc_info.value.rule == 'type'
    assert exc_info.value.name == 'data.name'

    with pytest.raises(JsonSchemaValuesException) as exc_info:
        compile(schema, fast_fail=False)({'name': 1, 'unexpected': True})

    rules = {(error.rule, error.name) for error in exc_info.value.errors}
    assert ('type', 'data.name') in rules
    assert ('unevaluatedProperties', 'data') in rules


@pytest.mark.parametrize('combinator', ['anyOf', 'oneOf'])
def test_only_successful_alternative_claims_properties(combinator):
    schema = {
        '$schema': DRAFT_2019,
        'type': 'object',
        combinator: [
            {'required': ['left'], 'properties': {'left': {}}},
            {'required': ['right'], 'properties': {'right': {}}},
        ],
        'unevaluatedProperties': False,
    }

    assert compile(schema)({'right': 1}) == {'right': 1}
    with pytest.raises(JsonSchemaValueException) as exc_info:
        compile(schema)({'right': 1, 'unexpected': 2})
    assert exc_info.value.rule == 'unevaluatedProperties'


def test_if_then_else_only_selected_branches_claim_properties():
    schema = {
        '$schema': DRAFT_2019,
        'type': 'object',
        'if': {'required': ['condition'], 'properties': {'condition': {}}},
        'then': {'properties': {'when_true': {}}},
        'else': {'properties': {'when_false': {}}},
        'unevaluatedProperties': False,
    }

    assert compile(schema)({'condition': True, 'when_true': 1})
    assert compile(schema)({'when_false': 1})

    with pytest.raises(JsonSchemaValueException):
        compile(schema)({'when_true': 1})
    with pytest.raises(JsonSchemaValueException):
        compile(schema)({'condition': True, 'when_false': 1})


@pytest.mark.parametrize('fixed_definition', [True, False, {'type': 'integer'}])
def test_pattern_properties_boolean_and_schema_forms(fixed_definition):
    schema = {
        '$schema': DRAFT_2019,
        'type': 'object',
        'properties': {'fixed': fixed_definition},
        'patternProperties': {'^p': {'type': 'integer'}},
        'unevaluatedProperties': {'type': 'string'},
    }

    if fixed_definition is False:
        with pytest.raises(JsonSchemaValueException) as exc_info:
            compile(schema)({'fixed': 1, 'p1': 2, 'extra': 'x'})
        assert exc_info.value.name == 'data.fixed'
        assert compile(schema)({'p1': 2, 'extra': 'x'})
    else:
        fixed = 1 if fixed_definition == {'type': 'integer'} else object()
        assert compile(schema)({'fixed': fixed, 'p1': 2, 'extra': 'x'})

    with pytest.raises(JsonSchemaValueException) as exc_info:
        compile(schema)({'p1': 'not integer'})
    assert exc_info.value.name == 'data.p1'

    with pytest.raises(JsonSchemaValueException) as exc_info:
        compile(schema)({'extra': 1})
    assert exc_info.value.name == 'data.extra'


def test_unevaluated_properties_true_annotates_all_properties():
    schema = {
        '$schema': DRAFT_2019,
        'type': 'object',
        'allOf': [{'unevaluatedProperties': True}],
        'unevaluatedProperties': False,
    }

    assert compile(schema)({'anything': 1, 'other': 2}) == {'anything': 1, 'other': 2}


def test_nested_object_inside_array_uses_its_own_evaluated_properties():
    schema = {
        '$schema': DRAFT_2019,
        'type': 'object',
        'properties': {
            'things': {
                'type': 'array',
                'items': {'$ref': '#/$defs/thing'},
            },
        },
        'unevaluatedProperties': False,
        '$defs': {
            'thing': {
                'type': 'object',
                'properties': {'id': {}},
                'unevaluatedProperties': False,
            },
        },
    }

    assert compile(schema)({'things': [{'id': 1}]}) == {'things': [{'id': 1}]}

    with pytest.raises(JsonSchemaValueException) as exc_info:
        compile(schema)({'things': [{'id': 1, 'bad': 2}]})

    assert exc_info.value.name == 'data.things[0]'
    assert exc_info.value.rule == 'unevaluatedProperties'


def test_keyword_is_supported_only_for_draft_2019():
    schema = {
        '$schema': 'http://json-schema.org/draft-07/schema#',
        'type': 'object',
        'unevaluatedProperties': False,
    }

    assert compile(schema)({'not_understood_by_draft_07': 1})


def test_compiled_and_exported_source_give_consistent_results(tmp_path):
    schema = _multi_ref_schema()
    valid = {'name': 'Ada', 'address': {'city': 'London'}}
    invalid = {'name': 'Ada', 'address': {}, 'unexpected': True}

    for fast_fail, exception_type in ((True, JsonSchemaValueException), (False, JsonSchemaValuesException)):
        source = compile_to_code(schema, fast_fail=fast_fail)
        source_path = Path(tmp_path) / f'generated_validator_{fast_fail}.py'
        source_path.write_text(source, encoding='utf-8')

        spec = importlib.util.spec_from_file_location(
            f'generated_validator_{fast_fail}', source_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        in_memory = compile(schema, fast_fail=fast_fail)
        assert in_memory(valid.copy()) == valid
        assert module.validate(valid.copy()) == valid

        with pytest.raises(exception_type) as in_memory_exc:
            in_memory(invalid.copy())
        with pytest.raises(exception_type) as source_exc:
            module.validate(invalid.copy())

        assert in_memory_exc.value.message == source_exc.value.message
        errors = getattr(source_exc.value, 'errors', [source_exc.value])
        assert errors[-1].rule == 'unevaluatedProperties'
