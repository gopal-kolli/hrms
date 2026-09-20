# Comp-off credit recovery

The employee portal never cancels approved credits. `hrms.api.comp_off.reverse_unused_portal_credit` is a console-only maintenance helper, not a web endpoint. This release does not authorize reversing any LIVE record.

Before any LIVE recovery, obtain explicit approval for the exact request and reason. Snapshot the request, linked allocation, leave applications, and leave ledger. Take a verified database backup. Set site maintenance mode and pause the scheduler; drain all active and queued site workers and in-flight web requests. Do not rely on the Employee row lock alone: native leave booking uses a separate path. Keep the whole site closed to writes until verification and commit finish.

Use a current authenticated Administrator or enabled HR Manager/System Manager identity in a site-bound bench console. Run the helper with the exact request name and a nonblank reason. It does not commit. Inspect its result and the structured `comp_off_recovery_v1` Comment, then commit only after the operator confirms the approved request and expected delta. On failure, roll back and investigate; do not bypass its guards. Restore the original scheduler/maintenance settings only after the transaction ends and health checks pass.

Only a clean, unused allocation is eligible. Any active/pending leave request in its period, negative or non-allocation ledger, expiry, carry-forward, changed audit state, or allocation/ledger mismatch stops recovery. Such cases require separate HR reconciliation; this helper makes no assumption about which pooled credit was consumed. An existing submitted allocation can remain with zero total after reversal; do not delete it.

The helper serializes Employee, request and allocation locks, invokes native cancellation, checks the exact allocation and ledger delta and preservation of prior entries, and appends the audit Comment in one transaction. A retry returns the cancelled result only if the recorded post-state still matches; it never creates a second reversal. Forced audit or post-check failure rolls back the helper's changes to its savepoint.

Recovery acceptance must pass on independent synthetic staging before workflow activation, including full/half-day reversal, retry, consumed-credit refusal, permission denial and rollback. No recovery helper execution on real employees is part of the portal deployment.
