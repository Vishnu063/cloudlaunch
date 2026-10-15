import pytest
from decimal import Decimal
from app.backend.gst import calculate_gst


def test_intrastate_gst():
    r = calculate_gst("100", 2, "12")
    assert r["cgst"] == Decimal("12.00")
    assert r["sgst"] == Decimal("12.00")
    assert r["igst"] == Decimal("0.00")
    assert r["total"] == Decimal("224.00")


def test_interstate_gst():
    r = calculate_gst("100", 2, "12", interstate=True)
    assert r["igst"] == Decimal("24.00")
    assert r["total"] == Decimal("224.00")


def test_discount():
    r = calculate_gst("100", 2, "5", discount="20")
    assert r["taxable"] == Decimal("180.00")
    assert r["total"] == Decimal("189.00")


def test_zero_gst():
    assert calculate_gst("100", 1, 0)["total"] == Decimal("100.00")


def test_rounding():
    r = calculate_gst("99.99", 1, "5")
    assert r["cgst"] + r["sgst"] == Decimal("5.00")
    assert r["total"] == Decimal("104.99")


@pytest.mark.parametrize("price,qty,rate,discount", [
    ("-1", 1, 5, 0),
    ("100", 0, 5, 0),
    ("100", 1, -5, 0),
    ("100", 1, 101, 0),
    ("100", 1, 5, 200),
])
def test_invalid_values(price, qty, rate, discount):
    with pytest.raises(ValueError):
        calculate_gst(price, qty, rate, discount)
