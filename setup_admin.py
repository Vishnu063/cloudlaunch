import getpass
import hashlib
import secrets
from pathlib import Path

p = Path(".env")
lines = p.read_text().splitlines() if p.exists() else []
values = {}
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        values[k] = v

if not values.get("POSTGRES_PASSWORD"):
    raise SystemExit("ERROR: Database password missing; nothing changed.")

password = getpass.getpass("Choose admin password (16+ characters): ")
confirm = getpass.getpass("Confirm admin password: ")

if password != confirm:
    raise SystemExit("ERROR: Passwords do not match.")
if len(password) < 16:
    raise SystemExit("ERROR: Password must be at least 16 characters.")

salt = secrets.token_bytes(16)
iterations = 600_000
digest = hashlib.pbkdf2_hmac(
    "sha256", password.encode(), salt, iterations
).hex()

values["ADMIN_PASSWORD_HASH"] = (
    f"pbkdf2_sha256${iterations}${salt.hex()}${digest}"
)
values["SESSION_SECRET"] = secrets.token_hex(32)

p.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
p.chmod(0o600)

print("Admin credentials saved securely in .env.")
