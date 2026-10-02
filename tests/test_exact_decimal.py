from decimal import Decimal, localcontext
import json

import pytest

from fastjsonschema import (
    JsonSchemaDefinitionException,
    JsonSchemaValueException,
    JsonSchemaValuesException,
    compile,
    compile_to_code,
)


DRAFT_VERSIONS = (
    'http://json-schema.org/draft-04/schema',
    'http://json-schema.org/draft-06/schema',
    'http://json-schema.org/draft-07/schema',
    'http://json-schema.org/draft/2019-09/schema',
)


def test_number_constraints_use_decimal_without_float_conversion():
    validator = compile({
        'type': 'number',
        'exclusiveMinimum': Decimal('0.1'),
        'exclusiveMaximum': Decimal('0.5'),
        'multipleOf': Decimal('0.1'),
    }, exact_decimal=True)

    assert validator(Decimal('0.3')) == Decimal('0.3')
    assert validator(0.3) == Decimal('0.3')

    with pytest.raises(JsonSchemaValueException) as exc:
        validator(Decimal('0.3000000000000000000000000000000001'))
    assert exc.value.rule == 'multipleOf'

    with pytest.raises(JsonSchemaValueException) as exc:
        validator(Decimal('0.1'))
    assert exc.value.rule == 'exclusiveMinimum'

    with pytest.raises(JsonSchemaValueException) as exc:
        validator(Decimal('0.5'))
    assert exc.value.rule == 'exclusiveMaximum'


def test_decimal_0_3_is_three_tenths():
    validator = compile({'multipleOf': Decimal('0.1')}, exact_decimal=True)
    assert validator(Decimal('0.3')) == Decimal('0.3')
    assert validator(Decimal('-0.3')) == Decimal('-0.3')
    assert validator(Decimal('0')) == Decimal('0')

    with pytest.raises(JsonSchemaValueException):
        validator(Decimal('0.299999999999999999999999999999999'))


def test_integers_follow_json_integer_semantics():
    validator = compile({'type': 'integer'}, exact_decimal=True)
    assert validator(42) == 42
    assert validator(Decimal('42.000')) == Decimal('42.000')
    assert validator(1.0) == Decimal('1.0')

    with pytest.raises(JsonSchemaValueException):
        validator(Decimal('1.001'))
    with pytest.raises(JsonSchemaValueException):
        validator(True)


def test_boolean_is_not_a_number_for_constraints():
    schema = {
        'type': ['boolean', 'number'],
        'minimum': Decimal('1'),
        'exclusiveMinimum': Decimal('1'),
        'maximum': Decimal('10'),
        'exclusiveMaximum': Decimal('10'),
        'multipleOf': Decimal('2'),
    }
    validator = compile(schema, exact_decimal=True)
    assert validator(False) is False
    assert validator(True) is True
    assert validator(Decimal('4')) == Decimal('4')

    integer_or_boolean = compile({'type': ['integer', 'boolean']}, exact_decimal=True)
    assert integer_or_boolean(True) is True
    with pytest.raises(JsonSchemaValueException):
        integer_or_boolean(Decimal('1.5'))


def test_regex_format_keeps_exact_mode_imports():
    validator = compile({
        'type': 'object',
        'properties': {
            'pattern': {'type': 'string', 'format': 'regex'},
            'amount': {'type': 'number', 'multipleOf': Decimal('0.1')},
        },
    }, exact_decimal=True)
    assert validator({'pattern': '^a$', 'amount': Decimal('0.3')}) == {
        'pattern': '^a$',
        'amount': Decimal('0.3'),
    }


@pytest.mark.parametrize('value', (
    float('nan'),
    float('inf'),
    float('-inf'),
    Decimal('NaN'),
    Decimal('Infinity'),
    Decimal('-Infinity'),
))
def test_non_finite_numbers_are_rejected(value):
    validator = compile({}, exact_decimal=True)
    with pytest.raises(JsonSchemaValueException) as exc:
        validator(value)
    assert exc.value.rule == 'type'


def test_nested_non_finite_numbers_are_rejected():
    validator = compile({
        'type': 'object',
        'properties': {
            'items': {'type': 'array', 'items': {'type': 'number'}},
        },
    }, exact_decimal=True)
    with pytest.raises(JsonSchemaValueException) as exc:
        validator({'items': [Decimal('1'), Decimal('NaN')]})
    assert exc.value.name == 'data.items[1]'


def test_non_finite_numbers_are_collected_when_fast_fail_is_disabled():
    validator = compile({}, exact_decimal=True, fast_fail=False)
    with pytest.raises(JsonSchemaValuesException) as exc:
        validator(Decimal('NaN'))
    assert [error.message for error in exc.value.errors] == ['data must be a finite number']


@pytest.mark.parametrize('schema,value', (
    ({'enum': [Decimal('0.1'), 2]}, Decimal('0.1')),
    ({'enum': [Decimal('0.1'), 2]}, 0.1),
    ({'const': Decimal('0.1')}, 0.1),
))
def test_enum_and_const_compare_numbers_exactly(schema, value):
    validator = compile(schema, exact_decimal=True)
    assert validator(value) == value


def test_enum_does_not_match_boolean_number():
    validator = compile({'enum': [0, 1]}, exact_decimal=True)
    with pytest.raises(JsonSchemaValueException):
        validator(True)


def test_extreme_exponents_and_large_integers():
    tiny = Decimal('1E-100000')
    huge = Decimal('1E100000')
    validator = compile({
        'minimum': tiny,
        'maximum': huge,
        'multipleOf': tiny,
    }, exact_decimal=True)

    assert validator(tiny) == tiny
    assert validator(huge) == huge
    assert validator(10 ** 10000) == 10 ** 10000
    with pytest.raises(JsonSchemaValueException):
        validator(Decimal('1E-100001'))


def test_bad_numeric_schema_constraints_are_definition_errors():
    with pytest.raises(JsonSchemaDefinitionException):
        compile({'multipleOf': Decimal('0')}, exact_decimal=True)
    with pytest.raises(JsonSchemaDefinitionException):
        compile({'multipleOf': True}, exact_decimal=True)
    with pytest.raises(JsonSchemaDefinitionException):
        compile({'minimum': Decimal('NaN')}, exact_decimal=True)


def test_compiled_code_is_stable_under_another_decimal_context(tmp_path):
    schema = {
        'type': 'object',
        'properties': {
            'amount': {
                'type': 'number',
                'minimum': Decimal('0.1'),
                'exclusiveMaximum': Decimal('1.0'),
                'multipleOf': Decimal('0.1'),
            },
        },
        'required': ['amount'],
    }
    cases = (
        ('0.3', True),
        ('0.3000000000000000000000000001', False),
        ('0.1', True),
        ('1.0', False),
    )

    with localcontext() as context:
        context.prec = 2
        validator = compile(schema, exact_decimal=True)
        code = compile_to_code(schema, exact_decimal=True)
        for amount, should_pass in cases:
            value = {'amount': Decimal(amount)}
            if should_pass:
                assert validator(value) == value
            else:
                with pytest.raises(JsonSchemaValueException):
                    validator(value)

    module_path = tmp_path / 'generated_decimal_validator.py'
    module_path.write_text(code, encoding='utf-8')

    import importlib
    import sys
    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module(module_path.stem)
        with localcontext() as context:
            context.prec = 80
            for amount, should_pass in cases:
                value = {'amount': Decimal(amount)}
                if should_pass:
                    assert module.validate(value) == value
                else:
                    with pytest.raises(JsonSchemaValueException):
                        module.validate(value)
    finally:
        sys.path.remove(str(tmp_path))
        del sys.modules[module_path.stem]


def test_decimal_json_loader():
    validator = compile({'type': 'number', 'multipleOf': Decimal('0.01')}, exact_decimal=True)
    parsed = json.loads('0.30', parse_float=Decimal)
    assert validator(parsed) == Decimal('0.30')


@pytest.mark.parametrize('schema_version', DRAFT_VERSIONS)
def test_boundaries_are_inclusive_by_default(schema_version):
    validator = compile({
        '$schema': schema_version,
        'minimum': Decimal('-0.2'),
        'maximum': Decimal('0.2'),
    }, exact_decimal=True)
    assert validator(Decimal('-0.2')) == Decimal('-0.2')
    assert validator(Decimal('0.2')) == Decimal('0.2')
