import pytest

from fastjsonschema import (
    JsonSchemaValueException,
    JsonSchemaValuesException,
    compile,
    compile_to_code,
    validate,
)

DRAFT2019 = 'https://json-schema.org/draft/2019-09/schema'


def schema(**kwargs):
    return {'$schema': DRAFT2019, **kwargs}


def check_valid(definition, data):
    for fast_fail in (True, False):
        assert compile(definition, fast_fail=fast_fail)(data) == data


def check_invalid(definition, data):
    for fast_fail in (True, False):
        with pytest.raises((JsonSchemaValueException, JsonSchemaValuesException)):
            compile(definition, fast_fail=fast_fail)(data)


def test_basic():
    definition = schema(properties={'a': {}}, unevaluatedProperties=False)
    check_valid(definition, {'a': 1})
    check_valid(definition, {})
    check_invalid(definition, {'a': 1, 'b': 2})


def test_ignores_non_objects():
    definition = schema(unevaluatedProperties=False)
    check_valid(definition, 'hello')
    check_valid(definition, 42)
    check_valid(definition, [1, 2])
    check_valid(definition, None)


def test_error_points_to_extra_properties():
    definition = schema(properties={'a': {}}, unevaluatedProperties=False)
    with pytest.raises(JsonSchemaValueException) as exc:
        validate(definition, {'a': 1, 'b': 2})
    assert exc.value.message == "data must not contain {'b'} properties"
    assert exc.value.rule == 'unevaluatedProperties'
    assert exc.value.name == 'data'
    assert exc.value.value == {'a': 1, 'b': 2}
    assert exc.value.definition['unevaluatedProperties'] is False


def test_fast_fail_false_collects_error():
    definition = schema(properties={'a': {}}, unevaluatedProperties=False)
    with pytest.raises(JsonSchemaValuesException) as exc:
        compile(definition, fast_fail=False)({'a': 1, 'b': 2})
    assert exc.value.errors
    assert exc.value.errors[0].rule == 'unevaluatedProperties'


def test_true_evaluates_everything():
    definition = schema(properties={'a': {}}, unevaluatedProperties=True)
    check_valid(definition, {'a': 1, 'b': 2})


def test_schema_form():
    definition = schema(properties={'a': {}}, unevaluatedProperties={'type': 'string'})
    check_valid(definition, {'a': 1, 'b': 'text'})
    check_invalid(definition, {'a': 1, 'b': 2})


def test_pattern_properties_contribute():
    definition = schema(patternProperties={'^x_': {}}, unevaluatedProperties=False)
    check_valid(definition, {'x_a': 1})
    check_invalid(definition, {'y_a': 1})


def test_additional_properties_contribute():
    definition = schema(
        properties={'a': {}},
        additionalProperties={'type': 'string'},
        unevaluatedProperties=False,
    )
    check_valid(definition, {'a': 1, 'b': 'text'})
    check_invalid(definition, {'a': 1, 'b': 2})


def test_additional_properties_true_contribute():
    definition = schema(
        properties={'a': {}},
        additionalProperties=True,
        unevaluatedProperties=False,
    )
    check_valid(definition, {'a': 1, 'b': 2})


def test_default_filled_property_is_evaluated():
    definition = schema(properties={'a': {'default': 5}}, unevaluatedProperties=False)
    for fast_fail in (True, False):
        assert compile(definition, fast_fail=fast_fail)({}) == {'a': 5}


def test_all_of_union():
    definition = schema(
        allOf=[
            {'properties': {'a': {}}},
            {'properties': {'b': {}}},
        ],
        unevaluatedProperties=False,
    )
    check_valid(definition, {'a': 1, 'b': 2})
    check_invalid(definition, {'a': 1, 'b': 2, 'c': 3})


def test_ref_composition():
    # Object rules split into multiple $refs and combined with allOf.
    definition = schema(
        definitions={
            'with_a': {'properties': {'a': {'type': 'integer'}}},
            'with_b': {'properties': {'b': {'type': 'string'}}},
        },
        allOf=[{'$ref': '#/definitions/with_a'}, {'$ref': '#/definitions/with_b'}],
        unevaluatedProperties=False,
    )
    check_valid(definition, {'a': 1, 'b': 'x'})
    check_valid(definition, {'a': 1})
    check_invalid(definition, {'a': 1, 'b': 'x', 'c': None})
    check_invalid(definition, {'a': 'not-an-int', 'b': 'x'})


def test_multi_level_ref_composition():
    definition = schema(
        definitions={
            'level1': {'properties': {'a': {}}},
            'level2': {'$ref': '#/definitions/level1', 'properties': {'b': {}}},
            'level3': {'$ref': '#/definitions/level2', 'properties': {'c': {}}},
        },
        **{'$ref': '#/definitions/level3', 'unevaluatedProperties': False},
    )
    check_valid(definition, {'a': 1, 'b': 2, 'c': 3})
    check_invalid(definition, {'a': 1, 'b': 2, 'c': 3, 'd': 4})


def test_remote_ref_composition():
    repo = {
        'sch://with-a': {'properties': {'a': {'type': 'integer'}}},
        'sch://with-b': {
            'allOf': [{'$ref': 'sch://with-a'}],
            'properties': {'b': {'type': 'string'}},
        },
    }
    definition = schema(
        allOf=[{'$ref': 'sch://with-b'}],
        unevaluatedProperties=False,
    )
    for fast_fail in (True, False):
        validator = compile(definition, handlers={'sch': repo.__getitem__}, fast_fail=fast_fail)
        assert validator({'a': 1, 'b': 'x'}) == {'a': 1, 'b': 'x'}
        with pytest.raises((JsonSchemaValueException, JsonSchemaValuesException)):
            validator({'a': 1, 'b': 'x', 'c': None})


def test_any_of_passing_branches_contribute():
    definition = schema(
        anyOf=[
            {'properties': {'a': {}}},
            {'properties': {'b': {}}},
        ],
        unevaluatedProperties=False,
    )
    check_valid(definition, {'a': 1})
    check_valid(definition, {'b': 1})
    # Both branches are valid, so annotations of both count.
    check_valid(definition, {'a': 1, 'b': 2})
    check_invalid(definition, {'a': 1, 'c': 1})


def test_any_of_failed_branch_does_not_claim_properties():
    definition = schema(
        anyOf=[
            {'properties': {'foo': {'const': 1}}, 'required': ['foo']},
            True,
        ],
        unevaluatedProperties=False,
    )
    check_valid(definition, {'foo': 1})
    # First branch fails on const, so its properties annotation is dropped.
    check_invalid(definition, {'foo': 2})


def test_one_of():
    definition = schema(
        oneOf=[
            {'properties': {'a': {}}, 'required': ['a']},
            {'properties': {'b': {}}, 'required': ['b']},
        ],
        unevaluatedProperties=False,
    )
    check_valid(definition, {'a': 1})
    check_valid(definition, {'b': 1})
    check_invalid(definition, {'a': 1, 'b': 1})
    check_invalid(definition, {'a': 1, 'c': 1})


def test_one_of_failed_branch_does_not_claim_properties():
    definition = schema(
        oneOf=[
            {'properties': {'a': {'const': 1}}, 'required': ['a']},
            {'properties': {'b': {}}, 'required': ['b']},
        ],
        unevaluatedProperties=False,
    )
    # First branch fails on const, so 'a' stays unevaluated.
    check_invalid(definition, {'a': 2, 'b': 1})


def test_if_then_else():
    definition = schema(
        **{
            'if': {'properties': {'kind': {'const': 'a'}}, 'required': ['kind']},
            'then': {'properties': {'x': {}}},
            'else': {'properties': {'y': {}}},
            'unevaluatedProperties': False,
        }
    )
    check_valid(definition, {'kind': 'a', 'x': 1})
    check_invalid(definition, {'kind': 'a', 'y': 1})
    # When `if` fails, its own annotations are dropped.
    check_invalid(definition, {'kind': 'b', 'y': 1})
    check_valid(definition, {'y': 1})
    check_invalid(definition, {'x': 1})


def test_if_annotations_count_when_valid():
    definition = schema(
        **{
            'if': {'properties': {'kind': {}}},
            'then': {'properties': {'x': {}}},
            'unevaluatedProperties': False,
        }
    )
    check_valid(definition, {'kind': 'a', 'x': 1})


def test_not_does_not_contribute():
    definition = schema(
        **{'not': {'properties': {'a': {}}}, 'unevaluatedProperties': False}
    )
    check_invalid(definition, {'b': 1})


def test_nested_scope_does_not_see_outer_properties():
    definition = schema(
        properties={'a': {}},
        allOf=[{'properties': {'b': {}}, 'unevaluatedProperties': False}],
    )
    # The inner unevaluatedProperties only sees 'b' from its own subschema.
    check_invalid(definition, {'a': 1, 'b': 2})
    check_valid(definition, {'b': 2})


def test_outer_scope_sees_inner_annotations():
    definition = schema(
        properties={'a': {}},
        allOf=[{'properties': {'b': {}}, 'unevaluatedProperties': False}],
        unevaluatedProperties=False,
    )
    check_invalid(definition, {'a': 1, 'b': 2})
    check_invalid(definition, {'b': 2, 'c': 3})


def test_nested_objects():
    definition = schema(
        properties={
            'obj': {'properties': {'a': {}}, 'unevaluatedProperties': False},
        },
        unevaluatedProperties=False,
    )
    check_valid(definition, {'obj': {'a': 1}})
    check_invalid(definition, {'obj': {'a': 1, 'b': 2}})
    check_invalid(definition, {'obj': {'a': 1}, 'top': 1})


def test_unevaluated_properties_behind_ref():
    definition = schema(
        definitions={
            'strict': {'properties': {'a': {}}, 'unevaluatedProperties': False},
        },
        **{'$ref': '#/definitions/strict'},
    )
    check_valid(definition, {'a': 1})
    check_invalid(definition, {'a': 1, 'b': 2})


def test_compile_to_code_same_results(tmp_path, monkeypatch):
    definition = schema(
        definitions={
            'name_rule': {'properties': {'name': {'type': 'string'}}, 'required': ['name']},
            'age_rule': {'properties': {'age': {'type': 'integer', 'minimum': 0}}},
            'contact_rule': {
                '$ref': '#/definitions/age_rule',
                'properties': {'email': {'type': 'string'}},
            },
        },
        allOf=[{'$ref': '#/definitions/name_rule'}, {'$ref': '#/definitions/contact_rule'}],
        unevaluatedProperties=False,
    )
    samples = [
        ({'name': 'Ann', 'age': 3, 'email': 'a@b.co'}, True),
        ({'name': 'Ann', 'age': 3}, True),
        ({'name': 'Ann'}, True),
        ({'name': 'Ann', 'extra': 1}, False),
        ({'age': 3}, False),
        ({'name': 'Ann', 'age': -1}, False),
        ('not an object', True),
    ]
    for fast_fail in (True, False):
        code = compile_to_code(definition, fast_fail=fast_fail)
        module_path = tmp_path / 'schema_unevaluated_{}.py'.format(fast_fail)
        module_path.write_text(code)
        with monkeypatch.context() as m:
            m.syspath_prepend(tmp_path)
            module = __import__(module_path.stem)
        validate_in_memory = compile(definition, fast_fail=fast_fail)
        for data, expected_valid in samples:
            results = []
            for validator in (validate_in_memory, module.validate):
                try:
                    validator(data)
                    results.append(True)
                except (JsonSchemaValueException, JsonSchemaValuesException):
                    results.append(False)
            assert results == [expected_valid, expected_valid], (
                'fast_fail={}, data={!r}'.format(fast_fail, data)
            )
