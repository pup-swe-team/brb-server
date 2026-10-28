# BRB Server — API endpoints

Flat reference of every HTTP route the server exposes. Generated from the
URLconf on **2026-10-20** (branch `feature/sprint-2_CP-104-1001-1002-1004`,
after merging CP-301/302/304/403/1105) — if a route changes, update this file
in the same commit.

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
| POST | `/api/v1/jobs/expire-borrow-requests/` | cron secret |

Call `expire-borrow-requests/` hourly with `Authorization: Bearer <CRON_SECRET_TOKEN>`
using cron-job.org or an equivalent scheduler. The endpoint is idempotent and
returns the number and IDs of orders expired in that run. The deployment must
configure the external schedule; this repository does not provision it.

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

## Borrow requests — `/api/v1/orders/` (CP-501)

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/orders/` | authenticated, identity-verified borrower |

Send JSON `{"listing_id": 1, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}`.
Dates are inclusive, start today or later, and must fit inside one listing
availability window. A confirmed or active order, or a blocked date range,
prevents overlapping requests. The response is `201` with `id`, `listing_id`,
`borrower_id`, `start_date`, `end_date`, and `status: "requested"`; validation
failures return `400`. A successful request creates a `new_request` in-app
notification for the lender with the order ID as its reference.

The Admin-configurable `SystemConfig` key `borrowing_limit` caps each borrower's
combined Requested, Confirmed, and Active orders. Missing, non-numeric, or
non-positive values use the default limit of **3**.

## Lender responses — `/api/v1/orders/<id>/` (CP-502)

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/orders/<id>/accept/` | listing lender |
| POST | `/api/v1/orders/<id>/decline/` | listing lender |

Only `Requested` orders can be answered. Acceptance sets `Confirmed` and blocks
its inclusive dates. If another Confirmed or Active order, or a blocked date
range, now overlaps, acceptance automatically sets `Declined` instead. A decline
also sets `Declined` and releases dates linked to that order. Both responses
return the order's ID, listing ID, borrower ID, dates, and resulting status.
The borrower receives an in-app `acceptance` or `decline` notification.

The `SystemConfig` key `borrow_request_expiry_hours` controls the response
deadline from order creation; missing, invalid, or non-positive values default
to **48**. A lender response at or after the deadline marks the order `Expired`,
releases its dates, notifies the borrower, and returns `409` with the expired
order. The scheduled job performs the same transition for unanswered orders.

## Order cancellation and detail — `/api/v1/orders/<id>/` (CP-503)

| Method | Path | Auth |
|---|---|---|
| GET | `/api/v1/orders/<id>/` | order borrower or listing lender |
| POST | `/api/v1/orders/<id>/cancel/` | order borrower or listing lender |

Cancel with JSON `{"reason": "..."}`. The reason must contain non-whitespace
text. Only `Requested` or `Confirmed` orders can be cancelled; later states
return `409`. Cancellation sets `Cancelled`, stores the trimmed reason, releases
blocked dates linked to that order, and creates a `cancellation` in-app
notification for the other party. The response and party-only detail include
the order ID, listing and party IDs, dates, status, `cancel_reason`, and
timestamps. Existing orders have an empty cancellation reason.

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

Orders/borrowing, chat, reviews (write), codes, reports, notifications have
**no endpoints yet** — their tables exist but are empty. Do not point a client
at paths under these names until the owning tickets land.
