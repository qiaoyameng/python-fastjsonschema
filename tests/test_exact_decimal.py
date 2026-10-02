import decimal
import json
import builtins
from decimal import Decimal, localcontext

import pytest

import fastjsonschema
from fastjsonschema import JsonSchemaDefinitionException, JsonSchemaValueException, compile, compile_to_code


def validate(schema, value, *, exact_decimal=True):
    return compile(schema, exact_decimal=exact_decimal)(value)


def assert_invalid(schema, value, rule=None, *, exact_decimal=True):
    with pytest.raises(JsonSchemaValueException) as exc:
        compile(schema, exact_decimal=exact_decimal)(value)
    if rule is not None:
        assert exc.value.rule == rule
    return exc.value


# --------------------------------------------------------------------------
# Type semantics
# --------------------------------------------------------------------------

@pytest.mark.parametrize('value', [
    0, -5, 42,
    0.0, 1.0, -2.5,
    Decimal('0'), Decimal('1.0'), Decimal('-3.14'),
])
def test_number_accepts_int_float_decimal(value):
    assert validate({'type': 'number'}, value) == value


@pytest.mark.parametrize('value', [True, False, None, '1', [], {}, object()])
def test_number_rejects_non_numbers(value):
    assert_invalid({'type': 'number'}, value, 'type')


@pytest.mark.parametrize('value', [
    0, -5, 42,
    1.0, 0.0, -17.0,
    Decimal('1.0'), Decimal('100'), Decimal('-3.00'),
])
def test_integer_accepts_integral_values(value):
    assert validate({'type': 'integer'}, value) == value


@pytest.mark.parametrize('value', [
    0.1, 1.5,
    Decimal('0.1'), Decimal('1.0001'),
    True, False,
])
def test_integer_rejects_non_integral(value):
    assert_invalid({'type': 'integer'}, value, 'type')


def test_bool_is_never_a_number_with_numeric_keywords():
    for keywords in (
        {'minimum': 0},
        {'maximum': 10},
        {'multipleOf': 1},
        {'exclusiveMinimum': 0},
        {'exclusiveMaximum': 10},
    ):
        for value in (True, False):
            assert_invalid({'type': 'number', **keywords}, value, 'type')


def test_bool_allowed_when_boolean_type_listed():
    validator = compile({'type': ['boolean', 'number'], 'minimum': 5}, exact_decimal=True)
    assert validator(True) is True
    assert validator(False) is False


# --------------------------------------------------------------------------
# Boundaries: exact decimal, no float conversion
# --------------------------------------------------------------------------

def test_minimum_exact_boundary():
    schema = {'minimum': Decimal('0.1')}
    assert validate(schema, Decimal('0.1')) == Decimal('0.1')
    assert validate(schema, 0.1) == 0.1
    assert_invalid(schema, Decimal('0.0999999999999999999999'), 'minimum')
    assert_invalid(schema, 0.09, 'minimum')


def test_maximum_exact_boundary():
    schema = {'maximum': Decimal('0.1')}
    assert validate(schema, Decimal('0.1')) == Decimal('0.1')
    assert_invalid(schema, Decimal('0.100000000000000000001'), 'maximum')


def test_float_constant_is_reconstructed_exactly():
    # 0.1 as a float must mean the decimal 0.1 (shortest round-trip), not the binary value.
    schema = {'minimum': 0.1}
    assert validate(schema, Decimal('0.1')) == Decimal('0.1')
    assert_invalid(schema, Decimal('0.09999999999999999999999999999999'), 'minimum')


def test_exclusive_boundaries():
    min_schema = {'exclusiveMinimum': Decimal('1.5')}
    assert_invalid(min_schema, Decimal('1.5'), 'exclusiveMinimum')
    assert validate(min_schema, Decimal('1.6')) == Decimal('1.6')

    max_schema = {'exclusiveMaximum': Decimal('1.5')}
    assert_invalid(max_schema, Decimal('1.5'), 'exclusiveMaximum')
    assert validate(max_schema, Decimal('1.4')) == Decimal('1.4')


def test_negative_boundaries():
    schema = {'minimum': Decimal('-0.3'), 'maximum': Decimal('-0.1')}
    assert validate(schema, Decimal('-0.2')) == Decimal('-0.2')
    assert_invalid(schema, Decimal('-0.31'), 'minimum')
    assert_invalid(schema, Decimal('-0.09'), 'maximum')


# --------------------------------------------------------------------------
# multipleOf: exact, no epsilon
# --------------------------------------------------------------------------

@pytest.mark.parametrize('divisor, value', [
    (Decimal('0.1'), Decimal('0.3')),
    (0.1, 0.3),
    (Decimal('0.1'), 0.3),
    (0.1, Decimal('0.3')),
    (Decimal('0.01'), Decimal('19.01')),
    (Decimal('0.0001'), Decimal('0.0075')),
])
def test_multiple_of_tenths(divisor, value):
    assert validate({'multipleOf': divisor}, value) == value


@pytest.mark.parametrize('divisor, value', [
    (Decimal('0.1'), Decimal('0.31')),
    (0.1, 0.31),
    (Decimal('0.0001'), Decimal('0.00751')),
    (Decimal('0.01'), Decimal('19.001')),
])
def test_not_multiple_of_tenths(divisor, value):
    assert_invalid({'multipleOf': divisor}, value, 'multipleOf')


def test_multiple_of_does_not_use_epsilon():
    # Off by a single unit in the last place must fail; float 0.3/0.1 passes by luck,
    # but an exact near-miss must not be accepted.
    schema = {'multipleOf': Decimal('0.1')}
    assert_invalid(schema, Decimal('0.3000000000000000000000000001'), 'multipleOf')
    assert_invalid(schema, Decimal('0.2999999999999999999999999999'), 'multipleOf')


def test_multiple_of_zero_and_negatives():
    schema = {'multipleOf': Decimal('0.1')}
    assert validate(schema, 0) == 0
    assert validate(schema, Decimal('-0.3')) == Decimal('-0.3')
    assert_invalid(schema, Decimal('-0.31'), 'multipleOf')


def test_multiple_of_tiny_exponent():
    schema = {'multipleOf': Decimal('1E-100000')}
    assert validate(schema, Decimal('12345E-100000')) == Decimal('12345E-100000')
    assert validate(schema, Decimal('1E-100000')) == Decimal('1E-100000')
    assert_invalid(schema, Decimal('1E-100001'), 'multipleOf')
    assert validate(
        {'multipleOf': Decimal('1E-100001')}, Decimal('1E-100000'),
    ) == Decimal('1E-100000')


def test_multiple_of_huge_integer():
    big = 10 ** 1000
    schema = {'multipleOf': big}
    assert validate(schema, big * 7) == big * 7
    assert_invalid(schema, big * 7 + 1, 'multipleOf')
    # A huge Decimal integer constant must stay exact.
    assert validate({'maximum': big}, big) == big
    assert_invalid({'maximum': big}, big + 1, 'maximum')


def test_multiple_of_must_be_positive():
    with pytest.raises(JsonSchemaDefinitionException):
        compile({'multipleOf': 0}, exact_decimal=True)
    with pytest.raises(JsonSchemaDefinitionException):
        compile({'multipleOf': Decimal('-0.1')}, exact_decimal=True)


# --------------------------------------------------------------------------
# NaN and infinity
# --------------------------------------------------------------------------

@pytest.mark.parametrize('value', [
    Decimal('NaN'), Decimal('sNaN'), Decimal('Infinity'), Decimal('-Infinity'),
    float('nan'), float('inf'), float('-inf'),
])
def test_non_finite_data_rejected_by_type(value):
    assert_invalid({'type': 'number'}, value, 'type')
    assert_invalid({'type': 'integer'}, value, 'type')


@pytest.mark.parametrize('value', [
    Decimal('NaN'), Decimal('Infinity'), Decimal('-Infinity'),
    float('nan'), float('inf'), float('-inf'),
])
@pytest.mark.parametrize('keyword_schema', [
    {'minimum': 0},
    {'maximum': 10},
    {'exclusiveMinimum': 0},
    {'exclusiveMaximum': 10},
    {'multipleOf': 1},
])
def test_non_finite_data_rejected_by_numeric_keywords(value, keyword_schema):
    assert_invalid(keyword_schema, value)


@pytest.mark.parametrize('keyword_schema', [
    {'minimum': 0},
    {'maximum': 10},
    {'exclusiveMinimum': 0},
    {'exclusiveMaximum': 10},
    {'multipleOf': 1},
])
def test_non_numbers_ignored_by_numeric_keywords(keyword_schema):
    # Without a "type" keyword, non-numeric values (including booleans) are
    # simply not checked by numeric constraints.
    validator = compile(keyword_schema, exact_decimal=True)
    for value in ('NaN', None, True, False, [], {'x': 1}):
        assert validator(value) == value


@pytest.mark.parametrize('keyword', [
    'minimum', 'maximum', 'multipleOf', 'exclusiveMinimum', 'exclusiveMaximum',
])
def test_non_finite_schema_constants_rejected(keyword):
    with pytest.raises(JsonSchemaDefinitionException):
        compile({keyword: Decimal('NaN')}, exact_decimal=True)
    with pytest.raises(JsonSchemaDefinitionException):
        compile({keyword: Decimal('Infinity')}, exact_decimal=True)
    with pytest.raises(JsonSchemaDefinitionException):
        compile({keyword: float('inf')}, exact_decimal=True)


# --------------------------------------------------------------------------
# enum / const numeric equality
# --------------------------------------------------------------------------

def test_enum_numeric_equality_across_types():
    validator = compile({'enum': [Decimal('1.0'), Decimal('2.5'), 'x', None]}, exact_decimal=True)
    assert validator(1) == 1
    assert validator(1.0) == 1.0
    assert validator(Decimal('1.00')) == Decimal('1.00')
    assert validator(2.5) == 2.5
    assert validator(Decimal('2.5')) == Decimal('2.5')
    assert validator('x') == 'x'
    assert validator(None) is None


def test_enum_bool_does_not_match_number():
    validator = compile({'enum': [1, 0]}, exact_decimal=True)
    for value in (True, False):
        with pytest.raises(JsonSchemaValueException):
            validator(value)


def test_enum_nan_constant_rejected():
    with pytest.raises(JsonSchemaDefinitionException):
        compile({'enum': [1, Decimal('NaN')]}, exact_decimal=True)
    with pytest.raises(JsonSchemaDefinitionException):
        compile({'enum': [{'x': Decimal('Infinity')}]}, exact_decimal=True)


def test_const_numeric_equality():
    validator = compile({'const': Decimal('0.1')}, exact_decimal=True)
    assert validator(0.1) == 0.1
    assert validator(Decimal('0.1')) == Decimal('0.1')
    with pytest.raises(JsonSchemaValueException):
        validator(0.2)


def test_const_nan_rejected():
    with pytest.raises(JsonSchemaDefinitionException):
        compile({'const': Decimal('Infinity')}, exact_decimal=True)


# --------------------------------------------------------------------------
# Parsed JSON (billing API use case)
# --------------------------------------------------------------------------

def test_json_parsed_with_decimal():
    schema = {
        'type': 'object',
        'properties': {
            'amount': {'type': 'number', 'minimum': Decimal('0.01'),
                       'maximum': Decimal('999999.99'), 'multipleOf': Decimal('0.01')},
            'qty': {'type': 'integer'},
        },
        'required': ['amount', 'qty'],
    }
    validator = compile(schema, exact_decimal=True)

    data = json.loads('{"amount": 19.01, "qty": 3}', parse_float=Decimal, parse_int=int)
    assert validator(data) == data

    bad = json.loads('{"amount": 19.001, "qty": 3}', parse_float=Decimal)
    with pytest.raises(JsonSchemaValueException) as exc:
        validator(bad)
    assert exc.value.rule == 'multipleOf'


# --------------------------------------------------------------------------
# Exported code: same verdicts under a different Decimal context precision
# --------------------------------------------------------------------------

def _load_exported(code):
    namespace = {}
    exec(builtins.compile(code, '<exported>', 'exec'), namespace, namespace)
    return namespace['validate']


def test_exported_constants_exact_under_low_precision(tmp_path):
    schema = {
        'type': 'number',
        'minimum': Decimal('0.1'),
        'maximum': Decimal('999999.9999999999'),
        'multipleOf': Decimal('0.1'),
        'enum': [Decimal('0.3'), Decimal('123456789.123456789')],
    }
    code = compile_to_code(definition=schema, exact_decimal=True)
    exported = _load_exported(code)

    # And also keep the file to verify it is standalone source.
    (tmp_path / 'validator.py').write_text(code)

    with localcontext() as ctx:
        ctx.prec = 2
        assert exported(Decimal('0.3')) == Decimal('0.3')
        assert exported(0.3) == 0.3
        with pytest.raises(JsonSchemaValueException):
            exported(Decimal('0.31'))
        with pytest.raises(JsonSchemaValueException):
            exported(Decimal('123456789.12345678'))
        with pytest.raises(JsonSchemaValueException):
            exported(Decimal('0.1') - Decimal('1E-50'))


def test_exported_and_in_memory_agree_across_precisions():
    schema = {'multipleOf': Decimal('0.3'), 'minimum': Decimal('-1E1000')}
    cases = [
        (Decimal('0.9'), True),
        (Decimal('-0.9'), True),
        (Decimal('0.3'), True),
        (Decimal('0'), True),
        (Decimal('0.91'), False),
        (Decimal('1E-100'), False),
        (Decimal('1E-101'), False),
        (10 ** 100 * 3, True),
        (10 ** 100 * 3 + 1, False),
    ]

    def verdict(validator, value):
        try:
            validator(value)
            return True
        except JsonSchemaValueException:
            return False

    in_memory = compile(schema, exact_decimal=True)
    exported = _load_exported(compile_to_code(definition=schema, exact_decimal=True))

    for precision in (1, 2, 6, 28, 50):
        with localcontext() as ctx:
            ctx.prec = precision
            for value, expected in cases:
                assert verdict(in_memory, value) is expected
                assert verdict(exported, value) is expected


# --------------------------------------------------------------------------
# Default mode is unchanged
# --------------------------------------------------------------------------

def test_default_mode_unchanged_for_float_multipleof():
    # Existing float-based behavior keeps working without exact_decimal.
    validator = compile({'multipleOf': 0.01}, exact_decimal=False)
    assert validator(19.01) == 19.01


def test_exported_default_mode_has_no_numeric_import():
    code = compile_to_code({'type': 'number', 'minimum': 0}, exact_decimal=False)
    assert 'fastjsonschema._numeric' not in code
