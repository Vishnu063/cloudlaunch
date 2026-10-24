"""Live FastAPI permission checks with an isolated test SQLite database."""
import hashlib
import os
import secrets
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient


class RBACApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="pharmacy_test_rbac_")
        cls.addClassCleanup(cls.tempdir.cleanup)
        db_path = Path(cls.tempdir.name) / "pharmacy_test.sqlite3"
        os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + str(db_path)
        os.environ["SESSION_SECRET"] = "rbac-test-session-secret-not-production"
        salt = bytes.fromhex("00112233445566778899aabbccddeeff")
        digest = hashlib.pbkdf2_hmac("sha256", b"owner-test-password", salt, 310000).hex()
        os.environ["ADMIN_PASSWORD_HASH"] = "pbkdf2_sha256$310000$" + salt.hex() + "$" + digest
        from app.backend import main
        from unittest.mock import patch
        credentials = patch.object(main, "ADMIN_PASSWORD_HASH", os.environ["ADMIN_PASSWORD_HASH"])
        credentials.start()
        cls.addClassCleanup(credentials.stop)
        cls.main = main
        main.Base.metadata.create_all(main.engine)
        with main.SessionLocal() as session:
            for role in ["manager", "pharmacist", "cashier", "inventory"]:
                session.add(main.StaffUser(
                    username="rbac_" + role,
                    display_name="Test " + role,
                    role=role,
                    active=True,
                    password_hash=main.hash_new_password("staff-test-password"),
                    session_version=secrets.token_hex(24),
                ))
            session.commit()

    def client(self, role):
        client = TestClient(self.main.app, base_url="https://testserver")
        self.addCleanup(client.close)
        data = ({"password": "owner-test-password"} if role == "owner" else
                {"username": "rbac_" + role, "password": "staff-test-password"})
        response = client.post("/api/login", json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def test_anonymous_is_denied(self):
        client = TestClient(self.main.app, base_url="https://testserver")
        self.addCleanup(client.close)
        self.assertEqual(client.get("/api/medicines").status_code, 401)
        self.assertEqual(client.get("/api/users").status_code, 401)

    def test_cashier_restricted(self):
        client = self.client("cashier")
        self.assertEqual(client.get("/api/auth").json()["role"], "cashier")
        self.assertEqual(client.get("/api/sales").status_code, 200)
        self.assertEqual(client.get("/api/medicines").status_code, 200)
        self.assertEqual(client.get("/api/users").status_code, 403)
        self.assertEqual(client.post("/api/medicines/1/stock", json={"change": 4, "reason": "test"}).status_code, 403)
        self.assertEqual(client.get("/api/prescriptions").status_code, 403)

    def test_inventory_restricted(self):
        client = self.client("inventory")
        self.assertEqual(client.get("/api/medicines").status_code, 200)
        self.assertEqual(client.get("/api/purchase-orders").status_code, 200)
        self.assertEqual(client.get("/api/sales").status_code, 403)
        self.assertEqual(client.get("/api/users").status_code, 403)

    def test_pharmacist_access(self):
        client = self.client("pharmacist")
        self.assertEqual(client.get("/api/prescriptions").status_code, 200)
        self.assertEqual(client.get("/api/sales").status_code, 200)
        self.assertEqual(client.get("/api/finance/summary").status_code, 403)

    def test_manager_cannot_change_users(self):
        client = self.client("manager")
        self.assertEqual(client.get("/api/finance/summary").status_code, 200)
        response = client.post("/api/suppliers", json={"name": "RBAC Test Supplier"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(client.get("/api/users").status_code, 403)
        self.assertEqual(client.get("/api/security/audit").status_code, 403)

    def test_owner_access_preserved(self):
        client = self.client("owner")
        self.assertEqual(client.get("/api/auth").json()["role"], "owner")
        self.assertEqual(client.get("/api/users").status_code, 200)
        self.assertEqual(client.get("/api/security/audit").status_code, 200)

    def test_disabled_staff_session_revoked(self):
        client = self.client("cashier")
        with self.main.SessionLocal() as db:
            staff = db.scalar(self.main.select(self.main.StaffUser).where(
                self.main.StaffUser.username == "rbac_cashier"))
            staff.active = False
            db.commit()
        self.assertEqual(client.get("/api/sales").status_code, 401)


if __name__ == "__main__":
    unittest.main()
