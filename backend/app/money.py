from decimal import ROUND_DOWN, Decimal, InvalidOperation

ZERO = Decimal("0")


def to_decimal(value: object, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def quantize(value: Decimal, quantum: Decimal) -> Decimal:
    if quantum <= ZERO:
        return value
    steps = (value / quantum).to_integral_value(rounding=ROUND_DOWN)
    return (steps * quantum).quantize(quantum)


def discounted_max_price(
    floor_price: Decimal,
    discount_percent: Decimal,
    quantum: Decimal = Decimal("0.00001"),
) -> Decimal:
    if floor_price < ZERO:
        floor_price = ZERO
    raw = floor_price * (Decimal("1") - (discount_percent or ZERO) / Decimal("100"))
    if raw < ZERO:
        raw = ZERO
    return quantize(raw, quantum)


def increase_by_step(base: Decimal, step: Decimal, quantum: Decimal) -> Decimal:
    return quantize(base + step, quantum)


def money_str(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
