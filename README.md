# PharmaCare — Pharmacy Management System

## Optional ecosystem integration

Optional Ops Pilot deployment events, bounded release/DB metrics, immutable release tags, opt-in Trivy and an explicitly authorized rollback policy. The disposable monitored recovery passed; production integration remains unverified.

[Architecture, configuration, test evidence and known limits](integrations/README.md).

A pharmacy management project built with **FastAPI, PostgreSQL, Docker Compose, and Nginx**. It covers stock and medicine batches, suppliers, purchasing, sales, customers, prescription records, reporting, and staff accounts with role-based access control (RBAC).

> **Project status:** Actively developed demo. The application has been deployed on AWS EC2 and checked through an HTTPS health endpoint. **Do not use with real patient data or as a production pharmacy system yet.** Backup/restore verification, a full end-to-end test pass, and additional security/compliance work remain open.

## Live demo

- **HTTPS:** [https://13-201-104-76.sslip.io](https://13-201-104-76.sslip.io)
- **Health:** [https://13-201-104-76.sslip.io/health](https://13-201-104-76.sslip.io/health)
- **API health/login check:** [https://13-201-104-76.sslip.io/api/auth](https://13-201-104-76.sslip.io/api/auth)

Availability depends on the EC2 instance being running and retaining its current public IP. No public demo credentials are provided. `sslip.io` is a temporary, IP-based hostname, not a permanent domain.

## Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Uvicorn |
| Database | PostgreSQL 16 |
| Frontend | HTML, CSS and JavaScript (`app/static/index.html`) |
| Runtime | Docker and Docker Compose |
| Reverse proxy / TLS | Nginx, Let's Encrypt / Certbot |
| CI/CD | Jenkinsfile; GitHub Actions permission regression tests |
| Infrastructure | AWS EC2 (Ubuntu) |

## Implemented areas

- Medicine inventory, batch and expiry information, stock adjustments and movement history
- Suppliers and purchase orders, including receiving
- Sales, returns, customers and prescription records
- Inventory, sales-related and GST reporting APIs
- Pharmacy and owner profile/settings
- Owner login, staff users, and RBAC API rules for `manager`, `pharmacist`, `cashier` and `inventory`
- Password-change and audit-log APIs
- Docker health checks and HTTPS reverse proxy

**Scope limitations:** Having an API or screen does not guarantee every business scenario is tested. This project does not claim clinical prescription validation, completed tax/legal compliance, certified payments, working receipt hardware, or a verified disaster-recovery procedure.

## Repository layout

```text
app/
  backend/
    main.py            # FastAPI routes, models and sessions
    gst.py             # GST calculation helpers
    permissions.py     # Staff permission matrix
  static/
    index.html         # Frontend
compose.yml            # App + PostgreSQL containers
Dockerfile             # Python application image
requirements.txt
setup_admin.py         # Creates owner password hash and session secret
Jenkinsfile            # Jenkins validation / test / deployment pipeline
tests/                 # Application and RBAC tests
scripts/               # Database backup and restore scripts (not yet validated)
.github/workflows/     # GitHub Actions regression tests
```

## 1. Prerequisites

On an Ubuntu server, install Docker Engine and the Docker Compose plugin. For HTTPS, install Nginx and Certbot with its Nginx plugin. A hostname must resolve to the EC2 public IP.

The existing EC2 deployment uses:

- Application container: `pharmacy-app`
- PostgreSQL container: `pharmacy-db`
- Host-only application endpoint: `127.0.0.1:8082` → container port `80`
- Public HTTPS: Nginx on port `443`

A fresh machine also needs a PostgreSQL password and administrator account. **Never commit your `.env`, database dumps, certificates, or private keys.**

## 2. Clone and configure

```bash
git clone https://github.com/Vishnu063/cloudlaunch.git
cd cloudlaunch

# Create a private local environment file (never commit it).
umask 077
cat > .env <<'EOF'
POSTGRES_PASSWORD=REPLACE_WITH_A_LONG_RANDOM_PASSWORD
EOF
chmod 600 .env

# Choose your owner password interactively (16+ characters).
python3 setup_admin.py
```

`setup_admin.py` stores `ADMIN_PASSWORD_HASH` and `SESSION_SECRET` in `.env`. The app requires all three secrets. Use a strong, distinct database password; avoid shell history or shared screenshots containing secret values.

> **Important:** Do not run `setup_admin.py` to reset credentials on an existing deployment without understanding its effect: it replaces the administrator hash and session signing key, invalidating existing sessions.

## 3. Build and start the application

```bash
sudo docker compose up -d --build
sudo docker compose ps

curl -fsS http://127.0.0.1:8082/health
curl -fsS http://127.0.0.1:8082/api/auth
```

A healthy response looks like:

```json
{"status":"healthy","database":"connected"}
```

The anonymous auth endpoint should respond with `{"authenticated":false}`.

**Don't expose port 8082 publicly:** `compose.yml` binds it to `127.0.0.1`. During local development on the host, visit `http://127.0.0.1:8082`. If you need access from your laptop before setting up HTTPS, use an SSH tunnel:

```bash
ssh -i /path/to/your-key.pem -N \
  -L 127.0.0.1:9090:127.0.0.1:8082 ubuntu@YOUR_EC2_PUBLIC_IP
```

Then visit `http://127.0.0.1:9090` on your laptop. The tunnel stays open while the SSH command runs.

## 4. HTTPS with Nginx

The live deployment uses a **dedicated hostname** for PharmaCare. The API lives at the **root** (`/api/...`); avoid hosting this frontend under `/pharmacy/` without adapting its API paths.

Example Nginx site (replace `YOUR_HOSTNAME` with a DNS name pointing to your server):

```nginx
server {
    listen 80;
    server_name YOUR_HOSTNAME;

    location / {
        proxy_pass http://127.0.0.1:8082;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Install this as an Nginx site *alongside*, not in place of, any other application's configuration. Verify the configuration before reloading:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

After DNS resolves and inbound ports 80 and 443 are allowed:

```bash
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_HOSTNAME --redirect

curl -fsS https://YOUR_HOSTNAME/health
curl -fsS https://YOUR_HOSTNAME/api/auth
```

The existing deployment's Nginx configuration is maintained **on the EC2 host**, not automatically installed from this repository. A Let's Encrypt certificate was issued for `13-201-104-76.sslip.io`; renewals depend on continued DNS reachability.

**AWS Security Group:** Allow port 443 for HTTPS, port 80 for redirects/certificate validation, and SSH port 22 only from trusted addresses. Remove any public inbound rule for port **8082**. PostgreSQL port **5432** must not be publicly exposed.

The FastAPI session middleware uses HTTPS-only cookies. Log in through the **HTTPS hostname**, not the direct HTTP IP/port.

## 5. Updating EC2 from GitHub

Run this in `~/cloudlaunch` after reviewing the incoming commits:

```bash
git status --short
git fetch origin main
git log --oneline HEAD..origin/main
git pull --ff-only origin main

# Preserve the existing image for application rollback.
OLD_IMAGE=$(sudo docker inspect -f '{{.Image}}' pharmacy-app)
sudo docker image tag "$OLD_IMAGE" cloudlaunch-app:pre-update

# Rebuild the app only; do not recreate the database.
sudo docker compose up -d --no-deps --build app
sudo docker compose ps
curl -fsS http://127.0.0.1:8082/health
```

**Caution:** A Docker image tag is *not* a database backup. Do not deploy schema-changing updates before verified database backups and migration procedures exist. Do not run `docker compose down -v` unless you explicitly intend to delete persistent volumes.

## 6. Tests

GitHub Actions runs unit/regression tests for role permissions and HTTP login/session access with an isolated test database.

```bash
# Run pure role-matrix tests without a running database.
python3 -m unittest discover -s tests -p 'test_permissions.py' -v
```

Broader `pytest` tests are guarded by `tests/conftest.py` and require a **dedicated test database** whose URL contains `pharmacy_test`. Never point test commands at the live `pharmacy` database.

```bash
# Example only after you provision a separate test database and dependencies:
# DATABASE_URL=postgresql+psycopg://.../pharmacy_test pytest -q tests/
```

GitHub Actions passing does not substitute for browser-level functional, security, and deployment testing.

## 7. Troubleshooting

| Symptom | Check / action |
| --- | --- |
| Browser shows “Cannot connect to the application” | `curl -fsS http://127.0.0.1:8082/api/auth`; frontend must call `/api/auth`, **not** `/pharmacy/api/auth` on the dedicated hostname |
| `curl -I` returns HTTP 405 | The endpoint supports GET rather than HEAD; try `curl -fsS URL` |
| Container not healthy | `sudo docker compose ps` and `sudo docker compose logs --tail=100 app` |
| Database connection issues | `sudo docker compose ps db` and `sudo docker compose logs --tail=100 db` |
| Nginx changes don't work | `sudo nginx -t`, inspect `/etc/nginx/sites-enabled/`, then reload |
| Public IP HTTPS inaccessible | Check DNS, EC2 running state, security-group ports 80/443, and TLS certificate |
| SSH tunnel appears “stuck” | Expected with `ssh -N`; leave that terminal open |
| Local tunnel port already in use | Choose another local port, for example 9090 |
| HTTPS owner login behaves unexpectedly | Confirm HTTPS-only cookies and same-host `/api/login`; don't submit passwords on HTTP |

## 8. Backup and restore — pending validation

The repository contains `scripts/backup-db.sh` and `scripts/restore-db.sh`, but an earlier backup attempt was unsuccessful. **Do not assume either script is operational or use the restore script against production without first testing on a disposable database.**

A complete recovery plan still needs successful backups, off-instance encrypted storage, retention, periodic automated runs, and a tested restore procedure. Neither Git nor tagged Docker images protect database records.

## 9. Before production use

- [ ] Verify PostgreSQL backup, restore, retention, and off-instance recovery
- [ ] Run end-to-end tests for medicine inventory, sales, returns, purchase orders and prescriptions
- [ ] Test role restrictions with real user sessions and account revocation
- [ ] Verify HTTPS-only cookies, CSRF protection, login throttling, and access controls
- [ ] Confirm port 8082 is closed in AWS security groups; audit ports 22 and 5432
- [ ] Introduce controlled database migrations, operational alerts and monitoring
- [ ] Review pharmacy-specific legal, privacy, tax and clinical compliance requirements
- [ ] Validate barcode/receipt printing and remaining business workflow gaps before claiming completion

## Development notes

**Repository:** [Vishnu063/cloudlaunch](https://github.com/Vishnu063/cloudlaunch). Contributions should avoid committing secrets, sensitive data, generated backup files or local machine state.

This project is provided for learning and development. Its current behavior should not be interpreted as certified medical, financial or regulatory functionality.
