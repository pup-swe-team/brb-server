# AGENTS.md — instructions for AI coding assistants

Read this before making any change in this repository. It records decisions a
model cannot infer from the code, and it overrides anything you find that
contradicts it.

## Project

- **BRB Server** — Django REST API for the PUP campus resource borrowing system
  ("Iskolar Ngbayan"). Students borrow listed items from other students.
- Python 3.12, Django 5.x, DRF, SimpleJWT, PostgreSQL on Render.
- App layout: 10 Django apps mapped onto 7 logical ERD domains.
- Branch convention: `<category>/sprint-<n>_cp<ticket>-<short-description>`.
- Full history of reasoning is in `docs/DECISIONS.md` (read D-01 onward).

## Hard rules

1. **`Alumni` does not exist in this project. Never add it.**
   `users.affiliation` has exactly three values: `Student`, `Faculty`, `Staff`.
   Do not add `Alumni` to `AffiliationChoices`, do not add an alumni
   registration path, do not infer alumni from an email domain. If you find a
   document that still mentions alumni, it is stale — correct it, do not follow
   it. (Decision D-15.)

2. **Never run a partial migration.** Always `uv run python manage.py migrate`
   with no app labels. Migrating a subset of apps breaks CP-102: deleting a
   `User` makes Django walk every reverse relation, and the other apps all FK to
   `AUTH_USER_MODEL`, so the expiry sweep crashes with
   `relation "listings" does not exist`. (Decision D-14.)

3. **The Render database is shared.** `.env` points at the team's live
   `copup_db`. `migrate` writes to everyone's database. Never run the test suite
   against it — tests create and drop a whole `test_copup_db` and need
   `CREATEDB`. For routine tests use SQLite:
   `$env:DATABASE_URL="sqlite:///db.sqlite3"`.

4. **Never commit secrets.** `.env` is gitignored and untracked. No credentials
   belong in any tracked file, including `.env.example` (use the literal
   placeholder `USER:PASSWORD@HOST`).

## Architecture decisions you must not re-litigate

| ID | Decision |
|---|---|
| D-02 | Lookup tables stay. The ERD's blanket "use TextChoices" rule is wrong for reference data. |
| D-03 | Administrator authority is `is_staff`. Do not add an `is_admin` field. `affiliation` has no `Admin` value. |
| D-06 | Unverified accounts cannot log in. |
| D-07 | The 7-day unverified sweep **deletes** rows rather than setting a flag, so the email returns to the pool for re-registration. |
| D-08 | Verification token lifetime is per-instance, not `PASSWORD_RESET_TIMEOUT`. |
| D-09 | The verification link targets the app; confirmation is a `POST`, not a `GET`. |
| D-11 | `id_number` is unique per account, enforced in the serializer. |
| D-12 | Auth failures are `401`, not `400`. |
| D-13 | Identity document bytes are Postgres `bytea`. **Cloudinary is removed.** Never reintroduce external object storage for documents. |
| D-14 | Full migration set only. |
| D-15 | `Alumni` removed from the project. |

## Scope

- **Sprint 1** is CP-101 (registration, merged), CP-102 (email verification),
  CP-103 (login/session lifecycle), CP-105 (identity submission).
  CP-104 is deliberately deferred to Sprint 2.
- Tables for later sprints (listings, orders, chat, reviews, codes, reports,
  notifications) exist but are **empty** and untested. Do not implement their
  endpoints, and do not write tests that claim their features work.
- Known intentional gaps: CP-107 encryption-at-rest for document bytes is not
  applied (CP-105 only caps size at 5 MB); `users.photo` still uses Render's
  ephemeral filesystem. The CP-105 listing/request gate is blocked because
  CP-301/CP-501 endpoints do not exist.

## Gotchas that will waste your time if you do not know them

- **DRF does not inject `request` into serializer context.** Any serializer
  using `self.context["request"]` must be constructed with an explicit
  `context={"request": request}`.
- **Windows cannot re-read Django's spooled uploads.** Uploads above
  `FILE_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB) stream to a temp file the Windows test
  runner then cannot reopen (`WinError 32`). Assert upload size limits at the
  field level, not over HTTP.
- **`ruff` 0.16.9 flags `RUF012` on two framework idioms.** `Meta.constraints`,
  `Meta.indexes` and `default_error_messages` are plain lists by contract;
  documented `per-file-ignores` handle this. Do not add `ClassVar` annotations
  the frameworks do not read.
- **`.env` values are loaded by `load_dotenv()` and do not override real
  environment variables.** A `$env:DATABASE_URL` you set in the shell wins over
  `.env`, and it persists after the command. Clear it explicitly when switching
  between SQLite and Render.

## Before you finish

Run all of these and expect clean output:

```powershell
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --check
uv run ruff format --check .
uv run ruff check .
$env:DATABASE_URL="sqlite:///db.sqlite3"; uv run python manage.py test
Remove-Item Env:\DATABASE_URL
uv run pre-commit run --all-files
```

Record anything non-obvious in `docs/DECISIONS.md` as a new `D-nn` entry, and
add user-visible changes to `docs/changelog-updating.md`.
