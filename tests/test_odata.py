from datetime import date
from decimal import Decimal

import pytest

from synapse.sap.odata import (
    ODataError,
    apply_orderby,
    format_key,
    from_wire,
    parse_expand,
    parse_filter,
    parse_key,
    parse_orderby,
    to_wire,
)

TYPES = {"Name": "str", "Qty": "decimal", "Day": "date", "Done": "bool", "Days": "int"}
ROWS = [
    {"Name": "O'Brien", "Qty": Decimal("10.5"), "Day": date(2026, 11, 1), "Done": False, "Days": 2},
    {"Name": "Siak", "Qty": Decimal(3), "Day": date(2026, 11, 3), "Done": True, "Days": 1},
    {"Name": "Kampar", "Qty": Decimal(7), "Day": None, "Done": False, "Days": 3},
]


def names(expr):
    pred = parse_filter(expr, TYPES)
    return [r["Name"] for r in ROWS if pred(r)]


def test_wire_round_trip():
    assert to_wire(date(2026, 10, 31), "date") == "/Date(1793404800000)/"
    assert from_wire("/Date(1793404800000)/", "date") == date(2026, 10, 31)
    assert from_wire("2026-10-31T00:00:00", "date") == date(2026, 10, 31)
    assert from_wire("/Date(1793404800000+0000)/", "date") == date(2026, 10, 31)
    assert to_wire(Decimal("1800.000"), "decimal") == "1800.000"
    assert from_wire(1800, "decimal") == Decimal(1800)
    assert to_wire(None, "date") is None


@pytest.mark.parametrize("value, typ", [("soon", "date"), (True, "decimal"), ("x", "decimal"), ("yes", "bool"),
                                        (5, "str")])
def test_from_wire_rejects(value, typ):
    with pytest.raises(ODataError) as e:
        from_wire(value, typ)
    assert e.value.status == 400


@pytest.mark.parametrize("expr, expected", [
    ("Name eq 'Siak'", ["Siak"]),
    ("Name eq 'O''Brien'", ["O'Brien"]),
    ("Qty gt 5", ["O'Brien", "Kampar"]),
    ("Qty ge 7M", ["O'Brien", "Kampar"]),
    ("Day ge datetime'2026-11-02T00:00:00'", ["Siak"]),
    ("Day eq null", ["Kampar"]),
    ("Done eq true", ["Siak"]),
    ("Days le 2 and Done eq false", ["O'Brien"]),
    ("Name eq 'Siak' or Name eq 'Kampar' and Qty gt 100", ["Siak"]),  # and binds tighter
    ("(Name eq 'Siak' or Name eq 'Kampar') and Qty gt 5", ["Kampar"]),
    ("not (Done eq true)", ["O'Brien", "Kampar"]),
    ("Day lt datetime'2026-12-01T00:00:00'", ["O'Brien", "Siak"]),  # null never satisfies an ordering
])
def test_filter(expr, expected):
    assert names(expr) == expected


@pytest.mark.parametrize("expr", [
    "Missing eq 'x'", "Qty eq 'x'", "Name eq 5", "Day eq '2026-11-01'", "Done eq 1", "Name like 'x'",
    "Name eq 'x' and", "(Name eq 'x'", "Name eq 'x')", "", "Name eq 'x' ; drop", "and eq 'x'",
])
def test_filter_errors(expr):
    with pytest.raises(ODataError) as e:
        parse_filter(expr, TYPES)
    assert e.value.status == 400


def test_orderby():
    order = parse_orderby("Done desc, Qty", TYPES)
    assert [r["Name"] for r in apply_orderby(ROWS, order)] == ["Siak", "Kampar", "O'Brien"]
    assert [r["Name"] for r in apply_orderby(ROWS, parse_orderby("Day desc", TYPES))] == ["Siak", "O'Brien", "Kampar"]
    for bad in ("Nope", "Qty sideways", ""):
        with pytest.raises(ODataError):
            parse_orderby(bad, TYPES)


def test_keys():
    assert parse_key("'4500000001'", ("PurchaseOrder",)) == {"PurchaseOrder": "4500000001"}
    two = ("PurchaseOrder", "PurchaseOrderItem")
    assert parse_key("PurchaseOrder='45',PurchaseOrderItem='10'", two) == {"PurchaseOrder": "45", "PurchaseOrderItem": "10"}
    assert format_key({"PurchaseOrder": "45", "PurchaseOrderItem": "10"}, two) == "PurchaseOrder='45',PurchaseOrderItem='10'"
    assert parse_key(format_key({"PurchaseOrder": "a'b"}, ("PurchaseOrder",)), ("PurchaseOrder",)) == {"PurchaseOrder": "a'b"}
    for bad in ("'45'", "PurchaseOrder='45'", "PurchaseOrder=45,PurchaseOrderItem='10'"):
        with pytest.raises(ODataError):
            parse_key(bad, two)


def test_expand_tree():
    assert parse_expand("to_A/to_B, to_C,to_A/to_D") == {"to_A": {"to_B": {}, "to_D": {}}, "to_C": {}}
