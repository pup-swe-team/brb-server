# Changelog — Updating

Running record of what changed in `brb-server`, newest first. For the reasoning
behind a change, see [`DECISIONS.md`](DECISIONS.md). For scope and ticket
checkboxes, see [`BRB_BACKEND_SPRINTS.md`](BRB_BACKEND_SPRINTS.md).

Related documents:

| Document | Purpose |
|---|---|
| `CONTRIBUTING.md` | Team guide. Authoritative for conventions and quality gates |
| `README.md` | How a teammate gets the project running |
| `docs/BRB_BACKEND_SPRINTS.md` | What to build and when |
| `docs/COPUP_ERD.md` | Data shape |
| `docs/DECISIONS.md` | Decisions and their rationale |
| `docs/changelog-updating.md` | **This file** — what changed |

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
