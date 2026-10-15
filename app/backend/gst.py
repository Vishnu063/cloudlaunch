from decimal import Decimal, ROUND_HALF_UP

TWOPLACES = Decimal("0.01")


def money(value):
    return Decimal(str(value)).quantize(
        TWOPLACES, rounding=ROUND_HALF_UP
    )


def calculate_gst(unit_price, quantity, gst_rate,
                  discount=0, interstate=False):
    price = Decimal(str(unit_price))
    rate = Decimal(str(gst_rate))
    discount = Decimal(str(discount))

    if price < 0 or quantity <= 0:
        raise ValueError("Invalid price or quantity")
    if rate < 0 or rate > 100:
        raise ValueError("Invalid GST rate")

    subtotal = money(price * quantity)
    if discount < 0 or discount > subtotal:
        raise ValueError("Invalid discount")

    taxable = money(subtotal - discount)
    tax = money(taxable * rate / Decimal("100"))

    if interstate:
        cgst = sgst = Decimal("0.00")
        igst = tax
    else:
        cgst = money(tax / 2)
        sgst = tax - cgst
        igst = Decimal("0.00")

    return {
        "subtotal": subtotal,
        "discount": discount,
        "taxable": taxable,
        "gst_rate": rate,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "total": taxable + tax,
    }
