"""Centralized, deny-by-default API permissions for PharmaCare staff.

Owner access is handled separately; routes not listed here remain owner-only.
This module deliberately has no dependency on the database or FastAPI.
"""
import re

ROLES = frozenset({"manager", "pharmacist", "cashier", "inventory"})
ALL = ROLES
MANAGEMENT = frozenset({"manager"})
CLINICAL = frozenset({"manager", "pharmacist"})
STOCK = frozenset({"manager", "inventory"})
SALES = frozenset({"manager", "pharmacist", "cashier"})
STOCK_READ = frozenset({"manager", "pharmacist", "inventory", "cashier"})
SUPPLIER_READ = frozenset({"manager", "pharmacist", "inventory"})

# Patterns use fullmatch: /api/users and security routes cannot
# accidentally inherit access from an adjacent route prefix.
RULES = (
    ("GET", r"/api/summary", ALL),
    ("GET", r"/api/medicines", STOCK_READ),
    ("POST", r"/api/medicines", STOCK),
    ("PUT", r"/api/medicines/[0-9]+", STOCK),
    ("DELETE", r"/api/medicines/[0-9]+", MANAGEMENT),
    ("POST", r"/api/medicines/[0-9]+/stock", STOCK),
    ("GET", r"/api/medicines/[0-9]+/movements", STOCK_READ),
    ("GET", r"/api/inventory/fefo", STOCK_READ),
    ("GET", r"/api/suppliers", SUPPLIER_READ),
    ("GET", r"/api/suppliers/[0-9]+", SUPPLIER_READ),
    ("POST", r"/api/suppliers", MANAGEMENT),
    ("PUT", r"/api/suppliers/[0-9]+", MANAGEMENT),
    ("DELETE", r"/api/suppliers/[0-9]+", MANAGEMENT),
    ("GET", r"/api/purchase-orders", STOCK),
    ("GET", r"/api/purchase-orders/[0-9]+", STOCK),
    ("POST", r"/api/purchase-orders", MANAGEMENT),
    ("POST", r"/api/purchase-orders/[0-9]+/receive", STOCK),
    ("GET", r"/api/sales", SALES),
    ("GET", r"/api/sales/[0-9]+", SALES),
    ("POST", r"/api/sales", SALES),
    ("GET", r"/api/returns", SALES),
    ("GET", r"/api/returns/[0-9]+", SALES),
    ("POST", r"/api/returns", CLINICAL),
    ("GET", r"/api/customers", SALES),
    ("GET", r"/api/customers/[0-9]+", SALES),
    ("POST", r"/api/customers", SALES),
    ("PUT", r"/api/customers/[0-9]+", SALES),
    ("DELETE", r"/api/customers/[0-9]+", MANAGEMENT),
    ("GET", r"/api/prescriptions", CLINICAL),
    ("GET", r"/api/prescriptions/[0-9]+", CLINICAL),
    ("POST", r"/api/prescriptions", CLINICAL),
    ("GET", r"/api/pharmacy-profile", MANAGEMENT),
    ("GET", r"/api/reports/stock", STOCK_READ),
    ("GET", r"/api/reports/expiry", STOCK_READ),
    ("GET", r"/api/reports/gst", MANAGEMENT),
    ("GET", r"/api/finance/summary", MANAGEMENT),
)


def allowed_roles(method: str, path: str) -> frozenset[str]:
    """Return permitted staff roles; empty means owner-only."""
    for rule_method, pattern, roles in RULES:
        if method == rule_method and re.fullmatch(pattern, path):
            return roles
    return frozenset()


def can_access(role: str, method: str, path: str) -> bool:
    return role in allowed_roles(method, path)
