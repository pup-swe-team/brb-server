# BRB Server — API endpoints

Flat reference of every HTTP route the server exposes. Generated from the
URLconf — if a route changes, update this file in the same commit.

- **Base URL (dev):** `http://localhost:8000` — **(Render):** the service URL
  from the `brb-server` dashboard (`https://…onrender.com`).
- JSON in / JSON out. Auth is `Authorization: Bearer <access token>`
  (SimpleJWT; 15-min access, 7-day rotating refresh).
- Endpoints marked **public** need no token. Everything else needs a valid
  token for an account that passes the listed gate.

## Auth legend

| Marker | Meaning |
|---|---|
| `public` | No token required |
| `cron secret` | No token, but must present the cron shared secret (`CronSecretMixin`) |
| `user` | Any authenticated, active account |
| `lender` | Authenticated + account active + `lender_status=active` |
| `verified` | Authenticated + identity document approved (plus lender rules where listed) |
| `owner` | Read: any `user`. Write: only the listing's lender |
| `admin` | `is_staff` (admin portal / superuser accounts) |

## Health

| Method | Path | Auth |
|---|---|---|
| GET | `/healthz/` | public |

## Auth — `/api/v1/auth/`

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/auth/register/` | public |
| POST | `/api/v1/auth/verify-email/` | public (link from email) |
| POST | `/api/v1/auth/resend-verification/` | public (throttled 3/hour) |
| POST | `/api/v1/auth/login/` | public |
| GET | `/api/v1/auth/me/` | user |
| PATCH | `/api/v1/auth/me/` | user (profile fields only — not email/password) |
| POST | `/api/v1/auth/token/refresh/` | public (refresh token required) |
| POST | `/api/v1/auth/logout/` | user |
| POST | `/api/v1/auth/password-reset/` | public (throttled 3/hour) |
| POST | `/api/v1/auth/password-reset/confirm/` | public (link from email) |
| POST | `/api/v1/auth/password-change/` | user (current password required) |
| POST | `/api/v1/auth/email-change/` | user (throttled 3/hour) |
| POST | `/api/v1/auth/email-change/confirm/` | public (link sent to the new address) |
| POST | `/api/v1/auth/deactivate/` | user (body `{"password"}`; wrong password -> 401 `invalid_credentials`; blocked by open orders/cases) |

## Cron — `/api/v1/jobs/`

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/jobs/deactivate-unverified/` | cron secret |
| POST | `/api/v1/jobs/check-overdue/` | cron secret |

`POST /api/v1/jobs/check-overdue/` (CP-506, CP-504/505):
- Expires stale `active` `AuthCode` rows past their `expires_at` timestamp.
- Marks `Active` orders with `end_date < today` as `Overdue` and notifies both Borrower and Lender (`overdue_status`).
- Marks `Overdue` orders $\ge 7$ days past due (Admin-configurable via `SystemConfig` key `unreturned_escalation_days`) as `Unreturned`, auto-suspends the Borrower (`account_status="suspended"`), opens an Admin `UnreturnedCase` (`status="open"`), and notifies both parties (`unreturned_status`).

## Identity documents — `/api/v1/identity/`

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/identity/documents/` | user (multipart; PUP ID must be `20xx-xxxxx-MN-x`) |
| GET | `/api/v1/identity/documents/list/` | user |
| GET | `/api/v1/identity/documents/<id>/download/` | admin |
| POST | `/api/v1/identity/documents/<id>/review/` | admin |
| GET | `/api/v1/identity/documents/<id>/owner-info/` | admin |

## Listings — `/api/v1/`

| Method | Path | Auth |
|---|---|---|
| GET | `/api/v1/listings/` | user (CP-301 search: `?q=&category=&condition=&pickup_location=&min_price=&max_price=&free_only=&available_from=&available_to=&sort=`) |
| POST | `/api/v1/listings/` | verified lender (multipart; ≥1 photo, ≥1 date window) |
| GET | `/api/v1/listings/<id>/` | user (embeds lender summary, reviews, availability windows, blocked dates) |
| PUT | `/api/v1/listings/<id>/` | owner |
| PATCH | `/api/v1/listings/<id>/` | owner |
| DELETE | `/api/v1/listings/<id>/` | owner (soft delete; blocked by ongoing orders) |
| POST | `/api/v1/listings/<id>/deactivate/` | owner |
| POST | `/api/v1/listings/<id>/reactivate/` | owner |

> **Listing Creation Payload Flexibility (BE-BUG-2006 / CP-401):**
> - **Photos:** Accepts `photos`, `photo`, `photos[]`, `image`, or `images` in `request.FILES`.
> - **Categories & Pickup Locations:** Accepts integer ID, `category_id` / `pickup_location_id`, or object/stringified JSON (`{"id": ...}`).
> - **Dates & Availability:** Accepts ISO timestamp strings (e.g. `2026-10-25T00:00:00.000Z`) or `YYYY-MM-DD`. Accepts `available_from` and `available_to` top-level aliases in addition to `start_date` / `end_date` and `availability_windows`.
> - **Ownership Confirmation:** Accepts boolean or form checkbox strings (`"on"`, `"true"`, `"1"`, `"yes"`), and alias `ownership_confirmed`.
> - **Pricing:** Accepts empty string `""` or `null` for free listings (`rate_per_day`).
> - **Permissions:** Requires `IsIdentityVerified` + `IsActiveLender`. Manually seeded QA accounts in the database must have `lender_status = 'active'` AND an approved `IdentityDocument` row (`status = 'approved'`).

> There is also a legacy alias `GET/PUT/PATCH/DELETE /api/v1/<id>` (name
> `listing-detail-legacy`) pointing at the same detail view. Use
> `/api/v1/listings/<id>/` in clients; the bare alias is scheduled for cleanup.

## Handover & Return Authentication Codes — `/api/v1/orders/<order_id>/` (CP-504, CP-505)

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/orders/<order_id>/handover-code/generate/` | listing lender (order must be `confirmed`) |
| POST | `/api/v1/orders/<order_id>/handover-code/verify/` | order borrower (body: `{"code": "123456"}`) |
| POST | `/api/v1/orders/<order_id>/return-code/generate/` | order borrower (order must be `active` or `overdue`) |
| POST | `/api/v1/orders/<order_id>/return-code/verify/` | listing lender (body: `{"code": "123456", "flagged": false, "dispute_description": "..."}`; supports multipart `evidence` upload) |

- **Handover Code (`CP-504`):** Lender generates a single-use 6-digit OTP on a `Confirmed` order (superseding any previous active handover code). Borrower enters the code to set the order to `Active`, start tracking, and notify the Lender (`confirmed_handover`).
- **Return Code (`CP-505`):** Borrower generates a single-use 6-digit OTP when initiating return on an `Active` or `Overdue` order. Lender enters the code to mark the order `Returned`, release blocked calendar dates, notify the Borrower (`confirmed_return`), and automatically transition the order to `Completed` (if `flagged=false`) or `Disputed` (if `flagged=true`, opening a `Dispute` and saving any uploaded `DisputeEvidence`).
- **Shared Code Security Rules:** Codes expire after **3 hours** (`SystemConfig` key `auth_code_expiry_hours`). Incorrect, expired, or already-used codes return `400 Bad Request` and record an `AuthCodeAttempt(was_successful=False)`. After **5** consecutive failed attempts (`auth_code_lockout_threshold`), verification is locked (`429 Too Many Requests`) for **15 minutes** (`auth_code_lockout_minutes`).

## Unreturned Cases & Admin Order Overrides — `/api/v1/` (CP-506)

| Method | Path | Auth |
|---|---|---|
| GET | `/api/v1/unreturned-cases/` | admin (`?status=open\|escalated\|returned\|unresolved`) |
| GET | `/api/v1/unreturned-cases/<id>/` | admin (full dossier: identity, contact, order, chat, codes, evidence; logs `AdminAccessLog`) |
| POST | `/api/v1/unreturned-cases/<id>/escalate/` | admin (JSON or multipart `{"resolution_notes": "...", "evidence": <file>}`) |
| POST | `/api/v1/unreturned-cases/<id>/close/` | admin (JSON `{"status": "returned" \| "unresolved", "resolution_notes": "..."}`) |
| POST | `/api/v1/orders/<id>/override-status/` | admin (JSON `{"new_status": "<order_status>", "reason": "..."}`) |

## Pickup locations — `/api/v1/pickup-locations/` (CP-1105)

Unpaginated list. Soft delete: `DELETE` sets `deleted_at`; deleted rows stay
for history but vanish from the list and return 404 on detail.

| Method | Path | Auth |
|---|---|---|
| GET | `/api/v1/pickup-locations/` | user (active locations only — listing-creation dropdown) |
| POST | `/api/v1/pickup-locations/` | admin |
| GET | `/api/v1/pickup-locations/<id>/` | user (active only) |
| PUT | `/api/v1/pickup-locations/<id>/` | admin |
| PATCH | `/api/v1/pickup-locations/<id>/` | admin |
| DELETE | `/api/v1/pickup-locations/<id>/` | admin (soft delete) |

## Lenders — `/api/v1/lenders/`

| Method | Path | Auth |
|---|---|---|
| GET | `/api/v1/lenders/?q=` | user (CP-302; suspended/revoked/non-lenders excluded; omits contact info) |
| GET | `/api/v1/lenders/<id>/` | user (CP-304 public profile: bio, photo, ratings, active listings; 404 for non-lenders) |

## Media

| Method | Path | Auth |
|---|---|---|
| GET | `/media/<path>` | public (listing photos, profile images) |

## Admin portal (HTML, session login) — `/portal/`

| Method | Path |
|---|---|
| GET/POST | `/portal/login/` |
| GET | `/portal/logout/` |
| GET | `/portal/` (dashboard) |
| GET | `/portal/verification/` (queue) |
| GET | `/portal/verification/<id>/` (review page) |
| GET/POST | `/portal/verification/<id>/review/` (submit decision) |

## Not implemented yet (planned domains)

Chat, reviews (write), reports, notifications have **no endpoints yet** —
their tables exist but are empty. Do not point a client at paths under these
names until the owning tickets land.
