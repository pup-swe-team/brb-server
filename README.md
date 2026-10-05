# brb-server

Django REST API backend for **BRB (Borrow, Return, Borrow)** — a PUP community
lending platform for students to borrow and return items.

Django 5.1 · Django REST Framework · PostgreSQL (Render) · SimpleJWT

---

## Current status

Sprint 1 onboarding is implemented and under review:

| Ticket | Scope | State |
|---|---|---|
| CP-101 | Register with PUP-affiliated email | Done |
| CP-102 | Verify email address | Done |
| CP-103 | Log in to account | Done |
| CP-104 | Recover forgotten password | **Not started** — Sprint 2 |
| CP-105 | Submit identity verification document | Done, minus the listing gate |

See [`docs/changelog-updating.md`](docs/changelog-updating.md) for the full list of
changes and [`docs/BRB_BACKEND_SPRINTS.md`](docs/BRB_BACKEND_SPRINTS.md) for
ticket checkboxes.

---

## What you need

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12+ | `requires-python = ">=3.12"` |
| [uv](https://docs.astral.sh/uv/) | latest | Manages the venv, lockfile and commands |
| PostgreSQL | — | Use the team's Render DB, or a local SQLite file |

You do **not** need a separate Postgres install if you use the team database URL.

Check your versions:

```powershell
python --version
uv --version
```

---

## Setup

### 1. Get the code and install dependencies

```powershell
git clone <repo-url> brb-server
cd brb-server
uv sync
```

`uv sync` creates `.venv` and installs from `uv.lock`. It also installs a
`django-admin` shim, so `python manage.py ...` works once the venv is active.

> Do **not** run `pip install -r requirements.txt`; this project uses `uv` and has
> no such file.

### 2. Create your environment file

```powershell
Copy-Item .env.example .env      # Windows PowerShell
cp .env.example .env             # Git Bash / macOS / Linux
```

Then fill in these values in `.env`:

| Variable | Where to get it |
|---|---|
| `DATABASE_URL` | Render dashboard → your Postgres instance → **Connect** → copy the URI |
| `JWT_SECRET` | Generate one: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SECRET_KEY` | Any long random string for local work |

> **`.env` is gitignored. Never commit it, and never paste a live database URL
> into a PR, an issue, or chat.** `.env.example` holds placeholders only and is the
> file that is safe to share.

> The database password goes **inside `DATABASE_URL`**
> (`postgresql://USER:PASSWORD@HOST:5432/DBNAME`). There is no separate
> `DATABASE_PASSWORD` variable — Django ignores one if you add it.

`CRON_SECRET_TOKEN` ships with a local-only default. Change it for anything
non-local.

### 3. Apply migrations

```powershell
uv run python manage.py migrate
```

**Read this before you run it.** If `DATABASE_URL` points at the team's Render
database, `migrate` writes to a database **everyone shares**. Ask in the team
channel first — whoever migrates first populates it for everyone, and a later
`makemigrations` from your branch will change the schema under your teammates'
feet.

**Always run the full `migrate` — do not cherry-pick app labels.** An earlier
attempt to migrate only the Sprint 1 apps looked tidier but broke CP-102: deleting
a `User` makes Django walk every reverse relation, and the unmigrated Sprint 2+
apps all FK to `AUTH_USER_MODEL`, so the expiry sweep crashed with
`relation "listings" does not exist`. Partial migrations are unsafe here (D-14).

> **Already done (2026-10-05):** the shared Render `copup_db` is migrated — 50
> tables, 0 rows. You do not need to run `migrate` to start working; just pull.

To work in isolation instead, use a local SQLite file:

```powershell
$env:DATABASE_URL="sqlite:///db.sqlite3"
uv run python manage.py migrate
```

### 4. Create an admin

**This is how the runtime settings and identity submissions are managed**, so it is
worth doing rather than skipping:

```powershell
uv run python manage.py createsuperuser
```

Then log in at `http://127.0.0.1:8000/admin/`:

- **System Configurations** — the CP-102 expiry window and CP-103 lockout
  threshold/minutes. This is what makes those "Admin-configurable"; without an
  admin account you would have to use `manage.py shell`.
- **Identity Documents** — every CP-105 submission, including a size summary of
  the uploaded file. This is the *only* surface that may show a document; the
  mobile API never returns it.

### 5. Run the server

```powershell
uv run python manage.py runserver
```

The API is at `http://127.0.0.1:8000/api/v1/`. The full list of endpoints is in
the API surface table below, and the Django admin (where you can review identity
submissions and edit `SystemConfig`) is at `http://127.0.0.1:8000/admin/`.

---

## Running the tests

```powershell
uv run python manage.py test
```

> **Do this against SQLite, not the shared Postgres.** The test runner creates and
> drops a whole `test_<name>` database on whichever server `DATABASE_URL` names.
> Against Render that means a full create/migrate/drop cycle over the network on
> every run (roughly double the wall-clock time), and it needs `CREATEDB` rights on
> the team's database.

```powershell
# PowerShell — override for this shell session only
$env:DATABASE_URL="sqlite:///db.sqlite3"
uv run python manage.py test

# bash / macOS / Linux
DATABASE_URL=sqlite:///db.sqlite3 uv run python manage.py test
```

A real environment variable wins over `.env`, so this only affects the current
terminal.

Current suite: **117 tests, all passing.** Verified against SQLite and against
the team's Render PostgreSQL.

---

## Quality gates

Run all four before you open a PR:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
```

Or let pre-commit do it:

```powershell
uv run pre-commit run --all-files
```

The same four gates run in CI on every push.

---

## Working on a ticket

1. **Read the ticket's acceptance criteria** in `docs/BRB_BACKEND_SPRINTS.md` and
   tick the boxes as you verify each one.
2. **Branch with the team convention** (see `CONTRIBUTING.md` §4.1):

   ```
   feature/sprint-<n>_cp<ticket>-<short-description>
   ```

   For example `feature/sprint-1_cp105-identity-document`. Lowercase, no
   zero-padded ticket numbers. Ticketless work uses
   `<category>/sprint-<n>_no-ticket-<description>`.

3. **Migrations**: if you touch a model, run
   `uv run python manage.py makemigrations`. A pull request that changes a model
   without a migration will fail the CI migration check.
4. **Tests**: add or update tests alongside the change. New behaviour without a
   test does not count as done.
5. **Update the docs** in the same PR — tick the sprint checkbox, note the
   decision in `docs/DECISIONS.md` if you made a judgement call, and add a schema
   line to `docs/COPUP_ERD.md` if the data shape changed.
6. **Append to `docs/changelog-updating.md`** so the next person knows what moved.

---

## Configuration reference

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | SQLite file | Team Render Postgres, or local SQLite |
| `SECRET_KEY` | yes | dev placeholder | Django signing key |
| `JWT_SECRET` | yes | dev placeholder | JWT signing key. **Minimum 32 bytes** for HS256 |
| `ALLOWED_HOSTS` | yes | `localhost,127.0.0.1` | Permitted hosts |
| `ALLOWED_STUDENT_EMAIL_DOMAIN` | no | `iskolarngbayan.pup.edu.ph` | SRS 4.2 |
| `ALLOWED_FACULTY_EMAIL_DOMAIN` | no | `pup.edu.ph` | SRS 4.2 |
| `CRON_SECRET_TOKEN` | no | dev token | Protects `/api/v1/jobs/`. Unset ⇒ `503`, never open |
| `EMAIL_BACKEND` | no | console | Console prints confirmation links to the terminal |
| `DEFAULT_FROM_EMAIL` | no | `no-reply@brb.pup.edu.ph` | Sender address |
| `EMAIL_VERIFICATION_REDIRECT_URL` | no | `brb://auth/verify-email` | CP-102 link target |

### File storage

CP-105 identity documents are stored **in Postgres** (`bytea`), not in Cloudinary
or on disk. Render's filesystem is ephemeral and its free tier has no persistent
disk, so a file on disk would be lost on the next redeploy. Rationale in
`docs/DECISIONS.md` D-13.

### Email in local development

`EMAIL_BACKEND` defaults to the console backend, so the CP-102 confirmation link
prints straight into the `runserver` terminal. No mail provider account needed.

To test against a real provider, comment in the Resend/SendGrid block in `.env`.

---

## API surface (as of Sprint 1)

All paths are prefixed `/api/v1/`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/register/` | — | CP-101 registration |
| POST | `/auth/verify-email/` | — | CP-102 click-to-verify |
| POST | `/auth/login/` | — | CP-103 login, returns access + refresh |
| POST | `/auth/token/refresh/` | — | CP-103 rotate access token |
| POST | `/auth/logout/` | Bearer | CP-103 blacklist refresh token |
| POST | `/identity/documents/` | Bearer | CP-105 submit document |
| GET | `/identity/documents/list/` | Bearer | CP-105 own submissions |
| POST | `/jobs/deactivate-unverified/` | Cron secret | CP-102 7-day sweep |

`/jobs/` accepts the token bare or as `Authorization: Bearer <token>`.

---

## Database

The team database is **Render-managed PostgreSQL** (Singapore region). It is a
separate Render resource that the web service connects to over the network — the
database is not embedded in the app, so:

- Keep the Render **web service in the same region** as the database, or every
  query pays cross-region latency.
- The app relies on Postgres-specific behaviour (`bytea` for documents). SQLite is
  fine for tests, but do not treat a SQLite pass as production validation.

---

## Troubleshooting

**`connection refused` / `could not translate host name`**
Check `DATABASE_URL`, and that you are on the network. Confirm with:
`uv run python -c "import os,django; os.environ['DJANGO_SETTINGS_MODULE']='brb_server.settings'; django.setup(); from django.db import connection; connection.ensure_connection(); print('ok')"`

**`InsecureKeyLengthWarning`**
`JWT_SECRET` is under 32 bytes. Regenerate it (see above).

**Upload fails or `identity_documents` has no rows**
Document bytes go to Postgres, so confirm `migrate` has been run against the
database you are actually connected to.

**`manage.py test` is very slow**
You are pointed at the shared database. See the SQLite override above.

**Email link does not arrive**
Console backend prints to the terminal running `runserver`, not to an inbox.

---

## Further reading

- `CONTRIBUTING.md` — conventions, quality gates, branch naming
- `docs/BRB_BACKEND_SPRINTS.md` — tickets and acceptance criteria
- `docs/DECISIONS.md` — decisions with rationale, plus open questions
- `docs/COPUP_ERD.md` — entity relationship diagram
- `docs/changelog-updating.md` — what changed, newest first
