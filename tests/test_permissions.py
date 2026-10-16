"""Regression checks for deny-by-default staff permissions."""
import unittest
from app.backend.permissions import ROLES, allowed_roles, can_access


class StaffPermissionTests(unittest.TestCase):
    def test_owner_only_security_and_user_admin(self):
        sensitive = [
            ("GET", "/api/users"),
            ("POST", "/api/users"),
            ("PUT", "/api/users/1"),
            ("POST", "/api/users/1/reset-password"),
            ("GET", "/api/security/audit"),
            ("POST", "/api/security/change-password"),
            ("PUT", "/api/pharmacy-settings"),
            ("PUT", "/api/owner-profile"),
        ]
        for method, path in sensitive:
            with self.subTest(path=path):
                self.assertEqual(allowed_roles(method, path), frozenset())

    def test_cashier_may_bill_but_cannot_adjust_stock_or_refund(self):
        self.assertTrue(can_access("cashier", "POST", "/api/sales"))
        self.assertTrue(can_access("cashier", "GET", "/api/medicines"))
        self.assertFalse(can_access("cashier", "POST", "/api/medicines/4/stock"))
        self.assertFalse(can_access("cashier", "POST", "/api/returns"))
        self.assertFalse(can_access("cashier", "POST", "/api/purchase-orders"))

    def test_inventory_may_receive_but_not_create_purchase_orders(self):
        self.assertTrue(can_access("inventory", "POST", "/api/purchase-orders/8/receive"))
        self.assertTrue(can_access("inventory", "POST", "/api/medicines/8/stock"))
        self.assertFalse(can_access("inventory", "POST", "/api/purchase-orders"))
        self.assertFalse(can_access("inventory", "POST", "/api/sales"))

    def test_pharmacist_prescriptions_and_sales(self):
        self.assertTrue(can_access("pharmacist", "POST", "/api/prescriptions"))
        self.assertTrue(can_access("pharmacist", "POST", "/api/sales"))
        self.assertFalse(can_access("pharmacist", "DELETE", "/api/medicines/2"))

    def test_manager_cannot_manage_owner_credentials(self):
        self.assertTrue(can_access("manager", "GET", "/api/finance/summary"))
        self.assertFalse(can_access("manager", "GET", "/api/users"))
        self.assertFalse(can_access("manager", "POST", "/api/security/change-password"))

    def test_unknown_routes_methods_and_path_tricks_denied(self):
        for method, path in [
            ("GET", "/api/unknown"),
            ("POST", "/api/summary"),
            ("GET", "/api/medicines/1/stock"),
            ("POST", "/api/medicines/1/stock/extra"),
            ("POST", "/api/medicines/one/stock"),
            ("GET", "/api/users/../medicines"),
            ("GET", "/api/users"),
            ("GET", "/api/pharmacy-settings"),
        ]:
            with self.subTest(method=method, path=path):
                self.assertFalse(any(can_access(r, method, path) for r in ROLES))


if __name__ == "__main__":
    unittest.main()
