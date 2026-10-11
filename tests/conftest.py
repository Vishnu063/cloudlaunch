import os

database_url = os.environ.get("DATABASE_URL", "")
assert "pharmacy_test" in database_url, (
    "Refusing to run tests: DATABASE_URL must point to pharmacy_test"
)
