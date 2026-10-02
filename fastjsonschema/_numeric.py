"""
Exact decimal helpers for validators compiled with ``exact_decimal=True``.

Everything here avoids :class:`float` arithmetic as well as context-rounded
``Decimal`` operations (``/``, ``%``, ``remainder_near`` ...), so validation
results do not depend on the current :class:`decimal.Decimal` context.
"""
from decimal import Decimal


def to_decimal(value):
    """
    Convert a JSON number (``int``, ``float`` or ``Decimal``) to ``Decimal``
    without losing precision.

    Floats are converted through their shortest round-trip representation
    (``repr``), not through the binary value, so ``0.1`` stays exactly ``0.1``.
    Constructing a ``Decimal`` from an int or a string never rounds, therefore
    the current Decimal context precision is irrelevant.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def is_finite_number(value):
    """Whether ``value`` is a JSON number (bool excluded) that is finite."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, float):
        return value == value and value not in (float('inf'), float('-inf'))
    return True


def is_integer_number(value):
    """
    Whether a finite JSON number (bool excluded) carries an integral value.

    JSON number semantics apply: ``1.0`` is an integer, ``Decimal('1.0')``
    is an integer. The check works on the Decimal coefficient and exponent,
    so it never rounds and is independent of the Decimal context.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    if isinstance(value, int):
        return True
    value_decimal = to_decimal(value)
    if not value_decimal.is_finite():
        return False
    return _is_integral(value_decimal)


def numbers_equal(left, right):
    """
    Exact numeric equality of two JSON numbers (bools are never numbers).

    Cross-type comparison (int/float/Decimal) is exact: both sides are
    compared as Decimals constructed without rounding.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, (int, float, Decimal)) or not isinstance(right, (int, float, Decimal)):
        return False
    return to_decimal(left) == to_decimal(right)


def is_multiple(value, divisor):
    """
    Whether ``value`` is an exact multiple of ``divisor``.

    Both arguments may be int, float or Decimal. The decision is computed
    from integer coefficients only (``a / b == n`` for some integer ``n``
    iff ``num_a * den_b == num_b * den_a * n``), so it never rounds, uses no
    epsilon and no float arithmetic, and is independent of the Decimal
    context precision.
    """
    value_decimal = to_decimal(value)
    divisor_decimal = to_decimal(divisor)
    if divisor_decimal == 0:
        raise ZeroDivisionError('multipleOf divisor is zero')
    if value_decimal == 0:
        return True
    value_num, value_den = _integer_ratio(value_decimal)
    divisor_num, divisor_den = _integer_ratio(divisor_decimal)
    return (value_num * divisor_den) % (divisor_num * value_den) == 0


def _integer_ratio(value_decimal):
    """Exact (numerator, denominator) integers of a finite Decimal."""
    sign, digits, exponent = value_decimal.as_tuple()
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
    if sign:
        coefficient = -coefficient
    if exponent >= 0:
        return coefficient * 10 ** exponent, 1
    return coefficient, 10 ** (-exponent)


def _is_integral(value_decimal):
    sign, digits, exponent = value_decimal.as_tuple()
    if exponent >= 0:
        return True
    return all(digit == 0 for digit in digits[exponent:])
