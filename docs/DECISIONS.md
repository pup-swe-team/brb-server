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
team decision, nothing removed. `Alumni` affiliation is also still undecided
and was not part of the original TODO list.

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

1. **`Alumni` affiliation is missing.** The ERD specifies
   `student, alumni, faculty, staff`; the code now has
   `Student, Faculty, Staff` (see D-03). `CONTRIBUTING.md` §2.4 also describes
   `ALLOWED_STUDENT_EMAIL_DOMAIN` as validating the "student/alumni" domain, so
   alumni appear to be in scope. Note that both student and alumni share the
   `@iskolarngbayan.pup.edu.ph` domain, so the two cannot be told apart by
   email domain alone — CP-101 will need an explicit signal. Needs adding, or an
   explicit decision to drop.

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
