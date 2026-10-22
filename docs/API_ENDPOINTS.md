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
| GET | `/api/v1/auth/me/` | user (full profile: name, contact, affiliation, status, bio, photo, address, municipality, province) |
| PATCH | `/api/v1/auth/me/` | user (profile fields: full_name, contact_number, bio, photo/profile_picture, street_address/address, municipality, province; multipart/json) |
| POST | `/api/v1/auth/token/refresh/` | public (refresh token required) |
| POST | `/api/v1/auth/logout/` | user |
| POST | `/api/v1/auth/password-reset/` | public (throttled 3/hour) |
| POST | `/api/v1/auth/password-reset/confirm/` | public (link from email) |
| POST | `/api/v1/auth/password-change/` | user (current password required) |
| POST | `/api/v1/auth/email-change/` | user (throttled 3/hour) |
| POST | `/api/v1/auth/email-change/confirm/` | public (link sent to the new address) |
| POST | `/api/v1/auth/deactivate/` | user (blocked by open orders/cases) |

## Cron — `/api/v1/jobs/`

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/jobs/deactivate-unverified/` | cron secret |

## Identity documents — `/api/v1/identity/`

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/identity/documents/` | user (multipart upload) |
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

> There is also a legacy alias `GET/PUT/PATCH/DELETE /api/v1/<id>` (name
> `listing-detail-legacy`) pointing at the same detail view. Use
> `/api/v1/listings/<id>/` in clients; the bare alias is scheduled for cleanup.

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
