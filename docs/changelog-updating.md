# Changelog — Updating

Running record of what changed in `brb-server`, newest first. For the reasoning
behind a change, see [`DECISIONS.md`](DECISIONS.md). For scope and ticket
checkboxes, see [`BRB_BACKEND_SPRINTS.md`](BRB_BACKEND_SPRINTS.md).


## 2026-10-20 — Merge: listing search, lender profiles, availability calendar, pickup locations (CP-301, CP-302, CP-304, CP-403, CP-1105)

Branch: `feature/sprint-2_CP-104-1001-1002-1004` (merged `feature/sprint-2_cp301-302-304-403-1105-search-profiles-calendar-locations`).

### Changed

- `/api/v1/listings/` is now a single collection view: GET searches (CP-301,
  filters/sort as validated by `ListingSearchQuerySerializer`), POST publishes a
  listing (CP-401, requires identity-verified active lender). The standalone
  search view route and the singular `pickup-location/` routes from CP-401 were
  retired; both sides reverse() to the merged view.
- Pickup locations follow CP-1105: plural `pickup-locations/` routes,
  soft-delete via `deleted_at`, read for any authenticated user, writes for
  staff only, `description` field. The hard-delete admin-only endpoints and
  the ProtectedError-400 guard are gone with them.
- `ListingDetail` responses now embed `blocked_dates` (CP-403) alongside
  reviews, and the lender search/profile endpoints live under
  `/api/v1/lenders/` (CP-302/CP-304).
- CP-301/302/304/403/1105 tests were ported from the single
  `apps/listings/tests.py` into modules under `apps/listings/tests/`, with the
  pickup tests rewritten against the CP-1105 endpoints.

### Added (admin activation, same day)

- `/admin/` now covers the whole listings domain: `ListingCategory`,
  `ListingStatus` (read-only lookup — names are literal constants in the
  services), `ListingPhoto`, `AvailabilityWindow` joined the `Listing`,
  `PickupLocation` (with a soft-delete bulk action mirroring DELETE
  `/api/v1/pickup-locations/<id>/`) and `BlockedDateRange` registrations, and
  `users.User` itself is registered (password hash excluded from the form;
  statuses searchable/filterable for incident support).
- `docs/COPUP_ERD.md` gained the missing `BLOCKED_DATE_RANGES` table (CP-403)
  in the listings domain.
- New smoke tests: `/admin/` changelists render for every listings model plus
  `User`, the pickup soft-delete action works, and `/portal/` (verification
  admin, CP-106) renders for staff and bounces everyone else.

## 2026-10-21 — Portal: pickup-location management

Branch: `merging/sprint-2`.

### Added

- Added pickup-location management to `/portal/`. The previously-disabled
  sidebar nav item is now live. Active locations list with an inline add form
  and per-row Edit / Archive; Archived section lists soft-deleted rows with
  Restore.
- `PickupLocationPortalForm` restates the existing pickup-location rules
  (trimmed, non-blank name up to 150 chars, optional description) with the same
  `"Location name cannot be blank."` wording, so the portal and the API agree.
- Portal-only **Restore** action for soft-deleted locations: `deleted_at` is
  cleared, and the row returns to the listing-creation dropdown.
- Routes: `portal-pickup-locations`, `portal-pickup-location-edit`,
  `portal-pickup-location-delete`, `portal-pickup-location-restore` (delete and
  restore are POST-only). All staff-gated via `staff_login_required` (D-03).
- 11 tests in `tests_portal.py`: staff gating, active/archived split, trimmed
  create feeding the API dropdown, blank-name rejection, edit (and 404 for
  archived), soft-delete, restore, and GET rejection on the POST-only routes.

### Changed

- Portal page scope is now coordinated with the API work: this page mirrors the
  existing pickup-location capability, and the remaining sidebar items activate
  only once their backend counterparts exist. Tracked in the local-only
  `BRB_BACKEND_SPRINTS.md`.

## 2026-10-20 — Sprint 2: Search, Profiles, Calendar, and Locations (CP-301, CP-302, CP-304, CP-403, CP-1105)

Branch: `feature/sprint-2_cp301-302-304-403-1105-search-profiles-calendar-locations`.

### Added

**CP-1105 — Fixed pickup locations (Admin CRUD)**
- `apps/listings/permissions.py`: `IsAdminOrReadOnly` permission granting write permissions exclusively to staff administrators while permitting read access to authenticated borrowers and lenders.
- `apps/listings/serializers.py`: `PickupLocationSerializer` with unique name validation and soft-deletion protection.
- `apps/listings/views.py`: `PickupLocationListCreateView` (`GET`, `POST` `/api/v1/pickup-locations/`) and `PickupLocationDetailView` (`GET`, `PUT`, `PATCH`, `DELETE` `/api/v1/pickup-locations/<pk>/`). Soft-delete sets `deleted_at`.
- Active pickup locations feed into the lender's listing-creation location dropdown set.

**CP-403 — Availability calendar date blocking & release**
- `apps/listings/models.py`: `BlockedDateRange` model with foreign keys to `Listing` and optional `Order`, plus `reason` (e.g. `order_confirmed`, `maintenance`). Includes database check constraint `start_date <= end_date`.
- `apps/listings/migrations/0003_blockeddaterange.py`: Schema migration for `BlockedDateRange`.
- `apps/listings/services.py`:
  - `block_dates_for_order(order)`: atomically blocks date range upon order confirmation.
  - `release_dates_for_order(order)`: atomically releases blocked dates upon cancellation or completion.
  - `is_listing_available_for_range(listing, start_date, end_date)`: checks for overlapping blocked ranges and ensures requested dates fall within listing availability windows.
- Registered `BlockedDateRange` in `apps/listings/admin.py`.

**CP-301 — Search listings by keyword & filters**
- `apps/listings/selectors.py`: `search_listings(...)` filtering by keyword (`title`, `description`), category ID, condition, pickup location ID, price range (`min_price`, `max_price`), free-only flag (`is_free=True` or `rate=0`), and date range availability.
- Multi-field sorting: `price_asc`, `price_desc`, `newest`, `rating`.
- Robust exclusion rules: excludes soft-deleted listings (`deleted_at`), inactive listings (`is_active=False`), admin-removed listings (`status='removed'`), and listings owned by unverified, inactive, suspended, or revoked lenders.
- `apps/listings/serializers.py`: `ListingSearchQuerySerializer` (query param validation) and `ListingSearchResultSerializer`.
- `apps/listings/views.py`: `ListingSearchView` (`GET /api/v1/listings/`).

**CP-302 — Search for verified lenders**
- `apps/users/selectors.py`: `search_lenders(query=...)` searching verified lenders by full name.
- Annotates `active_listing_count` dynamically based on non-deleted, active, non-removed listings.
- Robust exclusions: excludes suspended, revoked, inactive, or unverified lenders.
- `apps/users/serializers.py`: `LenderSearchResultSerializer`.
- `apps/users/views.py`: `LenderSearchView` (`GET /api/v1/lenders/`).
- Routes mapped in `apps/users/lender_urls.py` and `brb_server/urls.py`.

**CP-304 — Public lender profile endpoint**
- `apps/users/selectors.py`: `get_lender_profile(lender_id)` aggregating lender info, active listings, and rating statistics (`average_rating`, `review_count`).
- Review calculation joins through `order__listing__lender=lender` and excludes self-reviews, adhering to D-19 (reviewee is derived).
- Information disclosure protection (Rule 9): queries for non-existent, unverified, inactive, suspended, or revoked lenders return `404 Not Found` rather than leaking status details.
- `apps/users/serializers.py`: `LenderProfileSerializer` exposing public fields safely (no sensitive emails, phones, or document data).
- `apps/users/views.py`: `LenderProfileView` (`GET /api/v1/lenders/<pk>/`).

### Tests

41 new automated tests across `apps/listings/tests.py` and `apps/users/tests.py`. Total test suite: **198 tests, all passing** with 0 warnings or errors.
- `PickupLocationTests` (10 tests)
- `AvailabilityCalendarTests` (8 tests)
- `ListingSearchTests` (11 tests)
- `LenderSearchTests` (6 tests)
- `LenderProfileTests` (6 tests)
## 2026-10-19 — Listing photos and media serving fixes (D-26)

Branch: `feature/sprint-2_CP-104-1001-1002-1004`.

### Fixed

- **Listing photos now load in production** — added the missing `media/<path>`
  route (`django.views.static.serve` over `MEDIA_ROOT`; Render has no nginx
  and `DEBUG=False`, so nothing served uploads before) and changed `MEDIA_URL`
  to the absolute `/media/`, which also stops photo URLs from resolving to
  `.../api/v1/listings/media/...`.
- **Photo uploads validate by content, not by client claims** — files whose
  first bytes are not PNG/JPEG/WebP are rejected regardless of the declared
  `content_type`, and non-file `photos` values (e.g. URL strings in a JSON
  body) now return a 400 instead of creating a phantom `ListingPhoto` row.
- **PATCH on a listing returns the photos you just sent** — the response was
  built from the stale prefetch cache after `update_listing()` replaced
  photos and availability windows.
- **Deleting an in-use pickup location returns 400** instead of a 500
  (`ProtectedError`); unreferenced locations still delete with 204.
- Removed the no-op `paginate_by = 10` on the pickup-location list (DRF
  reads `pagination_class`; the endpoint has always used the global
  `PAGE_SIZE` of 20).

## 2026-10-19 — Sprint 2 account lifecycle endpoints (D-25)

Branch: `feature/sprint-2_CP-104-1001-1002-1004`.

### Added

- **CP-104 password recovery** — `POST /api/v1/auth/password-reset/` mails a
  single-use link (generic anti-enumeration response, throttled 3/hour);
  `POST /api/v1/auth/password-reset/confirm/` sets the new password, clears
  any lockout and blacklists outstanding sessions. Link lifetime defaults to
  60 minutes, Admin-configurable via
  `system_configs.password_reset_expiry_minutes`.
- **CP-1001 profile edit** — `PATCH /api/v1/auth/me/` persists full name,
  contact number, bio, street address, municipality and province.
- **CP-1001 password change** — `POST /api/v1/auth/password-change/` proves
  the current password (401 `invalid_credentials` on mismatch), re-hashes the
  new one and signs out every other session.
- **CP-1002 email change** — `POST /api/v1/auth/email-change/` mails a
  confirmation link to the new address (throttled 3/hour);
  `POST /api/v1/auth/email-change/confirm/` swaps the addresses. The old
  email stays the account of record until the link is confirmed; the new
  address must satisfy the CP-101 PUP-domain and affiliation rules.
- **CP-1004 deactivation** — `POST /api/v1/auth/deactivate/` closes the
  account (status `deactivated`, `is_active` False, sessions blacklisted),
  and refuses with a 400 naming the counts while open orders (borrowed or
  lent) or open/escalated UnreturnedCases exist.

### Changed

- `apps/users/tokens.py` — the send-stamp hash logic is now driven by a
  per-subclass `sent_at_field`, with `PasswordResetTokenGenerator` and
  `EmailChangeTokenGenerator` added alongside the CP-102 generator (each
  with its own salt, so tokens cannot cross endpoints). Behaviour of
  verification tokens is unchanged.
- `apps/users/serializers.py` — PUP-domain lookups extracted into
  `pup_webmail_domains()`; registration behaviour is unchanged.
- `users.0007` — adds `password_reset_sent_at`, `pending_email`,
  `email_change_sent_at` (all nullable; backward-compatible).

### Tests

- `apps/users/tests.py` — 53 new tests: `PasswordResetTests` (15),
  `ProfileUpdateTests` (8), `PasswordChangeTests` (7),
  `EmailChangeTests` (13), `AccountDeactivationTests` (10). Suite total
  314, all green.

## 2026-10-19 — Verification bug-fix round (D-24)

Branch: `checking/sprint-1`.

### Fixed

- **A resend retires the previous verification link (F-BUG-0002-001):** new
  `User.email_verification_sent_at` column (`users.0006`) is stamped per
  dispatch in `send_email_verification` and folded into the token HMAC
  (`apps/users/tokens.py`), so the link already in the inbox stops verifying
  once a new email is mailed. A failed send persists nothing, so a mail
  outage leaves the previously mailed link working.
- **Portal review and download no longer 500 on legacy submissions:**
  `decrypt_document_data` (`apps/users/encryption.py`) returns bytes that are
  not Fernet tokens unchanged — rows written before the CP-107 write path are
  plaintext, and migration 0005 only rewrote rows that existed when it first
  ran. Token-shaped bytes still decrypt, or raise, exactly as before.

### Tests

- `apps/users/tests.py` — three new `ResendVerificationTests` (superseded link
  refused end-to-end by POST `/verify-email/`, freshly mailed link validates
  across the DB round-trip, failed send keeps the old link valid);
  `IdentityDocumentEncryptionTests` covers the legacy-plaintext read;
  `test_submission_is_stored_with_a_pending_status` now decrypts before
  comparing, since CP-107 encrypts at write time.
- The third QA bug (profile "Verified" tag stale after admin approval) is a
  `brb-client` fix — any-approved status scan, refresh-and-retry interceptor,
  foreground refetch — recorded in `DECISIONS.md` D-24.

Related documents:

| Document | Purpose |
|---|---|
| `CONTRIBUTING.md` | Team guide. Authoritative for conventions and quality gates |
| `README.md` | How a teammate gets the project running |
| `docs/BRB_BACKEND_SPRINTS.md` | What to build and when |
| `docs/COPUP_ERD.md` | Data shape |
| `docs/DECISIONS.md` | Decisions and their rationale |
| `docs/changelog-updating.md` | **This file** — what changed |

## 2026-10-16 — First Render Web Service deploy (D-23)

Branch: `checking/sprint-1` (local, uncommitted).

### Added

- `render.yaml` — Render Blueprint for the `brb-server` Web Service: Python
  3.12, build = `uv sync --frozen --no-dev` + full `migrate`, start =
  `gunicorn brb_server.wsgi:application --bind 0.0.0.0:$PORT`, health check
  at `/healthz/`, env contract (`DEBUG=False`, generated `SECRET_KEY`,
  `ALLOWED_HOSTS`, `DATABASE_URL` and the encryption key filled in the
  dashboard).
- `brb_server/urls.py` + `apps/core/views.py` — `GET /healthz/` liveness
  endpoint (no auth, no DB round-trip) for Render health checks.
- `pyproject.toml` / `uv.lock` — `gunicorn` runtime dependency.

### Changed

- `brb_server/settings.py` — added `SECURE_PROXY_SSL_HEADER` (Render
  terminates TLS) and env-driven `CSRF_TRUSTED_ORIGINS` (Admin/portal POSTs
  are rejected behind the proxy without it once `DEBUG=False`).

Related documents:

| Document | Purpose |
|---|---|
| `CONTRIBUTING.md` | Team guide. Authoritative for conventions and quality gates |
| `README.md` | How a teammate gets the project running |
| `docs/BRB_BACKEND_SPRINTS.md` | What to build and when |
| `docs/COPUP_ERD.md` | Data shape |
| `docs/DECISIONS.md` | Decisions and their rationale |
| `docs/changelog-updating.md` | **This file** — what changed |

## 2026-10-13 — Admin accounts restricted to `@pup.edu.ph`

Branch: `checking/sprint-1` (local, uncommitted).

### Changed

- `apps/users/models.py` — `UserManager.create_superuser` now rejects emails
  outside `ALLOWED_FACULTY_EMAIL_DOMAIN` (`@pup.edu.ph`) with a `ValueError`;
  `User.clean()` enforces the same rule for any `is_staff` account, so Django
  Admin "Add/Change user" forms refuse `@gmail.com` / `@iskolarngbayan` for
  staff. Registration was already enforced (serializer); this closes the
  `createsuperuser` and Django Admin gaps.
- `apps/users/models.py` — dropped `affiliation` from `REQUIRED_FIELDS` so
  `createsuperuser` no longer prompts for it; superusers keep the D-20 default
  `affiliation=Faculty`. This is a prompt-only change (no schema/ERD impact).

### Tests

- `apps/users/tests.py` — new `AdminAccountEmailDomainTests` (5 tests).

Related documents:

| Document | Purpose |
|---|---|
| `CONTRIBUTING.md` | Team guide. Authoritative for conventions and quality gates |
| `README.md` | How a teammate gets the project running |
| `docs/BRB_BACKEND_SPRINTS.md` | What to build and when |
| `docs/COPUP_ERD.md` | Data shape |
| `docs/DECISIONS.md` | Decisions and their rationale |
| `docs/changelog-updating.md` | **This file** — what changed |

## 2026-10-13 — Admin portal verification pages (BE-BUG-0006)

Branch: `checking/sprint-1` (local, uncommitted). Mounted at `/portal/`.

### Added

- `apps/users/portal.py` — server-rendered admin pages (D-22): `AdminPortalLoginView`
  (rejects non-staff sign-ins), `dashboard`, `verification_queue` (Pending /
  Approved / Rejected tabs + pagination), `verification_review` (document
  preview, submitted details, server-side checks), `verification_review_submit`
  (approve/reject). Authority is `is_staff` via `staff_login_required`; a
  non-staff member hitting any page is logged out. Reuses
  `review_identity_document` so notifications, emails and audit entries stay one
  code path.
- `apps/users/portal_urls.py` + `brb_server/urls.py` — `/portal/` routes.
- Templates in `apps/users/templates/admin_portal/` matching Figma screens 76
  (sign-in), 77 (dashboard), 82 (queue), 83 (review), 84 (reject overlay).
  Static assets: `apps/users/static/admin_portal/portal.css`, `portal.js`.
- `apps/users/templatetags/portal_extras.py` — `|initials` and `|doc_type_label`
  template filters.
- `django.contrib.humanize` in `INSTALLED_APPS` (dashboard `|intcomma`).
- `apps/users/encryption.py` — `detect_document_content_type` (PNG/JPEG/PDF
  magic-number sniffing); `IdentityDocumentDownloadView` now uses it too.
- `apps/users/tests_portal.py` — 16 tests: staff gating, login rejects
  non-staff, queue tabs/pagination, review audit `view` entry, approve/reject
  flows (notification + email), reject-requires-reason, no re-review.

### Notes

- The remaining admin screens (users, reports, content moderation, system
  settings, audit log, …) are shown disabled in the sidebar as "planned for a
  later sprint". Whitenoise/static serving for the deployed Render site is still
  an open offer; Django Admin (and these pages) render unstyled when
  `DEBUG=False`.

## 2026-10-12 — `GET /api/v1/auth/me/` profile endpoint (BE-BUG-0002)

Branch: `checking/sprint-1` (local, uncommitted).

### Added

- `MeView` (`apps/users/views.py`) + `auth-me` route (`apps/users/urls.py`):
  `GET /api/v1/auth/me/` returns the authenticated caller's own row as
  `UserResponseSerializer` (real `full_name`, `email`, `affiliation`, ...).
  Requires authentication (project-wide `IsAuthenticated`); always reads
  `request.user`, so it cannot return another account's details.
- `MeViewTests` (`apps/users/tests.py`, 4 tests): returns the registered
  affiliation verbatim, is scoped to the caller's own row only, and rejects
  anonymous and bogus-token requests with `401`.

### Why

The client Profile page rendered a hardcoded placeholder badge (always
"Student") and a hardcoded name, so a Staff/Faculty account looked like a
Student (BE-BUG-0002). The client had no way to fetch its own account after
login — only tokens were stored. The paired `brb-client` change makes
`ProfileScreen` call `/auth/me/` and render the real details.

---

## 2026-10-12 — Auth error responses expose `code` (D-21)

Branch: `checking/sprint-1` (local, uncommitted).

### Added

- `brb_server/exceptions.py`: project DRF exception handler
  (`api_exception_handler`) that keeps DRF's default behaviour and appends
  `response.data["code"] = exc.get_codes()` for every `APIException` whose
  `detail` is a plain string.
- `EXCEPTION_HANDLER` set in `REST_FRAMEWORK` (`brb_server/settings.py`).
- Login 401 tests now assert the `code` (`invalid_credentials`, `unverified_email`,
  `suspended`, `banned`).

### Why

The client branches on a machine-readable `code` — `LoginScreen` routes
`unverified_email` back to the verify prompt and special-cases
`invalid_credentials` — and `LoginSerializer` documents that code as its
contract, but DRF's default handler never serialized it. `getApiErrorCode()`
always returned `undefined`, so an unverified-email login showed a red error box
instead of the verify-email redirect (FE-BUG-0002). See `DECISIONS.md` D-21.
The paired `brb-client` fix (web token storage) makes login stop throwing on
Expo Web, where `expo-secure-store` has no native module.

---

## 2026-10-12 — Resend-verification endpoint (BE-BUG-0001)

Branch: `checking/sprint-1` (local, uncommitted).

### Added

- `POST /api/v1/auth/resend-verification/` — re-dispatches the CP-102
  confirmation link. Accepts an email address; only when the address belongs to
  an account that is unverified and in `pending_review` is a fresh link minted
  and mailed. Returns the same generic 200 for every outcome so it cannot
  enumerate registered addresses (consistent with the indistinguishable
  failures of the verification endpoint itself).
- `apps/users/services.py`: `resend_email_verification()`.
- `apps/users/serializers.py`: `ResendVerificationSerializer`.
- DRF `ScopedRateThrottle` on the new view with `resend-verification` limited to
  `3/hour` via `DEFAULT_THROTTLE_RATES` in `brb_server/settings.py`, bounding
  outbound mail volume from a public endpoint.
- `apps/users/tests.py`: `ResendVerificationTests` (7 tests).

### Why

The frontend "Resend Email" button previously navigated straight to the
"Email Verified" success screen and sent nothing (verify the client commit
alongside this). The backend surfaced no such endpoint at all, so the button
could not have worked as labelled. Client-side fix follows in `brb-client`.

---

## 2026-10-11 — CORS headers for the browser client (D-20)

Branch: `checking/sprint-1`.

### Added

- `django-cors-headers` dependency (`pyproject.toml`, `uv.lock`).
- `corsheaders` in `INSTALLED_APPS` and `CorsMiddleware` in `MIDDLEWARE`
  (`brb_server/settings.py`), placed above `CommonMiddleware`.
- `CORS_ALLOW_ALL_ORIGINS = DEBUG` and an env-driven `CORS_ALLOWED_ORIGINS`
  setting for production.
- `CORS_ALLOWED_ORIGINS` documented in `.env.example`.

### Why

Expo Web runs in a browser and enforces the same-origin policy; the native app
does not. The login preflight (`OPTIONS /api/v1/auth/login/`) returned 200 but
carried no `Access-Control-Allow-Origin`, so the browser blocked the actual
`POST` and login never reached the view. See `DECISIONS.md` D-20.

---

## 2026-10-09 — Review reviewee derived from order (D-19)

Branch: `test/sprint-1_for-merging`.

### Changed

- `apps/reviews/models.py`: removed the `Review.reviewee` FK. The reviewee is now
  a model property derived from the order's counterparty (borrower ↔ lender),
  with a `clean()` guard against self-review.
- `apps/reviews/migrations/0003_review_reviewee.py`: **deleted before merge** —
  never shipped; the tentative `reviewee` add and its check constraint never
  reach a database. `reviews` history is `0001` → `0002` only.
- `apps/users/migrations/0002_alter_user_affiliation.py`: **deleted before
  merge** — the `Admin`-free affiliation enum is folded directly into
  `users/0001_initial.py` (per PR review: fix the initial migration, don't ship
  fix migrations; the shared database is empty and re-migrated from scratch).
- `docs/COPUP_ERD.md`, `docs/DECISIONS.md`: ERD/diagram notes updated — do not
  add `reviewee_id` to draw.io.

### Why

PR review flagged `reviewee_id` as redundant: the reviewee is always the order
party who did not write the review. Removing an unused, un-ratified denormalized
column is cheapest while the `reviews` table is still empty. The reviewer also
directed that fixes live in the initial migration rather than new migration
files since the shared database is recreated from scratch.

---

## 2026-10-06 — Protect and log access to identity documents (CP-107)

Branch: `feature/sprint-1_cp107-identity-document-protection`.

### Added

- `cryptography` dependency for Fernet symmetric authenticated encryption.
- `IDENTITY_DOCUMENT_ENCRYPTION_KEY` setting in `brb_server/settings.py` (documented in `.env.example` and `README.md`).
- `apps/users/encryption.py`: `encrypt_document_data()`, `decrypt_document_data()`, and `get_fernet()` with fail-closed behavior in production.
- `apps/users/migrations/0005_encrypt_existing_documents.py`: data migration encrypting existing identity documents at rest.
- `apps/audit/models.py`: Added `action` and `ip_address` fields to `AdminAccessLog`.
- `apps/audit/migrations/0003_alter_adminaccesslog_options_adminaccesslog_action_and_more.py`: schema migration for audit fields.
- `apps/audit/services.py`: `log_admin_document_access()` and `get_client_ip()` helpers for FR14 audit compliance.
- `apps/audit/admin.py`: Read-only `AdminAccessLogAdmin` enforcing immutability.
- `GET /api/v1/identity/documents/<int:pk>/download/`: Administrator-only secure download endpoint that decrypts document bytes, detects MIME type, and logs access with IP (supports both JWT and Session auth).
- `GET /api/v1/identity/documents/<int:pk>/owner-info/`: Administrator-mediated contact release endpoint that releases only owner name and contact details, never documents or ID numbers.
- `apps/users/admin.py`: Removed raw `document_data` display; added `download_link` and audit logging on `change_view()`.
- `apps/users/tests.py`: 25 new tests across 5 test classes (`IdentityDocumentEncryptionTests`, `IdentityDocumentSubmissionEncryptionTests`, `IdentityDocumentDownloadTests`, `IdentityDocumentOwnerInfoTests`, `AdminAccessLogTests`).

---

## 2026-10-06 — Admin review of identity verification (CP-106)

Branch: `feature/sprint-1_cp106-admin-identity-review`.

### Added

- `POST /api/v1/identity/documents/<int:pk>/review/` — administrator endpoint to approve or reject submitted identity documents.
- `apps/users/serializers.py`: `IdentityDocumentReviewSerializer` (enforces mandatory rejection reason on reject, and checks pending document status). Added `rejection_reason` to `IdentityDocumentResponseSerializer`.
- `apps/users/services.py`: `review_identity_document` and `send_identity_review_email` (atomic decision persistence with reviewer audit info, in-app notification dispatch, and fail-safe email notifications).
- `apps/notifications/constants.py`: `NOTIFICATION_TYPE_VERIFICATION_RESULT` and default lookup list.
- `apps/notifications/migrations/0003_seed_notification_types.py`: data migration seeding standard `NotificationType` lookup rows.
- `apps/users/admin.py`: `approve_selected_documents` action and review audit fields in `IdentityDocumentAdmin`.
- `apps/users/tests.py`: `IdentityDocumentReviewTests` (12 tests covering auth, approval, rejection, notifications, resubmission, permission gating, and error resilience).

---

## 2026-10-05 — Sprint 1 onboarding: CP-102, CP-103, CP-105

Branch: `test/aaron-scratch` (uncommitted at time of writing).
CP-104 is **not** included — the sprint board schedules it for Sprint 2.

### Added

**CP-102 — email verification**
- `apps/core/constants.py` — configurable keys for lockout and expiry windows
- `apps/core/selectors.py` — `SystemConfig` readers with safe fallbacks
- `apps/core/cron.py` — `CronSecretMixin` (constant-time compare, accepts bare or
  `Bearer` token, fails closed with `503` when the secret is unset)
- `apps/core/views.py` / `apps/core/urls.py` — `POST /api/v1/jobs/deactivate-unverified/`
- `apps/users/tokens.py` — `EmailVerificationTokenGenerator`, a
  `PasswordResetTokenGenerator` subclass whose expiry is an instance attribute
  rather than the global `PASSWORD_RESET_TIMEOUT` (D-08)
- `POST /api/v1/auth/verify-email/` — idempotent verification

**CP-103 — login, session lifecycle**
- `User.failed_login_attempts`, `User.locked_until`
- `LoginSerializer`, `RefreshSerializer`, `LogoutSerializer`
- `POST /api/v1/auth/login/`, `/token/refresh/`, `/logout/`
- Login lockout after 5 consecutive failures for 15 minutes, both Admin-configurable
- Refresh-token rotation and blacklisting on logout

**CP-105 — identity document submission**
- `IdentityDocument.name_on_document`, `has_profile_mismatch`, `consent_given`,
  `consented_at`
- `apps/users/permissions.py` — `IsIdentityVerified`
- `IdentityDocumentSubmissionSerializer`, `IdentityDocumentResponseSerializer`
- `POST /api/v1/identity/documents/`, `GET /api/v1/identity/documents/list/`
- `apps/users/identity_urls.py`
- Name-mismatch flagging by normalised comparison against `users.full_name` (D-10)

**Admin surface — new, and needed to make CP-103 honest**
- `apps/core/admin.py` — registered `SystemConfig`
- `apps/users/admin.py` — registered `IdentityDocument`, `IdentityDocumentType`,
  `IdentityDocumentStatus`
- `README.md` — teammate setup and run instructions

### Changed

| Area | Change |
|---|---|
| `brb_server/settings.py` | Added multipart/form parsers (required for file upload) |
| `brb_server/settings.py` | Added `CRON_SECRET_TOKEN`, `EMAIL_VERIFICATION_REDIRECT_URL` |
| `brb_server/settings.py` | **Cloudinary removed** from `INSTALLED_APPS`; `STORAGES` reduced to one unconditional block (D-13) |
| `brb_server/urls.py` | Mounted `/api/v1/jobs/` and `/api/v1/identity/` |
| `pyproject.toml` | **Dropped `cloudinary` and `django-cloudinary-storage`** |
| `uv.lock` | 8 packages removed as a consequence of the above |
| `apps/users/models.py` | `IdentityDocument.file_reference` (FileField) → `IdentityDocument.document_data` (`BinaryField` / Postgres `bytea`) |
| `.env.example` | Removed the Cloudinary block and the inert `DATABASE_PASSWORD` |
| `pyproject.toml` | Added documented `per-file-ignores` for `RUF012` on `models.py` / `serializers.py` |
| `docs/COPUP_ERD.md` | Documented the new `users` and `identity_documents` columns |

### Migrations

| Migration | Purpose |
|---|---|
| `users/0003_identitydocument_consent_given_and_more` | CP-102/103 user columns, CP-105 document columns, `id_number` index, consent check constraint, and the `file_reference` → `document_data` swap |
| `users/0004_seed_identity_document_lookups` | Data migration seeding `IdentityDocumentType` (`pup_id`, `government_id`) and `IdentityDocumentStatus` (`pending`, `approved`, `rejected`) |

`0003` folds the storage swap into the same migration rather than shipping a
separate add-then-drop pair, because the branch was uncommitted and no shared
database had ever applied it. `makemigrations --check` reports no drift.

> **Note:** `copup_db` on Render has **not** been migrated. It was empty when
> connected and remains empty. Whoever runs `migrate` first populates it for
> everyone.

### Fixed

- **DRF does not inject `request` into serializer context.** The CP-105
  submission serializer needed the current user to enforce one-ID-per-account, but
  `Serializer(data=request.data)` has no `request` in `self.context`. Constructed
  with an explicit `context={"request": request}`.
- **Auth failures returned `400` with `detail` as a *list*.** Now
  `AuthenticationFailed` → `401` with a scalar message and distinct error codes
  (D-12).
- **`STUDENT_PAYLOAD` collided with the default `make_user()` email**, so
  registration tests were silently asserting against a `400 duplicate email`.
- **Expiry test used `max_age_seconds=0`**, which the generator accepts within the
  same second. Now `-1`.
- **5MB upload test failed on Windows** with `WinError 32` — Django spools
  anything over 2.5MB to an on-disk temp file that Windows then refuses to
  re-read. The 5MB boundary is now asserted at the field level.
- **`.env.example` shipped a 28-byte `JWT_SECRET`**, below the HS256 minimum of 32,
  so every token emitted `InsecureKeyLengthWarning`.
- **`DATABASE_PASSWORD` was a dead setting.** It was present in `.env` and
  `.env.example` but Django never read it — `dj_database_url.config()` takes the
  password from `DATABASE_URL`. Proved by connecting with a deliberately wrong
  value: authentication still succeeded. A teammate "fixing" that line would have
  changed nothing and been confused. Removed from both files.
- **`apps/*/admin.py` were stubs.** CP-103's acceptance criterion is "lock account
  for 15 min after 5 consecutive failed attempts **(Admin-configurable)**", but no
  model was registered in the admin, so `SystemConfig` rows were editable only
  from `manage.py shell`. The criterion was satisfiable in letter and not in
  intent. Both admin modules are now implemented.

### Added to infrastructure

- `DATABASE_URL` now points at **Render-managed PostgreSQL** (Singapore,
  PostgreSQL 18.6). `ssl_require` was already keyed off the `postgres` scheme, so
  Render's SSL requirement needed no change.

### Tests

`117 tests, all passing`, verified against both SQLite and real PostgreSQL.

| Ticket | Test class | Count |
|---|---|---|
| CP-101 | `UserRegistrationTests` | 15 |
| CP-102 | `EmailVerificationTests` | 12 |
| CP-102 | `EmailVerificationTokenGeneratorTests` | 6 |
| CP-102 | `DeactivateUnverifiedAccountsViewTests` (apps.core) | 13 |
| CP-102 | `SystemConfigAdminTests` (apps.core) | 2 |
| CP-103 | `LoginTests` | 11 |
| CP-103 | `LoginLockoutTests` | 10 |
| CP-103 | `TokenLifecycleTests` | 11 |
| CP-105 | `IdentityDocumentSubmissionTests` | 23 |
| CP-105 | `IdentityDocumentListTests` | 3 |
| CP-105 | `IdentityVerificationGateTests` | 7 |
| CP-105 | `IdentityDocumentAdminTests` | 4 |

`SystemConfigAdminTests` and `IdentityDocumentAdminTests` are counted under
CP-103/CP-105 respectively because they guard acceptance criteria those tickets
depend on: runtime-tunable configuration, and keeping document bytes off every
list view.

### Known gaps and deliberate omissions

1. **CP-105 "block listing creation and item requests until verified" is NOT
   done.** The `IsIdentityVerified` permission exists and is tested, but no listing
   or request endpoint exists yet (CP-301/CP-501). The checkbox stays unticked.
2. **CP-107's "store identity documents encrypted" is NOT done.** Render encrypts
   volumes at rest; application-level encryption (e.g. Fernet around the bytes) is
   still owed. It now applies to a blob rather than a path.
3. **CP-104 is untouched** (Sprint 2). D-08 deliberately left it room by keeping
   the verification-token lifetime off the global setting.
4. **`users.photo` still uses the ephemeral filesystem** and will be lost on
   redeploy. Cosmetic and re-uploadable, unlike an ID. Out of CP-105's scope.
5. **Database size ceiling.** ~1GB free Postgres ÷ 5MB cap ≈ 200 documents. Fine
   for a demo, wrong for production (D-13).
6. **Nine apps still have stub `tests.py` files.**
7. **Branch naming** was changed in `CONTRIBUTING.md` to
   `<category>/sprint-<n>_cp<ticket>-<desc>`. No existing branch was renamed.

### Outstanding before merge

- [ ] Create a properly named branch off `test/aaron-scratch`
- [ ] Commit and open a PR
- [ ] Team review of D-07 (sweep deletes rather than deactivates), D-13 (bytea storage) and D-14 (full migration set)

## 2026-10-05 - Documentation restructured (D-16)

`CONTRIBUTING.md` and `README.md` both documented setup, and they had drifted
into actively misleading guidance. Split by audience, no duplication:

| Document | Owns |
|---|---|
| `README.md` | Install, configure, run, test, debug |
| `CONTRIBUTING.md` | Branch naming, commits, SRS traceability, DoR/DoD, domain rules |

**`CONTRIBUTING.md`** went from 552 to ~490 lines. Prerequisites, First-Time
Setup and Troubleshooting were deleted (all now in `README.md`), sections were
renumbered 1–7, and a routing table was added at the top. Factual errors fixed:

- Removed the three `CLOUDINARY_*` rows — Cloudinary was deleted in D-13.
- Removed the `DATABASE_PASSWORD` row — the password lives inside
  `DATABASE_URL`, and the standalone variable does nothing.
- CI section now lists only the four steps that exist in `ci.yaml`. The claimed
  "PR & Commit Conventions" job never existed.
- Added §4.2: CI fires on `dev` and `main` only, so a `feature/*` PR gets no CI
  run at all.
- Clarified the Ruff version split: pre-commit pins an isolated `v0.6.9` while
  the project runs `0.16.x`.
- §5.3 rule 3 no longer claims documents are "encrypted at rest" — that is
  CP-107 and is not implemented. It now says so.
- §5.3 rule 6 now names the real `/api/v1/jobs/deactivate-unverified/`
  endpoint, plus the fail-closed `503` when `CRON_SECRET_TOKEN` is unset.
- New §5.2: migrations are never partial, with the D-14 failure mode.
- The daily workflow no longer tells everyone to branch off `dev`, which is
  currently empty of feature commits.

**`README.md`** gained a Troubleshooting entry for the D-14 partial-migration
error, the CI branch caveat, the current integration branch name, and a Further
reading table.

`AGENTS.md` and `docs/DECISIONS.md` (D-16) record the split so AI assistants do
not reintroduce duplication.

**Closed on 2026-10-05:**

- [x] Rotate the Render database password that was pasted into chat
- [x] Decide the `Alumni` affiliation question — **removed from the project** (D-15)

**AI assistants:** `AGENTS.md` at the repo root carries the standing
instructions, including the `Alumni` removal and the full-migration-only rule.
Read it before making changes.

## 2026-10-05 - Render `copup_db` populated

Render's shared PostgreSQL was previously empty; it is now migrated so the team
shares one database instead of each member running their own.

**Applied:** `contenttypes`, `auth`, `sessions`, `admin`, `users`, `core`,
`audit`, `token_blacklist` first (19 tables), then the full set after the trap in
D-14 was found. **Final state: 50 tables, 0 rows.**

| Domain | Tables |
|---|---|
| Django framework | `django_migrations`, `django_content_type`, `django_session`, `django_admin_log` |
| Auth / JWT | `auth_user`, `auth_group`, `auth_permission`, `auth_group_permissions`, `auth_user_permissions`, `users_groups`, `users_user_permissions`, `token_blacklist_outstandingtoken`, `token_blacklist_blacklistedtoken` |
| **Sprint 1 — accounts** | `users`, `user_provinces`, `user_municipalities` |
| **Sprint 1 — identity** | `identity_documents`, `identity_document_types`, `identity_document_statuses` |
| **Sprint 1 — audit / config** | `admin_access_logs`, `system_configs` |
| Sprint 2+ (empty, reserved) | listings, orders, chat, reviews, codes, reports, notifications |

**Verified against the live database, not just the test database:**

- `document_data` is `bytea NOT NULL`; a 35-byte payload round-tripped byte-exact.
- Lookup rows seeded: `government_id`, `pup_id`; `pending`, `approved`, `rejected`.
- `identity_document_consent_has_timestamp` check constraint and
  `idx_identity_doc_id_number` index both present.
- All probe and smoke rows were deleted; the database ships with zero rows.

**Trap worth knowing about (D-14):** the first pass migrated Sprint 1 only, and
CP-102's expiry sweep immediately crashed with
`ProgrammingError: relation "listings" does not exist`. Deleting a `User` makes
Django walk every reverse relation, and all seven deferred apps FK to
`AUTH_USER_MODEL`. Any partial migration of this project is therefore unsafe for
CP-102 — run the full `migrate`.

**Also corrected:** `docs/COPUP_ERD.md` drew `municipality` and `province` as
free-text strings on `USERS`. The code has always used nullable FKs to lookup
tables; the ERD now matches the database.

## 2026-10-05 - `Alumni` removed from the project (D-15)

Team decision: `Alumni` is out of scope for good. `users.affiliation` is
exactly `Student`, `Faculty`, `Staff`.

**No code change was needed** — the enum never included `Alumni`, the live
`copup_db` has zero user rows, and no migration is required. Documentation only:

- Added **`AGENTS.md`** at the repo root so AI assistants pick up the decision
  automatically. It also records the full-migration rule, the shared-database
  safety rules and the known Windows/DRF gotchas.
- `docs/DECISIONS.md`: new **D-15**; "Open questions not yet decided" is now
  empty.
- `docs/COPUP_ERD.md`: four stale references corrected, including the `USERS`
  enum comment and the draw.io sync checklist.
- `CONTRIBUTING.md`: §2.4 and §7.2 described
  `ALLOWED_STUDENT_EMAIL_DOMAIN` as the "student/alumni" domain and listed
  "Students and Alumni" as a registration category. Now student-only.

Standing instruction: do not reintroduce `Alumni` in any future sprint, and
treat any document that still mentions it as stale.
