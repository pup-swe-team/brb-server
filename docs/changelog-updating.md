# Changelog — Updating

Running record of what changed in `brb-server`, newest first. For the reasoning
behind a change, see [`DECISIONS.md`](DECISIONS.md). For scope and ticket
checkboxes, see [`BRB_BACKEND_SPRINTS.md`](BRB_BACKEND_SPRINTS.md).

---

## 2026-10-29 — Handover & return authentication codes, overdue detection, and unreturned case administration (CP-504, CP-505, CP-506)

Branch: `feature/sprint-3_cp504-505-506-codes-overdue-escalation`.

### Added

- **CP-504 — Handover Authentication Codes (`apps/codes/`):**
  - `POST /api/v1/orders/<order_id>/handover-code/generate/`: Lender generates a single-use, 6-digit numeric handover OTP on a `Confirmed` order (superseding any previous active handover code) and sends a `code_generation` notification to the Borrower.
  - `POST /api/v1/orders/<order_id>/handover-code/verify/`: Borrower validates the handover OTP to transition the order to `Active`, ensure calendar dates are blocked, mark the code `used`, record an `AuthCodeAttempt`, and notify the Lender (`confirmed_handover`).
  - Admin-configurable `SystemConfig` keys in `apps/core/constants.py`: `auth_code_expiry_hours` (default `3`), `auth_code_lockout_threshold` (default `5`), and `auth_code_lockout_minutes` (default `15`).
  - Rejects incorrect, expired, and already-used codes (`400 Bad Request`), logs every attempt in `AuthCodeAttempt`, and enforces a 15-minute lockout (`429 Too Many Requests`) after 5 consecutive failed attempts.
- **CP-505 — Return Authentication Codes (`apps/codes/`):**
  - `POST /api/v1/orders/<order_id>/return-code/generate/`: Borrower generates a single-use, 6-digit numeric return OTP on an `Active` or `Overdue` order and notifies the Lender (`code_generation`).
  - `POST /api/v1/orders/<order_id>/return-code/verify/`: Lender validates the return OTP (enforcing the same single-use, 3-hour expiry, 5-attempt lockout, and logging rules), marks the order `Returned`, releases blocked calendar dates, notifies the Borrower (`confirmed_return`), and automatically sets the order to `Completed` (if unflagged) or `Disputed` (if damage/missing items are flagged, creating an open `Dispute` and saving any uploaded `DisputeEvidence` files).
- **CP-506 — Overdue Orders, Unreturned Escalation & Admin Controls (`apps/orders/`, `apps/core/`):**
  - `POST /api/v1/jobs/check-overdue/`: Scheduled cron endpoint (`CronSecretMixin`) that expires stale `AuthCode` rows, transitions `Active` orders with `end_date < today` to `Overdue` (notifying both parties with `overdue_status`), and transitions `Overdue` orders $\ge 7$ days past due (`SystemConfig` key `unreturned_escalation_days`, default `7`) to `Unreturned` — automatically suspending the Borrower (`account_status="suspended"`), opening an Admin `UnreturnedCase` (`status="open"`), and notifying both parties (`unreturned_status`).
  - `GET /api/v1/unreturned-cases/` and `GET /api/v1/unreturned-cases/<id>/`: Admin endpoints returning the `UnreturnedCase` queue and full review dossier linking Borrower/Lender identity & contact details (logging `AdminAccessLog(action="contact_release")` without exposing raw ID bytes), order details & override history, linked `Conversation`/`Message` chat threads, `AuthCode`/`AuthCodeAttempt` logs, and attached `DisputeEvidence` files.
  - `POST /api/v1/unreturned-cases/<id>/escalate/`: Admin escalation to PUP OSS / Campus Security with resolution notes and attached evidence files.
  - `POST /api/v1/unreturned-cases/<id>/close/`: Admin case closure as `returned` (updating the order to `returned`, recording an `OrderStatusOverride`, releasing calendar dates, and reinstating the Borrower if no other open/escalated cases remain) or `unresolved`.
  - `POST /api/v1/orders/<id>/override-status/`: Admin manual order status correction with a required reason, recorded in `OrderStatusOverride` and synchronized with listing calendar date blocks.
  - Django Admin registrations in `apps/codes/admin.py` and `apps/orders/admin.py`, API reference updates in `docs/API_ENDPOINTS.md`, and 19 new automated tests across `apps/codes/tests.py` and `apps/orders/tests.py`.
