# Optional ecosystem integration

CloudLaunch retains its Pharmacy application, PostgreSQL, Jenkins deployment and rollback image. Ops Pilot owns incident orchestration; no repair engine is copied here. [Shared architecture and contracts](https://github.com/Vishnu063/ops-pilot/blob/feat/unified-devops-ecosystem/docs/ecosystem/INTEGRATION.md).

## Production pipeline configuration

Existing deployment host paths are unchanged. The pipeline now tags releases with commit/build identifiers, exports `APP_VERSION`, reports started/succeeded/failed and rollback lifecycle events, and can scan the exact built image ID before deploying. `/metrics` exposes bounded release identity and actual DB readiness; `/health` still verifies DB connectivity. Metrics do not establish business-transaction correctness.

All external integration is opt-in:

| Setting | Meaning |
| --- | --- |
| `OPS_PILOT_CLIENT` | Absolute path to the reviewed Ops Pilot stdlib `events_client.py`; unset disables producer execution |
| `OPS_PILOT_EVENTS_URL` | Exact HTTPS `/api/events` URL, or loopback HTTP; unset records locally only |
| `OPS_PILOT_INGEST_TOKEN` | Secure machine credential, never a dashboard approval credential |
| `OPS_PILOT_SERVICE` | Exact configured Pilot container name; defaults to `pharmacy-app` |
| `CLOUDLAUNCH_EVENT_DIR` | Private JSONL audit directory; defaults to ignored `.deployment-events` |
| `CLOUDLAUNCH_TRIVY_ENABLED` | `true` requires installed Trivy and scans built image for HIGH/CRITICAL findings before deployment |
| `CLOUDLAUNCH_ALLOW_ROLLBACK` | Defaults false; explicit per-job/operator authorization for the documented rollback policy below |
| `APP_VERSION` | Commit/build release identifier injected by deployment |

Event delivery is bounded and best effort; failure is reported without replacing the deployment outcome. The local JSONL remains available for replay with its exact ID/timestamp. Do not put tokens in build arguments or Jenkins logs. The Trivy report can contain package information and is ignored by Git; scanning is not a claim of zero vulnerabilities. The exact lab image was scanned with Trivy 0.67.2: the gate correctly exited 1 for 44 HIGH Debian findings, with no fixed versions listed. No findings were suppressed. See `validation/trivy-summary.json`.

The old pipeline rolled back automatically. It now requires explicit `CLOUDLAUNCH_ALLOW_ROLLBACK=true`. Enable only after the operator has reviewed that this is an app-only change, the retained image is a tested compatible release, no incompatible DB/schema/config migration occurred, the named target is owned by this job, interruption is acceptable and one rollback has been approved for this build. Otherwise leave disabled and use an operator-reviewed recovery. Rollback verification requires both the retained image ID and actual Docker HTTP/database healthcheck; a failed/unavailable verification emits `rollback_failed`. This legacy production path has not been executed here. New lab policy authorizes only its own disposable restart and never invokes this pipeline.

## Disposable demo and Jenkins proof

Use `compose.lab.yml` only as a standalone project with a unique generated `ecosystem-lab-*` name. It publishes loopback ports, creates a disposable `pharmacy_test` DB, uses explicit env-injected lab credentials, and limits each service to 192 MiB/0.5 CPU. Never merge with the production Compose file. Labs' `integrations/ecosystem_lab.py` owns generation, readiness, failure, approval verification and cleanup.

`Jenkinsfile.ecosystem` is an optional parameterized wrapper around that runner. It requires reviewed sibling checkouts, the prepared `ecosystem-venv`, trusted monitoring binaries, and explicit `RUN_DISPOSABLE_FAILURE=true`. Its declarative Pipeline execution needs the normal Jenkins Pipeline plugins; this file was shell-syntax checked, not executed by a Pipeline plugin.

A real temporary Jenkins **freestyle** job executed the same runner successfully during development. To reproduce on a fresh disposable controller only: create an empty private `JENKINS_HOME`, put `jenkins-lab.groovy` in `init.groovy.d/`, securely generate a password file, set `JENKINS_LAB_PASSWORD_FILE`, `ECOSYSTEM_ROOT`, `MONITORING_TOOLS` and explicitly `ECOSYSTEM_RUN_LAB=true`, then start a trusted Jenkins WAR with Java 21, `-Xmx512m -Djenkins.install.runSetupWizard=false`, `--httpListenAddress=127.0.0.1` and a free port. The init creates one authenticated local owner, disables anonymous access, uses one executor and schedules only the disposable job when the flag is set. No plugins, production Jenkins home or production credentials are imported. Stop the temporary controller and remove its own generated credential/home after preserving non-secret evidence.

## Validation and known limits

32 CloudLaunch tests passed with 16 subtests. Existing test fixtures were corrected to scope their authorization override, use HTTPS for secure cookies and isolate the owner password binding; production authentication was not weakened. A real Docker/PostgreSQL deployment and monitored restart recovery passed, both directly and through disposable Jenkins. A clean vulnerability scan, production rollback, production hosting and full-stack 8 GB capacity remain unverified. [Cross-project evidence](https://github.com/Vishnu063/ops-pilot/blob/feat/unified-devops-ecosystem/docs/ecosystem/VALIDATION.md).
