# PharmaCare on AWS: reviewer guide

A FastAPI/PostgreSQL pharmacy demo with Compose, Jenkins, permission tests, and deployment documentation.

## Start the review

Show stock or permission behavior, then explain the current Jenkins test/deploy/health/rollback path. A container rollback is not a database restore.

| Source | Review focus |\n| --- | --- |\n| [Dockerfile](Dockerfile) | Build context, runtime configuration, ports, and persistence |\n| [Jenkinsfile](Jenkinsfile) | Triggers, credentials, failure handling, and deploy conditions |\n| [compose.yml](compose.yml) | Build context, runtime configuration, ports, and persistence |\n| [.github/workflows/permission-tests.yml](.github/workflows/permission-tests.yml) | Triggers, credentials, failure handling, and deploy conditions |\n| [app/backend/gst.py](app/backend/gst.py) | Implementation, assumptions, and operational boundaries |\n| [app/backend/main.py](app/backend/main.py) | Implementation, assumptions, and operational boundaries |

## A useful interview walkthrough

1. State the problem and the specific part you implemented or changed.
2. Open the source above and follow one request, release, or failure from start to finish.
3. Show a reproducible result, including an actual failure and the observation that confirms recovery.
4. Explain one tradeoff and one limitation. Distinguish a local test from a live deployment.

## Evidence and limits

This guide is based on the default-branch source inspected on 16 October 2026. It is a source review, not a fresh deployment or a certification of every feature. Existing CI runs and tests should be checked at the commit being demonstrated. Do not present screenshots, inherited code, planned features, or old README statements as proof of a current deployment.
