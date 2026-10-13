# BRB (CoPUP) — Backend Sprint Checklist

**Related doc:** `COPUP_ERD.md` — use both files together. This file defines
*what* to build and *when*; the ERD file defines *what the data looks like*.

**Also read:** `DECISIONS.md` records settled architecture decisions (auth
strategy, scheduled jobs, lookup-table convention) and open questions that
affect ticket estimates. `CONTRIBUTING.md` remains the authoritative guide for
workflow and conventions.

**Current status: Sprint 1 (Sept 26 – Oct 10) — IN PROGRESS**

Tasks are grouped by ticket, in the order they appear in the team's sprint
plan. Each task line is a checkbox — mark `[x]` as it's built and verified.
Assignee names are kept from the original tracker; update as work is
reassigned.

---

## 🔵 Sprint 1 — Onboarding & Identity Verification (Sept 26–Oct 10)

### CP-101 — Register with PUP-affiliated email
- [ ] Reject registration server-side when email domain isn't `@iskolarngbayan.pup.edu.ph` (student) or `@pup.edu.ph` (faculty/staff) — *Kim*
- [ ] Create account record in pending/unverified state on valid submission — *Kim*
- [ ] Enforce domain-affiliation match server-side (Student → iskolarngbayan; Faculty/Staff → pup.edu.ph) — *Kim*
- [ ] Expose affiliation field in relevant API responses for display — *Kim*
- [ ] Do **not** use affiliation to gate any Borrower/Lender function — *Kim*
- [ ] Server-side required-field validation before account creation — *Kim*

### CP-102 — Verify email address (simplified confirmation screen)
> Note: can be omitted if time is short; add in a later sprint if time allows.
- [x] Send verification email on successful registration
- [x] Mark account email-verified and grant full access when link is clicked
- [x] Auto-deactivate account after 7 days unverified (scheduled job) — see deviation note below
- [x] Require re-registration for deactivated accounts (no reactivation path)

> **Deviation — CP-102 auto-deactivation deletes instead of flagging.** The
> scheduled job hard-deletes unverified accounts rather than flipping them to a
> deactivated status. An unconfirmed account has no verified contact channel, so a
> "deactivated" row would be unreachable by the owner and would hold the email
> hostage to a support ticket. Deleting releases the address for re-registration,
> which is what the next bullet requires anyway. The 7-day window is
> Admin-configurable via `SystemConfig`, and a mail outage cannot strand anyone
> because the sweep is the safety net. Endpoint:
> `POST /api/v1/jobs/deactivate-unverified/`.

### CP-103 — Log in to account
- [x] Authenticate credentials server-side
- [x] Return generic error (no email/password hint) from auth endpoint
- [x] Lock account for 15 min after 5 consecutive failed attempts (Admin-configurable)
- [x] Deny login for suspended/banned accounts
- [x] End session on logout or inactivity timeout — logout blacklists the refresh
      token; inactivity is bounded by the 15-minute access-token lifetime (see D-04)

### CP-105 — Submit identity verification document
- [x] Store uploaded document and submission record
- [x] Flag mismatches between registration info and submitted document for Admin check
- [x] Reject submission if ID number already linked to another account
- [x] Require explicit consent captured before accepting submission
- [ ] Block listing creation and item requests until user is verified — **blocked on
      CP-301/CP-501**: the `IsIdentityVerified` permission exists and is tested, but
      no listing or request endpoint has been built yet to attach it to.

### CP-106 — Admin review of identity verification
- [x] Persist approve/reject decision + reason — *Ezekiel*
- [x] Allow resubmission after rejection — *Ezekiel*
- [x] Send in-app + email notification on decision — *Ezekiel*
- [x] Unlock listing/requesting functions when status becomes Verified — *Ezekiel*

### CP-107 — Protect and log access to identity documents
- [x] Store identity documents encrypted — *Ezekiel*
- [x] Restrict document visibility to Admins only — *Ezekiel*
- [x] Log every Admin access to a document — *Ezekiel*
- [x] Release only name/contact details (never the document) via Admin-mediated process — *Ezekiel*

---

## ⚪ Sprint 2 — Marketplace Core + Deferred Onboarding (Oct 10–24)

### CP-104 — Recover forgotten password
- [ ] Send single-use, time-limited reset link to registered email
- [ ] Reject reset links older than 1 hour (Admin-configurable)
- [ ] Reject reset links that have already been used

### CP-1001 — Edit profile information
- [ ] Persist profile field updates
- [ ] Handle password change server-side (re-hash, invalidate old sessions if needed)

### CP-1002 — Change registered email with re-verification
- [ ] Require verification of new email before it becomes account of record
- [ ] Reject new email if not a valid PUP webmail domain
- [ ] Keep previous email as account of record until new one is verified

### CP-1004 — Deactivate account
- [ ] Allow deactivation only when no open orders/Unreturned case
- [ ] Block deactivation with clear message when blockers exist

### CP-301 — Search listings by keyword and filters
- [ ] Implement keyword search query logic
- [ ] Implement filter/sort query logic
- [ ] Exclude deactivated/deleted/removed listings and revoked/suspended Lenders from results

### CP-302 — Search for Lenders
- [ ] Implement Lender search query logic
- [ ] Exclude suspended/revoked Lenders from results

### CP-303 — View listing detail page
- [ ] Build detail-fetch endpoint aggregating listing + Lender + reviews

### CP-304 — View public Lender profile
- [ ] Build profile-fetch endpoint

### CP-401 — Create a resource listing
- [ ] Block unverified users from accessing the create-listing flow
- [ ] Validate required fields server-side before publishing
- [ ] Validate image type (JPEG/PNG/WEBP) and size (max 5MB) server-side
- [ ] Restrict pickup location options to Admin-defined fixed set

### CP-402 — Edit, deactivate, or delete a listing
- [ ] Implement edit/update endpoint
- [ ] Implement deactivate endpoint (soft-remove from search)
- [ ] Block deletion server-side when listing has Confirmed/Active order

### CP-403 — Automatically maintained availability calendar
- [ ] Implement calendar logic: block dates on confirm, release on cancel/complete

### CP-1105 — Manage fixed pickup locations (Admin)
- [ ] Implement pickup-location CRUD endpoints
- [ ] Feed current location set into Lender's listing-creation dropdown

---

## ⚪ Sprint 3 — Order Lifecycle & Dashboards (Oct 24–Nov 7)

### CP-501 — Request to borrow a listing
- [ ] Implement availability/overlap validation server-side
- [ ] Reject requests outside listing availability, targeting own listing, or exceeding borrowing limit
- [ ] Create order with status Requested and notify Lender on valid request

### CP-502 — Accept or decline a borrow request
- [ ] Set order to Confirmed + block dates on acceptance
- [ ] Set order to Declined + release dates on decline
- [ ] Auto-expire unanswered requests after 48h (Admin-configurable)

### CP-503 — Cancel a Requested or Confirmed order
- [ ] Implement cancellation endpoint (state validation, date release)
- [ ] Notify other party on cancellation

### CP-504 — Generate and validate handover code
- [ ] Generate one-time code on Confirmed order ready for handover
- [ ] Validate code entry; set order Active + start tracking on success
- [ ] Reject incorrect/expired/used codes; lock after repeated failures
- [ ] Log every code generation and successful entry
- [ ] Expire codes after 3 hours (Admin-configurable)

### CP-505 — Generate and validate return code
- [ ] Generate one-time code on return initiation
- [ ] Validate code; set order Returned + stop tracking on success
- [ ] Auto-set Completed (no flag) or Disputed (damage/missing flagged)
- [ ] Apply same code rules as handover (single-use, expiry, lockout, logging)

### CP-506 — Mark orders Overdue and escalate Unreturned items
- [ ] Auto-set Overdue when end date passes without return; notify both parties
- [ ] Auto-set Unreturned after 7 days Overdue; auto-suspend Borrower
- [ ] Open Admin review case linking identity/contact/order/chat/code data
- [ ] Support Admin escalation to OSS/Campus Security with attached evidence
- [ ] Support Admin closing case as Returned/Unresolved
- [ ] Support Admin manual status correction with recorded reason

### CP-201 — View Borrower Dashboard
- [ ] Implement dashboard aggregation endpoint (profile, verification status, orders)
- [ ] Implement 'Apply for Lender role' action for verified users

### CP-203 — Apply for and access Lender Dashboard
- [ ] Implement role-application logic (grant Lender role)
- [ ] Implement Lender dashboard aggregation endpoint

---

## ⚪ Sprint 4 — Dashboards, Ratings, Core Trust & Admin (Nov 7–21)

### CP-202 — Perform order actions from Borrower Dashboard
- [ ] Wire dashboard actions to existing Epic 5 endpoints

### CP-204 — Manage listings and confirm handover/return as Lender
- [ ] Implement listing+order aggregation endpoint for Lender dashboard

### CP-205 — Revoke own Lender status
- [ ] Block revocation server-side while Confirmed/Active order exists
- [ ] Auto-decline Requested orders + notify Borrowers on revocation
- [ ] Auto-deactivate all listings and exclude from search on revocation
- [ ] Retain Borrower access/history after revocation

### CP-206 — Admin revokes a user's Lender status
- [ ] Implement Admin revoke endpoint triggering same cascade as CP-205

### CP-601 — Rate and review counterparty after order completion
- [ ] Enforce one review per party per order + 7-day submission window
- [ ] Recalculate reviewed user's average rating on new review
- [ ] Store review + link report action (ties to CP-901)

### CP-801 — Notify users of key platform events
- [ ] Implement event-triggered notification logic for all listed event types

### CP-901 — Report a user, listing, review, or message
- [ ] Implement report-submission endpoint creating Open queue entry
- [ ] Enforce one report per order/interaction server-side

### CP-902 — Automatic flagging of repeatedly reported users
- [ ] Implement auto-flag job (3+ reports in rolling 30 days)
- [ ] Leave account unrestricted until Admin confirms flag
- [ ] Restrict listing/request creation only after confirmed flag

### CP-1101 — Search, suspend, reinstate, and ban users (Admin)
- [ ] Implement user search endpoint
- [ ] Implement suspend/reinstate/ban endpoints

### CP-1102 — Remove listings and reviews (Admin)
- [ ] Implement removal endpoints
- [ ] Exclude removed listings from search results

---

## ⚪ Sprint 5 — Chat, Remaining Trust & Safety, Remaining Admin (Nov 21–Dec 5)

### CP-701 — One-to-one chat between Borrower and Lender
- [ ] Implement chat-start-from-listing/order entry points
- [ ] Implement message storage + history retrieval

### CP-702 — Block another user in chat
- [ ] Implement block logic; disable while order in progress

### CP-703 — Retain conversations linked to reports or disputes
- [ ] Implement retention logic overriding block/delete for linked conversations

### CP-802 — Configure email notification preferences
- [ ] Implement preference storage + email-gating logic per category

### CP-903 — Document and resolve item damage/missing-item disputes
- [ ] Set order to Disputed on damage/missing flag instead of Completed
- [ ] Create dispute case linking order/photos/report/chat history
- [ ] Implement Admin resolve-to-Completed or escalate-via-OSS logic

### CP-1103 — Admin review queues (verification, reports, Unreturned cases)
- [ ] Implement queue-aggregation logic across the three source types
- [ ] Implement approve/reject/resolution persistence per queue type

### CP-1104 — Configure system parameters (Admin)
- [ ] Implement config storage + endpoints
- [ ] Apply config changes without requiring redeployment

### CP-1106 — Audit logging of Admin actions
- [ ] Implement action-logging middleware for all Admin actions incl. document views
- [ ] Prevent edit/delete of log entries through normal Admin functions

### CP-1107 — Admin dashboard summary metrics
- [ ] Implement metrics-aggregation endpoint

---

## ⚪ Sprint 6 — Hardening & Release (Dec 5–19) — no new features

### Final Bug Fixes and Polishing
- [ ] Triage and fix backend/logic bugs surfaced during full regression
- [ ] Verify scheduled jobs (auto-deactivation, overdue/unreturned, code expiry) run correctly in production config
- [ ] Set up and configure production hosting/database
- [ ] Deploy backend services and run smoke tests on live environment
- [ ] Monitor for critical post-deployment issues

---

## Notes for OpenCode

- Build in sprint order. Do not start Sprint 2+ tickets until Sprint 1 is
  checked off, unless explicitly told otherwise.
- Cross-reference `COPUP_ERD.md` for the exact table/field names each task
  touches — e.g. CP-101's domain-affiliation check reads/writes
  `users.affiliation` and `users.email` as defined in Domain 1 (Accounts).
- "Admin-configurable" items (lockout duration, code expiry, request expiry,
  borrowing limit, review window) should read their value from the
  `system_configs` table (Domain 1), not be hardcoded — see CP-1104 in
  Sprint 5, which builds the config endpoints, but the *values themselves*
  are referenced starting in Sprint 1 (e.g. CP-103's 15-minute lockout).
- Scheduled-job items (CP-102 auto-deactivation, CP-506 overdue/unreturned,
  CP-504/505 code expiry) are triggered by **cron-job.org**, which the team has
  verified and uses for free. Build the token-protected endpoint
  (`POST /api/v1/jobs/check-overdue/`) required by CONTRIBUTING.md §7.2 rule 6,
  and have cron-job.org call it on a schedule with `CRON_SECRET_TOKEN` in the
  `Authorization` header. Unauthenticated requests must return `401`.
- As a safety net for records that slip between cron runs, also recompute
  time-derived statuses on read (dashboard load, order detail fetch). This is
  belt-and-braces, not a replacement for the cron job.
