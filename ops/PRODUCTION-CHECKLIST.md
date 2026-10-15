# PharmaCare production handover

These changes have NOT undergone integration testing. Do not use real pharmacy,
patient or payment data until operational and regulatory checks are complete.

## HTTPS / security
1. Set up a stable domain and DNS. Review the sample Nginx TLS config against
   the EXISTING Nginx config. Obtain and renew a valid TLS certificate.
2. Once HTTPS actually works, set COOKIE_SECURE=true in the private EC2 .env
   and redeploy. Until then, the existing HTTP login is not safe for production.
3. Restrict Jenkins 8081 and all administration ports using AWS security groups,
   SSH tunnels or VPN. Keep app 8082 bound to localhost.
4. Review CSRF protection, role permissions, browser cookies and security audit.

## Database recovery
- The daily backup and 7-file cleanup are local-only.
- Restore script targets -p cloudlaunch consistently, but do not execute on
  live data without verified backups and approved downtime.
- Optional scripts/upload-backup-s3.sh requires an existing private S3 bucket,
  AWS CLI and least-privilege IAM. It uploads the most recent local archive
  using S3 server-side AES256 encryption. Cloud fees may apply.
- Schedule off-server backups only after configuring the destination, its
  access policy and independent retention/lifecycle. Verify an isolated restore.

## Pharmacy data and regulatory gaps
- FEFO planning allocates by expiry date; final sale rechecks availability.
  Concurrent order, expiry and partial-batch scenarios need validation.
- GST report includes recorded returns as reductions. Draft credit notes are
  NOT legally issued automatically and refund obligations are NOT payments.
- Confirm GST rate/HSN, buyer information, credit note and invoice legal
  requirements with a professional before issuing fiscal documents.
- Inventory valuation is based on selling price, not cost of goods.
  Profit reports cannot be accurate without cost-of-goods tracking.
- The staff workspace provides basic role-specific operations only; additional
  purchase/customer/prescription workflows need polished interactive screens.

## Unverified at user request
Manual end-to-end browsing, automated tests, partial refund arithmetic,
FEFO concurrency, permissions by role, mobile layout, recovery drills, invoice
compliance, real barcode/printer integration and live deployment status.
Skipping tests does not establish production readiness.
