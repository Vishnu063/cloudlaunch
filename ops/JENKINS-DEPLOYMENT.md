# PharmaCare — Jenkins deployment playbook

Jenkins remains the **only deployment pipeline** for PharmaCare. GitHub Actions is not required or configured by these changes.

## Current workflow

- `main` is the deployed branch. Commits there trigger the existing Jenkins pipeline.
- `feature/pharmacare-production-updates-20261015` is the development branch.
- Draft PR #1 holds unfinished improvements. Keeping it unmerged prevents deployment to the running pharmacy.
- Jenkins validates the Docker Compose configuration, runs the project test suite, builds the application container, deploys it, checks Docker health and attempts an image rollback on failure.

## When EC2 is restarted

1. Confirm EC2, Docker, the PostgreSQL volume and Jenkins service are running.
2. Confirm Jenkins still points to `main` and review PR #1 first. **Do not merge just to deploy.**
3. Because billing, FEFO and permissions changed, perform a database backup and validate changes on a disposable test environment before a production merge, even if manual testing was previously skipped.
4. Merge PR #1 only when approved; the existing Jenkins job should then build and deploy on its normal trigger.
5. Review build logs, application health and the login, billing and staff screens.
6. A successful build is **not** proof of GST compliance or disaster-recovery readiness.

## Existing deployment safety limits

- `Jenkinsfile` is retained; **no GitHub Actions** were introduced.
- Jenkins runs pytest despite the user's request to skip manual testing. Keep these automated safeguards.
- Jenkins checks application health and attempts an image rollback, not a database rollback.
- Database schema changes require a separately designed migration and restore plan. Do not delete or recreate the production PostgreSQL volume.
- HTTPS, secure cookies and private Jenkins access still require configuration on the server/AWS account.
- The off-server S3 backup script is optional and not scheduled or activated by this branch.
