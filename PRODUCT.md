# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
SOLARA employees using the Atlas employee portal, and their reporting managers reviewing comp-off credit requests.

## Product Purpose
Employees can see leave balances, request leave, and request credit for verified work on a holiday. Reporting managers approve or reject comp-off requests. The user confirmed these leave tasks should be fastest to reach from home.

## Operating Context
An existing Vue/Ionic Frappe HR progressive web app at /hrms, used on phones and desktop browsers. Atlas is SOLARA's existing HR system. Preserve attendance, check-in, shifts, expenses, advances, salary slips, notifications and profile access.

## Capabilities and Constraints
Comp-off credits are bound to the signed-in employee, verified holiday attendance and the current reporting manager. Approval creates native leave credit. Preserve server authorization, feature gating, loading and error states. No invented entitlements, leave policy, attendance, approval counts or payroll figures. Preview fixtures are synthetic and must be labelled. Current work is a candidate, not a live deployment.

## Brand Commitments
SOLARA and Atlas are confirmed names. The user rejected the basic default Frappe appearance and requested Impeccable design. On 19 September 2026 the user chose the third, green Modern HR Workspace concept: deep teal header/actions, pale teal ground, white panels and clear sans typography. The approved image is .impeccable/mocks/approved-green.png. No new logo symbol is approved.

## Product Principles
- Make leave availability and the next action immediately clear.
- Distinguish requesting earned comp-off credit from spending approved leave.
- Keep approval status and responsible manager understandable.
- Preserve all existing employee capabilities and verified data.

## Open Decisions
The green concept is selected; remaining release acceptance and operational enablement are tracked outside this design record.
