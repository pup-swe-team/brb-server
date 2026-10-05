# BRB Server — Decision & Change Log

**This file is not a guide.** `CONTRIBUTING.md` is the team's guide and stays
authoritative; it is edited deliberately by the team, not as a side effect of
day-to-day work. This file records the decisions and code changes that would
otherwise have gone into `CONTRIBUTING.md`, plus open questions that still need
a team answer.

- Workflow, conventions, quality gates → `CONTRIBUTING.md`
- What to build and when → `docs/BRB_BACKEND_SPRINTS.md`
- Data shape → `docs/COPUP_ERD.md`
- Decisions and their rationale → **this file**

---

## 2026-10-05 — Pre-Sprint-1 infrastructure pass

Branch: `test/aaron-scratch`. No ticket work; these are prerequisites that
Sprint 1 depends on. Scopes used per `CONTRIBUTING.md` §4.2.

### D-01 — Scheduled jobs run on cron-job.org

**Decision:** Order-status transitions (Overdue, Unreturned, code expiry,
auto-deactivation) are driven by **cron-job.org** calling a token-protected
endpoint. The previous note in `BRB_BACKEND_SPRINTS.md` saying to use
check-on-access logic instead of a scheduler is **retracted** — the team has
verified cron-job.org works and is free for this project.

**Contract:** `POST /api/v1/jobs/check-overdue/`, `Authorization` header
carrying `CRON_SECRET_TOKEN`, `401 Unauthorized` when absent or wrong. This is
the same requirement as `CONTRIBUTING.md` §7.2 rule 6 and SRS §2.4 / §5.2.

**Still open:** check-on-access recomputation is kept as a safety net for
records that slip between cron runs, but it is explicitly *not* the primary
mechanism. Endpoint itself belongs to CP-506 (Sprint 3) and is not built yet.

### D-02 — Lookup tables stay; ERD's blanket TextChoices rule is wrong

**Decision:** Where the ERD draws a field as its own table
(`order_statuses`, `listing_statuses`, `auth_code_types`,
`auth_code_statuses`, `identity_document_types`,
`identity_document_statuses`, `unreturned_cases_statuses`, `file_types`), it
stays a real Django model — this is what the code already does and it is now
the documented convention.

Inline `"enum: ..."` string fields on models the platform also seeds or
validates inline (`users.affiliation`, `users.account_status`,
`users.lender_status`, `disputes.status`) are `TextChoices` on the model.

`*_report_categories` remain real Admin-managed tables per FR14.

**Why:** the ERD previously contradicted itself — it drew `order_statuses` and
`auth_code_statuses` as tables while its own implementation note forbade
tables for enums. The code was followed and the note was corrected.

### D-03 — Administrator authority is `is_staff`, not `affiliation`

**Decision:** `Admin` is removed from `users.affiliation`. Administrator
authority is carried by Django's built-in `is_staff` (inherited from
`AbstractUser`). No `is_admin` field was added.

`affiliation` now means only "the user's relationship to PUP":
`Student`, `Faculty`, `Staff`.

**Why:**

1. **`ADMIN` in `affiliation` breaks CP-101's domain-affiliation rule.** SRS FR1
   restricts registration to `@iskolarngbayan.pup.edu.ph` (student) and
   `@pup.edu.ph` (faculty/staff), and CP-101 requires the affiliation to *match*
   the email domain. An administrator with `admin@pup.edu.ph` would need
   `affiliation=Admin`, which matches neither allowed domain — so the value is
   unusable exactly where it is needed. This is the concrete reason the earlier
   review flagged the field, and it blocks Sprint 1.
2. **No third overlapping flag.** `is_staff` and `is_superuser` already exist
   and `is_staff` already gates `/admin/`. Adding `is_admin` would leave three
   flags all meaning "administrator", which is precisely the separation
   confusion that prompted the original question. Using `is_staff` keeps one
   flag with one meaning.
3. **`createsuperuser` already sets `is_staff=True`**, which is what
   `CONTRIBUTING.md` §2.6 relies on when it tells contributors to create a
   superuser. No new setup step is introduced.

**Changes:** `AffiliationChoices.ADMIN` deleted; `create_superuser` now
defaults `affiliation` to `FACULTY`. Migration
`users/0002_alter_user_affiliation.py` includes a data step that promotes any
pre-existing `affiliation="Admin"` row to `is_staff=True` + `affiliation="Faculty"`
so no administrator silently loses access when the enum narrows.

**Verified:** a superuser created via `create_superuser` now reports
`affiliation=Faculty, is_staff=True` and passes `full_clean()`; the enum is
`['Student', 'Faculty', 'Staff']`.

**Note for whoever builds CP-106 / CP-107:** the "is this user an
Administrator?" check that `CONTRIBUTING.md` §7.2 rule 3 requires is
`request.user.is_staff`. There is deliberately no affiliation-based admin
check anywhere.

### D-04 — SimpleJWT adopted for API authentication

**Decision:** `djangorestframework-simplejwt` is the token strategy, matching
the `JWT_SECRET` variable already documented in `CONTRIBUTING.md` §2.4 and
`.env.example`. Configured in `brb_server/settings.py`:

- `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES = JWTAuthentication`
- `REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES = IsAuthenticated`
  (default-deny, because FR3 requires private identity documents and FR5
  requires per-endpoint ownership checks)
- access token 15 min, refresh token 7 days, refresh rotation **on**, with
  `rest_framework_simplejwt.token_blacklist` installed so logout can actually
  invalidate (CP-103 "end session on logout or inactivity timeout")
- page-number pagination, 20 per page
- `SIGNING_KEY` reads `JWT_SECRET`, falling back to `SECRET_KEY`

**Not built:** no auth URLs were added. Token endpoints belong to CP-103.

**Mobile team note:** SimpleJWT serialises the `user_id` claim as a JSON
**string** (`"3"`), not a number. Verified that `JWTAuthentication` resolves it
correctly, but the client should parse it as a string.

### D-05 — ERD open TODOs 2, 3 and 4 fixed

All three were confirmed missing in the schema and are now closed.

| TODO | Fix | Migration |
|---|---|---|
| 1. `Admin` in `affiliation` | removed; admin authority moved to `is_staff` (see D-03) | `users/0002_alter_user_affiliation.py` |
| 2. `reviews.reviewee_id` missing | added `Review.reviewee` FK (`related_name="received_reviews"`), plus a `review_reviewer_not_reviewee` check constraint | `reviews/0003_review_reviewee.py` |
| 3. `order_status_overrides.new_status` missing | added `OrderStatusOverride.new_status` as `CharField(max_length=50)`, matching `previous_status` | `orders/0003_orderstatusoverride_new_status.py` |
| 4. `disputes.status` unconfirmed | confirmed `open, resolved, escalated`, now enforced by `Dispute.StatusChoices` | `orders/0004_alter_dispute_status.py` |

The new-column migrations follow the nullable → data backfill → `NOT NULL`
pattern so they stay backward-compatible against a populated database, as
required by `CONTRIBUTING.md` §9 ("migrations are backward-compatible"). All
tables are currently empty, so the backfill is a no-op today but will do the
right thing if rows exist elsewhere:

- review backfill derives the reviewee from the order's other party
  (borrower ↔ lender)
- status-override backfill falls back to the order's current status
- affiliation narrowing promotes any surviving `Admin` row to `is_staff`

**TODO 5 (`user_municipalities` / `user_provinces`) remains open** — still a
team decision, nothing removed.

**`Alumni` is no longer open — it was decided on 2026-10-05 and removed from the
project. See D-15.**

---

## Merge notes

### M-01 — `feat(users)/registration` (CP-101) merged into this branch

CP-101 was developed on `origin/feat(users)/registration` and merged into
`test/aaron-scratch` rather than into `dev` directly, since a single PR will
carry the Sprint 1 prerequisite work together. The branch contains one commit
(`5eef8f5` by Kim) adding `constants.py`, `serializers.py`, `services.py`,
`urls.py`, `views.py`, tests, and the `/api/v1/auth/` route.

**Resolved a silent settings collision.** Both branches defined a
`REST_FRAMEWORK` dict in `brb_server/settings.py`. Git merged the file without
a conflict because the two blocks sat in different regions, but Python takes
the *last* assignment — so CP-101's block (renderers + parsers only) would have
silently discarded `DEFAULT_AUTHENTICATION_CLASSES` and
`DEFAULT_PERMISSION_CLASSES`. Dropping the default-deny permission classes
would have made every endpoint publicly accessible, directly contradicting FR3
(identity documents are private) and FR5 (per-endpoint ownership checks).

Verified after the merge that the effective config keeps JWTAuthentication and
IsAuthenticated, with `DEFAULT_PARSER_CLASSES` folded into the single
canonical block.

**Lesson worth keeping:** adding a second settings key of the same name to a
shared file is invisible to `git merge` and to CI, and only shows up as a
security regression at runtime. Any further branch that needs to extend
`REST_FRAMEWORK` should edit the existing block instead of adding another.

### CP-102 is not on that branch yet

`feat(users)/registration` contains **CP-101 only** — a single commit, and the
view is explicitly labelled CP-101. There is no verification email, no
verification token, no click-to-verify handler and no 7-day auto-deactivation
anywhere in the branch, which is all CP-102 scope. Sprint 1 remains
0 completed / 6 in progress.

## Fixes and issues found along the way

- **`JWT_SECRET` in `.env.example` was too short.** HS256 (the configured
  algorithm) requires a key of at least 32 bytes; the shipped placeholder was
  28 bytes, so every token signing emitted an `InsecureKeyLengthWarning`.
  Replaced with a clearly-marked placeholder plus the command to generate a
  real one. Anyone who copied the old placeholder into their `.env` needs to
  regenerate their local `JWT_SECRET`.

## Open questions not yet decided

None. The last open question — whether to add `Alumni` to `affiliation` — was
answered on 2026-10-05: **`Alumni` is removed from the project entirely (D-15).**

## Verification performed

All four CI gates from `.github/workflows/ci.yaml` pass, plus the local hooks:

| Gate | Result |
|---|---|
| `uv run ruff format --check .` | 71 files already formatted |
| `uv run ruff check .` | All checks passed |
| `uv run python manage.py makemigrations --check` | No changes detected |
| `uv run python manage.py test` | 15 tests, all passing (CP-101 suite) |
| `uv run pre-commit run --all-files` | all 7 hooks passed |

Schema and JWT wiring were additionally smoke-tested against the real
database: the `reviewee_id` column is `NOT NULL`, the
`review_reviewer_not_reviewee` check constraint is present in the DDL, and a
token issued through `RefreshToken.for_user()` validates through
`JWTAuthentication`.

**No automated tests exist yet** was true before CP-101 landed. The merged
`apps/users/tests.py` now provides 15 tests covering the CP-101 acceptance
criteria (domain rejection, domain-affiliation matching, Admin self-registration
prohibition, duplicate email, required fields, password mismatch, weak
password, contact-number format, and affiliation not gating Borrower/Lender
defaults). All 15 pass. The other nine apps still have stub `tests.py` files.

---

## 2026-10-05 — Sprint 1 onboarding pass (CP-102, CP-103, CP-105)

Branch: `test/aaron-scratch`. Covers CP-102, CP-103 and CP-105. **CP-104 is
deliberately untouched** — the sprint board schedules it for Sprint 2, and CP-102's
token work deliberately leaves it room (see D-08).

### D-06 — Unverified accounts cannot log in

**Decision:** A `pending_review` account with no `email_verified_at` is refused at
login with `401` and a message telling the user to check their inbox. Chosen over
"log in but restrict": the account has no verified contact channel, so an
unverified login is indistinguishable from the person who merely knows the
address, and every downstream feature assumes a reachable owner.

The unknown-email and wrong-password cases deliberately return a **byte-identical**
response (`Invalid email or password.`) so the endpoint cannot be used to
enumerate registered addresses. The lockout counter is only incremented for
accounts that actually exist, which means an attacker cannot lock someone else
out by guessing their email.

### D-07 — The 7-day sweep deletes rows instead of setting a flag

**Decision:** `POST /api/v1/jobs/deactivate-unverified/` **hard-deletes**
unverified accounts past the window. The ticket says "auto-deactivate", but a
deactivated flag on an account nobody can reach is a dead end: there is no
reactivation path (next bullet), so the row would exist only to block the email
address. Deleting frees the address for the re-registration the ticket requires.

Consequence worth stating plainly: **the delete cascades**, so the gate that
blocks document upload behind email verification (CP-105) is what stops a
sweep from destroying an uploaded document. That ordering is a dependency, not a
coincidence.

Window is Admin-configurable through `SystemConfig`
(`email_verification_expiry_days`, default 7). A mail outage cannot strand
anyone because the sweep is the safety net — registration still returns `201` when
the send fails, since failing the request would only invite a retry that then
collides on duplicate email.

### D-08 — Verification token lifetime is per-instance, not `PASSWORD_RESET_TIMEOUT`

**Decision:** `EmailVerificationTokenGenerator` subclasses
`PasswordResetTokenGenerator` and moves the expiry onto an instance attribute.

Django's generator hard-codes its window to the global `PASSWORD_RESET_TIMEOUT`,
which is the wrong knob: CP-102 links must outlive 7 days while CP-104's reset
links need 1 hour. One global setting cannot serve both without one ticket
silently changing the other's behaviour. The subclass reuses the parent's private
helpers rather than re-deriving the HMAC, so the two cannot drift on salt
construction, and it uses a distinct `key_salt` so a verification token can never
be replayed against Django's password-reset view.

### D-09 — The emailed link targets the app; verification is a POST

**Decision:** The email contains `brb://auth/verify-email?uid=...&token=...`
(configurable via `EMAIL_VERIFICATION_REDIRECT_URL`). Verification happens at
`POST /api/v1/auth/verify-email/`.

A confirmation link that mutates state on `GET` is unsafe by construction: link
previews, scanners and browser prefetch all issue `GET`s, so any of them would
consume the token. `POST` keeps the mutation explicit and leaves the scheme
handler in the frontend's control.

### D-10 — Identity mismatch is a declared-name comparison, not OCR

**Decision:** `has_profile_mismatch` is set by comparing the client-supplied
`name_on_document` against `User.full_name`, normalised for case, spacing and
punctuation. The document image is **not** read.

CP-105 says "flag mismatches between registration info and submitted document".
Doing that properly means OCR over a government ID, which is a large, failure-prone
dependency and a privacy commitment nobody has made yet. The flag is explicitly
*advisory*: it routes the submission to human review, it does not reject. So the
cheap signal captures the intent (most submissions are honest, and a mismatch
is what a reviewer needs to see) while leaving OCR as a later upgrade if CP-106
reviewers ask for it. Normalisation is one-way — punctuation is stripped from both
sides so "Dela Cruz" and "dela cruz." compare equal.

### D-11 — `id_number` is unique per account, enforced in the serializer

**Decision:** The database index on `id_number` is **not** unique. The rule is
"one id_number per account", which spans rows and is enforced by the serializer
using a case-insensitive lookup.

CP-106 allows resubmission after a rejection, so the same person must be able to
submit the same ID again; a unique index would make the second attempt a database
error instead of a valid workflow step. Uniqueness is also checked
case-insensitively, since IDs are transcribed by hand. One test pins this: the
same account re-submitting its own ID stays legal, a different account is refused.

### D-12 — Auth failures are `401`, not `400`

**Decision:** Login, refresh and logout failures raise
`AuthenticationFailed` (`401`). Structural problems — missing field, malformed
payload — remain `400`.

The serializer originally raised `ValidationError({"detail": ...})`, which DRF
renders as `400` **with `detail` as a list**. That shape is wrong on two counts:
`400` says "fix your request", but a bad password is a credential problem, and a
`detail` key holding a list of `ErrorDetail` is a shape no other endpoint here
returns. `AuthenticationFailed` also unifies the lockout, suspended, banned and
unverified branches behind one status with distinct error `code`s, so a client
can branch without string-matching prose.

### D-13 — Identity document bytes live in Postgres, not in a bucket or on disk

**Decision:** `identity_documents.document_data` is a `BinaryField` (Postgres
`bytea`). The document bytes are written into the row. **Cloudinary is removed**,
along with the `cloudinary` and `django-cloudinary-storage` packages, the
`CLOUDINARY_*` settings and the `USE_CLOUDINARY_STORAGE` toggle.

**Why not the local filesystem**, which was the previous fallback: Render's
filesystem is ephemeral and the free tier has no persistent disk, so every
uploaded ID would silently vanish on the next redeploy or restart. A dev-branch
that looks correct and loses real government IDs in production is worse than one
that was never finished. This was caught before any Cloudinary code was tested, so
nothing was migrated in the wrong direction.

**Why not another object store** (S3/R2/Backblaze): that is the same architecture
under a different vendor name. The team's stated goal is to keep everything on
Render, and a second service means a second account, a second bill and a second
thing to go down.

The trade-offs accepted, stated plainly:

- **Database growth.** Render's free Postgres is ~1GB and a document is capped at
  5MB, so roughly 200 documents is the ceiling before the disk is at risk. That is
  fine for a capstone demo and wrong for a real deployment; the honest fix later is
  object storage with a lifecycle policy, not a bigger database.
- **Backup size.** Every DB backup now carries the documents. That is a feature for
  recoverability and a cost for backup time.
- **CP-107's "store identity documents encrypted"** now applies to the blob rather
  than to a path. Render encrypts volumes at rest, but application-level encryption
  (e.g. Fernet around the bytes) is still owed by CP-107 and is *not* done here.
- **Ephemerality is not fixed for `users.photo`.** Profile photos still use the
  default filesystem backend and will still be lost on redeploy. They are cosmetic
  and the user can re-upload, unlike an ID.

The client API is unchanged: the request is still `multipart/form-data` with a
`document_file` part, and size/type validation still happens on the uploaded file.
Only the write target moved, so the mobile client needs no change.

The response serializer uses an explicit field list that omits `document_data`, so
the bytes cannot reach a phone even accidentally — FR3 keeps documents
Administrator-only, and one test asserts the key is absent.

### D-14 - "Sprint 1 tables only" is not a workable database boundary

**Context:** Populating the shared Render `copup_db` was scoped to Sprint 1, so
the first migration pass applied only `contenttypes`, `auth`, `sessions`, `admin`,
`users`, `core`, `audit` and `token_blacklist` — 19 tables — leaving `chat`,
`codes`, `listings`, `notifications`, `orders`, `reports` and `reviews` unmigrated.

**Problem:** CP-102's expiry sweep removes unverified accounts by deleting the row
(D-07), and Django's delete collector walks *every* reverse relation on `User`.
All seven deferred apps hold FKs to `AUTH_USER_MODEL`, so the sweep died against
the partially-migrated database:

```
ProgrammingError: relation "listings" does not exist
```

Reproduced live against `copup_db`, then confirmed fixed after the full
migration.

**Decision:** Apply the full migration set (50 tables). A partially-migrated
shared database is not a sprint boundary, it is a broken one. Sprint scope stays
where it belongs: in what we *implement* and *test*. No Sprint 2+ endpoint,
serializer or test is claimed by this pass, and every Sprint 2+ table is empty.

**Rejected:** hard-coding a table-existence check around deletes (silently skips
real cascades and must be revisited every sprint); switching CP-102 to a soft
delete (breaks the email-reuse requirement that motivated D-07).

### D-16 - README is the single source of truth for setup

**Problem:** `CONTRIBUTING.md` (552 lines) and `README.md` (224 lines) both
documented setup. They drifted, and the drift was actively harmful: after
Cloudinary was deleted in D-13, `CONTRIBUTING.md` still instructed new
contributors to set `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` and
`CLOUDINARY_API_SECRET`. It also described a CI commit-message gate that does
not exist, an encryption guarantee that was never implemented, and a scheduled
endpoint path that does not exist yet.

**Decision:** Split by audience, and never duplicate.

| Document | Owns |
|---|---|
| `README.md` | Install, configure, run, test, debug. Everything operational. |
| `CONTRIBUTING.md` | Branch naming, commit conventions, SRS traceability, DoR/DoD, domain rules. Everything process. |

`CONTRIBUTING.md` was reduced from 552 to ~490 lines by deleting Prerequisites,
First-Time Setup and Troubleshooting, and now opens with a routing table
telling readers which file answers what. Setup instructions exist in exactly one
place.

**Rejected:** moving `CONTRIBUTING.md` into `docs/` — GitHub only surfaces the
root `CONTRIBUTING.md`, and the contribution guide UI would break. Merging
everything into `README.md` — the two have different readers (anyone cloning
vs. a teammate joining a sprint) and different update cadences.

**Also corrected in `CONTRIBUTING.md`:** the Ruff version note (pre-commit pins
its own isolated `v0.6.9` while the project runs `0.16.x`); the CI section now
lists only the four steps that actually exist and warns that CI fires on `dev`
and `main` only; §5.3 rule 3 now says encryption-at-rest is **not** implemented
(CP-107) instead of claiming it is; §5.3 rule 6 now names the real
`/api/v1/jobs/deactivate-unverified/` endpoint and the fail-closed `503`.

### D-15 - `Alumni` is removed from the project, permanently

**Decision (lead, 2026-10-05):** `Alumni` is out of scope. `users.affiliation`
has exactly three values — **`Student`, `Faculty`, `Staff`** — and that is the
final list.

**Standing instruction:** do not add `Alumni` to `AffiliationChoices`, do not
add an alumni registration path, do not infer alumni from the email domain, and
do not reintroduce it in any future sprint. If a document, diagram or spec still
mentions alumni, it is stale and should be corrected rather than followed. This
supersedes every earlier "undecided"/"still open"/"needs a team decision" note
about alumni anywhere in this repository.

**Why this needed no code change:** the code never implemented `Alumni` in the
first place. The enum has always been `[Student, Faculty, Staff]`, the live
Render `copup_db` holds zero user rows, and no migration is required — there is
no `Alumni` value in the database to strip out. The whole change is
documentation, so the team and any AI assistant reading this repo stop treating
it as an open question.

**What was corrected:** `docs/COPUP_ERD.md` (four places, including the `USERS`
enum comment and the draw.io sync checklist), this file, and
`CONTRIBUTING.md` §2.4 and §7.2, which described
`ALLOWED_STUDENT_EMAIL_DOMAIN` as the "student/alumni" domain and listed
"Students and Alumni" as a registration category. `@iskolarngbayan.pup.edu.ph`
is the **student** domain only.

**Also closed the same day:** the Render `copup_db` password was rotated after
being pasted into chat, and TODO 5 (`user_municipalities` / `user_provinces`
normalization) is the one remaining genuinely open question in this file.

## Fixes and issues found along the way

- **The ERD drew `municipality` and `province` as free-text strings on `USERS`.**
  The code has always used nullable FKs to the `Municipality` and `Province`
  lookup tables declared in the `users` app (physically `user_municipalities` and
  `user_provinces`). Verified against `copup_db` and corrected in
  `docs/COPUP_ERD.md`; this is the same lookup-table pattern as D-02.

- **DRF does not inject `request` into serializer context.** The CP-105
  submission serializer needs the current user to enforce "this ID number is not
  already linked to another account", but a serializer constructed as
  `Serializer(data=request.data)` has no `request` in `self.context` — reading it
  raises `KeyError`. Every context-dependent serializer in this codebase must be
  constructed with an explicit `context={"request": request}`.

- **Windows cannot re-read Django's spooled uploads.** Anything above
  `FILE_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB by default) is streamed to an on-disk
  temporary file, and the Windows test runner then fails with
  `PermissionError: [WinError 32]` when storage reads it back. The 5 MB cap
  therefore has its boundary asserted at the field level rather than over HTTP;
  the cap is storage-independent, so the rule is still tested properly. Not a
  production issue — real clients upload over the wire.

- **`ruff` 0.16.9 flags two framework idioms as `RUF012`.** Django reads
  `Meta.constraints`/`Meta.indexes` as plain lists and DRF merges
  `default_error_messages` across a serializer hierarchy; both are containers by
  contract. Added documented `per-file-ignores` for `**/models.py` and
  `**/serializers.py` rather than sprinkling `ClassVar` annotations that the
  frameworks do not read.

## Verification performed

| Gate | Result |
|---|---|
| `uv run ruff format --check .` | All files formatted |
| `uv run ruff check .` | All checks passed |
| `uv run python manage.py makemigrations --check --dry-run` | No changes detected |
| `uv run python manage.py migrate --check` | No pending migrations |
| `uv run python manage.py test` | **117 tests, all passing** |

Test counts by suite: `apps.users` 98 (CP-101's original 15 plus CP-102, CP-103 and
CP-105), `apps.core` 13 (the CP-102 cron endpoint's secret handling). The other
nine apps still have stub `tests.py` files.

New migrations applied cleanly: `0003_identitydocument_consent_given_and_more`
and `0004_seed_identity_document_lookups` (the latter is a data migration seeding
`IdentityDocumentType` and `IdentityDocumentStatus`, so CP-105 does not depend on
someone remembering to insert rows).

`POST /api/v1/jobs/deactivate-unverified/` was additionally exercised by hand
with a missing, malformed and correct token; a token in either bare or `Bearer`
form is accepted, and an unset `CRON_SECRET_TOKEN` fails closed with `503` rather
than running the sweep unprotected.

---

## 2026-10-06 — Identity Document Review (CP-106)

Branch: `feature/sprint-1_cp106-admin-identity-review`.

### D-17 — Admin review workflow and dual notification

**Decision:**
1. Document review authority is strictly restricted to Administrators (`is_staff=True`), conforming to D-03.
2. Endpoint: `POST /api/v1/identity/documents/<int:pk>/review/` accepting `action: "approve" | "reject"` and mandatory `rejection_reason` when rejecting.
3. Review decisions are final for that submission instance; once approved or rejected, the record cannot be re-reviewed.
4. Notifications are dual-channel: an immutable in-app `Notification` with type `verification_result` is recorded in the transaction, and an email notification is dispatched outside the transaction with mail server errors caught and logged so SMTP issues do not abort the review.
5. Approval immediately activates `user.has_verified_identity()`, satisfying the `IsIdentityVerified` permission gate. Rejection preserves the `rejection_reason` and enables the user to submit a fresh document.
6. A batch action `approve_selected_documents` is registered on `IdentityDocumentAdmin` to support bulk approval directly in `/admin/`.

---

## 2026-10-06 — Identity Document Protection & Access Logging (CP-107)

Branch: `feature/sprint-1_cp107-identity-document-protection`.

### D-18 — Document encryption at rest, secure download, and immutable audit logging

**Context:**
SRS FR3, FR14, and NFR 4.2 require confidential identity documents to be stored encrypted at rest, document access restricted strictly to Administrators, every admin access logged immutably with timestamp and IP, and admin-mediated contact release to only provide name/contact details (never the document itself).

**Decisions:**
1. **Fernet Symmetric Encryption:** Used Fernet (AES-128-CBC + HMAC-SHA256 authenticated encryption) from the standard `cryptography` package. Documents are encrypted on submission write path before persisting to `bytea` in Postgres, and decrypted only when requested by an authorized Admin.
2. **Dedicated Encryption Key (`IDENTITY_DOCUMENT_ENCRYPTION_KEY`):** Separate environment variable from `SECRET_KEY` so rotating web secret keys does not invalidate stored documents and vice versa.
3. **Fail-Closed in Production:** In production (`DEBUG=False` with PostgreSQL), an unset or malformed encryption key raises `ImproperlyConfigured` (fails closed). In local development and tests, an empty key gracefully passes through plaintext bytes to avoid breaking developers' setups unless encryption testing is explicitly configured.
4. **Dual Authentication on Download Endpoint:** `GET /api/v1/identity/documents/<int:pk>/download/` accepts both `JWTAuthentication` and `SessionAuthentication` with `IsAdminUser` permission. This allows Administrators clicking download links from the Django Admin browser interface (session auth) as well as API callers (JWT auth) to download decrypted documents securely.
5. **Django Admin Hardening:** Removed raw `document_data` byte display from `IdentityDocumentAdmin.readonly_fields` to prevent accidental exposure or large binary dump in the DOM. Replaced it with a safe `download_link` pointing to the secure download endpoint.
6. **Immutable Audit Trail (`AdminAccessLog`):** Every administrative touch creates an immutable `AdminAccessLog` record tracking `document`, `admin`, `action` (`view`, `download`, `review`, `contact_release`), `ip_address`, and `accessed_at`. `AdminAccessLogAdmin` explicitly disallows add, change, and delete operations.
7. **Admin-Mediated Contact Release:** Added `GET /api/v1/identity/documents/<int:pk>/owner-info/` returning exclusively `full_name`, `email`, `contact_number`, and `affiliation`. Raw document bytes, `id_number`, and credential fields are never exposed. Access is logged with `action="contact_release"`.
