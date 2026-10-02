from decimal import Decimal

from .exceptions import JsonSchemaValueException


def _float_is_finite(value):
    return value == value and -float("inf") < value < float("inf")


def exact_json_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    if isinstance(value, float):
        if not _float_is_finite(value):
            raise ValueError("non-finite number")
        return Decimal(repr(value))
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("non-finite number")
    return value


def exact_decimal_is_integer(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if not isinstance(value, Decimal):
        return False
    sign, digits, exponent = value.as_tuple()
    del sign
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    return exponent >= 0 or all(digit == 0 for digit in digits)


def decimal_is_multiple(value, divisor):
    if value == 0:
        return True

    value_sign, value_digits, value_exponent = value.as_tuple()
    divisor_sign, divisor_digits, divisor_exponent = divisor.as_tuple()
    del value_sign, divisor_sign

    value_integer = int(Decimal((0, value_digits, 0)))
    divisor_integer = int(Decimal((0, divisor_digits, 0)))

    factor_2 = 0
    factor_5 = 0
    while divisor_integer % 2 == 0:
        divisor_integer //= 2
        factor_2 += 1
    while divisor_integer % 5 == 0:
        divisor_integer //= 5
        factor_5 += 1

    if value_integer % divisor_integer:
        return False
    remaining = value_integer // divisor_integer

    required_2 = factor_2 + divisor_exponent - value_exponent
    if required_2 > 0 and not _has_prime_factor(remaining, 2, required_2):
        return False

    required_5 = factor_5 + divisor_exponent - value_exponent
    if required_5 > 0 and not _has_prime_factor(remaining, 5, required_5):
        return False

    return True


def _has_prime_factor(value, prime, count):
    while count and value % prime == 0:
        value //= prime
        count -= 1
    return count == 0


def exact_json_number_is_multiple(value, divisor):
    value = exact_json_decimal(value)
    if value is None:
        return False
    if isinstance(value, int):
        value = Decimal(value)
    if isinstance(divisor, bool):
        return False
    divisor = Decimal(divisor) if isinstance(divisor, int) else divisor
    return decimal_is_multiple(value, divisor)


def exact_json_numbers_equal(value, expected):
    value = exact_json_decimal(value)
    expected = exact_json_decimal(expected)
    if value is None or expected is None:
        return False
    return value == expected


def reject_non_finite_json_numbers(value, name):
    try:
        _reject_non_finite_json_numbers(value, name)
    except JsonSchemaValueException as error:
        error.definition = {}
        raise error


def _reject_non_finite_json_numbers(value, name):
    if isinstance(value, Decimal) and not value.is_finite():
        raise JsonSchemaValueException(
            name + " must be a finite number",
            value=value,
            name=name,
            rule="type",
        )
    if isinstance(value, float) and not _float_is_finite(value):
        raise JsonSchemaValueException(
            name + " must be a finite number",
            value=value,
            name=name,
            rule="type",
        )
    if isinstance(value, dict):
        for key, item in value.items():
            reject_non_finite_json_numbers(item, name + "." + key)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_non_finite_json_numbers(item, "{}[{}]".format(name, index))
