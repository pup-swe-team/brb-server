# Contributing to BRB Server (`brb-server`)

Welcome to the backend repository of **BRB (Borrow, Return, Borrow)**! This guide establishes the development workflow, coding conventions, architectural patterns, and quality standards for our backend engineering team.

Please read this document thoroughly before opening your first pull request. The mobile application team maintains its companion guide in the client repository.

| Role | Responsibilities |
|---|---|
| **Backend Developers** | Django REST Framework API, database models, migrations, background jobs, serializers, services, and automated tests in `brb-server` |
| **Mobile Developers** | React Native + Expo mobile client, client state management, UI/UX screens, in-app polling |
| **Admin Portal Maintainers** | Django Admin customizations, moderation queues, identity verification views, audit logging |
| **Product Owner & Course Instructor** | Backlog prioritization, SRS alignment, final code reviews, and production releases to `main` (Instructor: Mr. Chris Nicole F. Piamonte) |

Project tracking and sprint boards are managed under the [pup-swe-team GitHub Organization](https://github.com/pup-swe-team).

---

## Contents

1. [Prerequisites](#1-prerequisites)
2. [First-Time Setup](#2-first-time-setup)
3. [Daily Development Workflow](#3-daily-development-workflow)
4. [Branches and Commits](#4-branches-and-commits)
5. [Code Quality: Ruff and Local Hooks](#5-code-quality-ruff-and-local-hooks)
6. [Continuous Integration (CI) and Quality Enforcement](#6-continuous-integration-ci-and-quality-enforcement)
7. [Coding Standards and BRB Architecture](#7-coding-standards-and-brb-architecture)
8. [Writing Issues and SRS Traceability](#8-writing-issues-and-srs-traceability)
9. [Definition of Ready and Done](#9-definition-of-ready-and-done)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

Ensure the following tools are installed on your workstation:

| Tool | Minimum Version | Verification Command | Notes |
|---|---|---|---|
| **Git** | 2.40+ | `git --version` | Configured with your PUP student/faculty email |
| **Python** | 3.12 | `python --version` | Managed via `uv` or system Python |
| **[uv](https://docs.astral.sh/uv/)** | 0.7+ (Recommended 0.12+) | `uv --version` | Ultra-fast Python package and project manager |

### Operating System & Shell Guidelines
- **Windows**: Use **Git Bash** or **PowerShell**. Avoid Command Prompt (`cmd.exe`).
- **macOS / Linux**: Use your standard POSIX terminal (`zsh` or `bash`).
- Commands throughout this guide are prefixed with `uv run`, which guarantees execution inside the managed virtual environment (`.venv`).

---

## 2. First-Time Setup

### 2.1 Clone the Repository
Clone `brb-server` and navigate into the project directory:

```bash
git clone git@github.com:pup-swe-team/brb-server.git
cd brb-server
git checkout dev
```

> [!IMPORTANT]
> Always verify you are branched off **`dev`** before starting work. `main` is reserved for stable production releases.

### 2.2 Install Dependencies with `uv`
Initialize your virtual environment and install all runtime dependencies and development tools (`ruff`, `pre-commit`):

```bash
uv sync --dev
```

This creates `.venv` and locks dependencies in `uv.lock`.

### 2.3 Install Pre-Commit Hooks
Activate automated git checks to validate staged files locally before every commit:

```bash
uv run pre-commit install
```

### 2.4 Configure Local Environment
Create your local environment file by copying the template:

```bash
# Git Bash / Linux / macOS:
cp .env.example .env

# Windows PowerShell:
Copy-Item .env.example .env
```

Open `.env` and review the local development values:

| Environment Variable | Local Default | Purpose |
|---|---|---|
| `DEBUG` | `True` | Enables Django debug mode and detailed error pages |
| `SECRET_KEY` | *(Generated dev secret)* | Secret key for cryptographic signing |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated list of allowed host/domain names |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | Zero-configuration local database (or PostgreSQL connection string for Render parity) |
| `DATABASE_PASSWORD` | `yourpassword` | Database password when connecting to local or remote PostgreSQL |
| `JWT_SECRET` | *(Dev JWT secret)* | Key used for signing authentication tokens |
| `ALLOWED_STUDENT_EMAIL_DOMAIN` | `iskolarngbayan.pup.edu.ph` | Validates student registration domain (SRS FR1, NFR 4.2). Students only — `Alumni` was removed from the project (DECISIONS.md D-15) |
| `ALLOWED_FACULTY_EMAIL_DOMAIN` | `pup.edu.ph` | Validates faculty/staff registration domain (SRS FR1, NFR 4.2) |
| `CRON_SECRET_TOKEN` | `local-dev-cron-token-brb` | Bearer token for protected scheduled endpoints (SRS Section 2.4 & 5.2) |
| `EMAIL_BACKEND` | `django.core.mail.backends.console.EmailBackend` | Dumps verification/reset emails to terminal in local development |
| `DEFAULT_FROM_EMAIL` | `no-reply@brb.pup.edu.ph` | Default email sender address |
| `CLOUDINARY_CLOUD_NAME` | *(Your Cloudinary cloud name)* | Cloudinary cloud identifier for media/document uploads |
| `CLOUDINARY_API_KEY` | *(Your Cloudinary API key)* | Cloudinary API key for storage authentication |
| `CLOUDINARY_API_SECRET` | *(Your Cloudinary API secret)* | Cloudinary API secret key |

> [!CAUTION]
> `.env` is ignored by Git. Never commit `.env` or paste real secrets or credentials into issues, pull requests, or chat messages.

### 2.5 Apply Database Migrations
Initialize the local database schema:

```bash
uv run python manage.py migrate
```

### 2.6 Create an Administrator Account
Create a local superuser to access the Django Admin portal:

```bash
uv run python manage.py createsuperuser
```

Provide a name and a PUP webmail address (e.g., `admin@iskolarngbayan.pup.edu.ph` or `admin@pup.edu.ph`).

### 2.7 Verify Setup and Run the Server
Run Django's system check to confirm there are no configuration issues:

```bash
uv run python manage.py check
```

Start the development server:

```bash
uv run python manage.py runserver
```

Open your browser to verify:
- **Django Admin Portal**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)
- **API Root / Documentation**: [http://127.0.0.1:8000/api/](http://127.0.0.1:8000/api/)

---

## 3. Daily Development Workflow

Follow this step-by-step workflow for all contributions:

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Backend Developer
    participant Board as GitHub Projects Board
    participant Local as Local Git Branch
    participant CI as GitHub Actions CI
    participant Repo as Upstream dev Branch

    Dev->>Board: Pick issue from "Ready" column & move to "In Progress"
    Dev->>Local: git checkout dev && git pull origin dev
    Dev->>Local: uv sync --dev (ensure dependencies & tools are current)
    Dev->>Local: git checkout -b feature/sprint-<n>_cp<ticket>-<desc>
    Dev->>Local: Write code + unit tests
    Dev->>Local: Run Ruff (ruff check / ruff format)
    Dev->>Local: Run tests (uv run python manage.py test)
    Dev->>Local: git commit -m "feat(module): description"
    Dev->>Repo: git pull origin dev (resolve any conflicts)
    Dev->>Repo: git push -u origin feature/sprint-<n>_cp<ticket>-<desc>
    Dev->>Repo: Open Pull Request against dev
    CI->>Repo: Run automated checks (Ruff, tests)
    Dev->>Board: Move issue to "In Review"
    Repo-->>Dev: Peer Review & Approval
    Dev->>Repo: Squash and merge into dev
```

1. **Pick an Issue**: Select an assigned issue from the **Ready** column on the board. Assign yourself and move it to **In Progress**.
2. **Sync Dependencies and Branch**:
   ```bash
   git checkout dev
   git pull origin dev
   uv sync --dev
   git checkout -b feature/sprint-3_cp504-handover-code
   ```
3. **Develop in Small Commits**: Write clean code backed by unit tests.
4. **Run Ruff Linting and Formatting**:
   ```bash
   # Linting (detects code errors, dead code, import order):
   uv run ruff check .

   # Formatting (applies uniform styling):
   uv run ruff format .
   ```
   *If you use `uv run ruff check --fix .`, always inspect `git diff` before staging.*
5. **Run Automated Tests**:
   ```bash
   uv run python manage.py test
   ```
6. **Commit Your Changes**: Follow Conventional Commits format:
   ```bash
   git add <changed-files>
   git commit -m "feat(orders): validate return authentication codes"
   ```
7. **Rebase or Merge Upstream Changes**:
   ```bash
   git checkout dev
   git pull origin dev
   git checkout feature/sprint-3_cp504-handover-code
   git merge dev
   uv run python manage.py test
   ```
8. **Push and Open a PR**:
   ```bash
   git push -u origin feature/sprint-3_cp504-handover-code
   ```
   Open a PR targeting the **`dev`** branch. In the PR description, link the issue using `Closes #XX`.
9. **Peer Review & CI Validation**: CI runs automated checks (Ruff, test suite). Address peer review feedback with additional commits.
10. **Squash and Merge**: Once approved and all required checks pass, the PR is **squash-merged** into `dev`. Delete the feature branch afterwards.

---

## 4. Branches and Commits

### 4.1 Branch Naming Conventions
Branch names must be lowercase, hyphen-separated, and prefixed by category.

Every branch that does work on a sprint ticket carries **both** the sprint number and the ticket number, so a branch can be traced back to `docs/BRB_BACKEND_SPRINTS.md` without opening the tracker:

```
<category>/sprint-<n>_cp<ticket>-<short-description>
```

| Branch Pattern | Purpose | Example |
|---|---|---|
| `main` | Production release branch. Direct commits strictly prohibited. | `main` |
| `dev` | Active integration branch. Target of all PRs. Direct commits strictly prohibited. | `dev` |
| `feature/sprint-<n>_cp<ticket>-<desc>` | New feature development | `feature/sprint-1_cp102-email-verification` |
| `bugfix/sprint-<n>_cp<ticket>-<desc>` | Bug fix for code on `dev` | `bugfix/sprint-1_cp103-login-lockout` |
| `hotfix/sprint-<n>_cp<ticket>-<desc>` | Critical fix for code on `main` | `hotfix/sprint-1_cp102-verification-token` |
| `refactor/sprint-<n>_cp<ticket>-<desc>` | Code restructuring without behavior changes | `refactor/sprint-2_cp301-listing-filters` |
| `test/sprint-<n>_cp<ticket>-<desc>` | Test coverage improvements | `test/sprint-1_cp105-identity-documents` |

Rules for the ticket segment:

- Keep the `cp` prefix in lowercase and **do not zero-pad**: `cp102`, not `cp0102`. Ticket numbers reach four digits (e.g. `CP-1001`, `CP-1105`), so padding would make `cp1001` ambiguous to read.
- The `<short-description>` is 2–4 lowercase hyphenated words, in plain English. It is a label for humans scanning `git branch`, not a restatement of the ticket title.
- The ticket number identifies the ticket. The **domain** is expressed by the Conventional Commit **scope** (§4.2), not by the branch name — so branch names should not repeat the module.

#### Work with no ticket number
Some work has no CP ticket: infrastructure, dependency bumps, CI changes, documentation, or the pre-sprint setup pass. Use `no-ticket` in place of the ticket number so these branches stay self-describing and can be filtered out of ticket-scoped queries:

```
<category>/sprint-<n>_no-ticket-<desc>
```

| Example | Purpose |
|---|---|
| `feature/sprint-1_no-ticket-simplejwt-setup` | Prerequisite infrastructure with no ticket |
| `chore/sprint-0_no-ticket-dependency-bumps` | Maintenance outside any sprint (`sprint-0` = pre-sprint) |

### 4.2 Conventional Commits
All commit messages and PR titles must adhere to the **Conventional Commits** specification:

```
<type>(<scope>): <description>
```

#### Allowed Types
- **`feat`**: A new feature or API capability
- **`fix`**: A bug fix
- **`docs`**: Documentation updates only
- **`style`**: Formatting, whitespace, or linting fixes without code behavior changes
- **`refactor`**: Code reorganization that neither fixes a bug nor adds a feature
- **`perf`**: A performance improvement
- **`test`**: Adding, updating, or fixing automated tests
- **`chore`**: Build tools, dependency bumps, or repository configuration

#### Scopes (Tailored to BRB Domains)
Use the scope corresponding to the functional domain:
- `core`: Abstract base models (`TimeStampedModel`), platform-wide dynamic configuration (`SystemConfig`)
- `auth`: PUP webmail validation, registration, login, JWT issuance, password reset (housed in `apps/users`)
- `users`: Profiles, affiliations, deactivation, role switching
- `verify`: Identity document upload, verification review, consent management
- `listings`: Resource posting, categories, search, filters, availability dates
- `orders`: Borrow requests, approvals, cancellation, active orders, completions
- `codes`: Handover authentication codes, return authentication codes, rate limiting
- `disputes`: Damage reporting, missing parts, dispute cases, OSS/Campus Security escalation
- `chat`: One-to-one messaging, order-linked chat history, user blocking
- `notifications`: In-app event notifications, notification preferences, email delivery
- `reports`: Content/user reporting, 30-day auto-flagging, admin report queue
- `admin`: Admin dashboard, configuration parameters, pickup locations, metrics
- `audit`: Read-only administrator audit logging

#### Examples
- `feat(auth): validate student and faculty pup webmail domains`
- `fix(codes): prevent reused return codes after order completion`
- `test(orders): add unit tests for overlapping borrowing dates`
- `refactor(listings): extract availability filter into service layer`

---

## 5. Code Quality: Ruff and Local Hooks

Our project relies on **Ruff** for high-speed Python linting and code formatting, and optional local git hooks for rapid feedback before committing.

### 5.1 Ruff Linting and Formatting
Ruff provides two distinct capabilities: **linting** (`ruff check`) and **formatting** (`ruff format`).

| Tool Command | Purpose | What It Does |
|---|---|---|
| `uv run ruff check .` | **Linting** | Analyzes Python files for logical bugs, syntax errors, dead code, unused imports/variables, anti-patterns, and import ordering. |
| `uv run ruff check --fix .` | **Automated Fixes** | Automatically resolves lint violations that have safe, deterministic fixes (such as import sorting and dead variable removal). |
| `uv run ruff format .` | **Formatting** | Formats all Python source code to enforce uniform indentation, quoting, line breaks, and bracket styles across the repository. |
| `uv run ruff format --check .` | **Format Check** | Assesses whether any files require formatting without altering file content (used in CI environments). |

#### Resolving Violations and Reviewing Fixes
- **Fix, Do Not Ignore**: Ruff violations should normally be corrected directly in source code rather than suppressed or bypassed.
- **Review Automated Fixes**: While `uv run ruff check --fix .` is convenient, contributors must always review the resulting diff (e.g., using `git diff`) before staging or committing. Automated fixes can occasionally remove necessary side-effect code or alter code structure in unintended ways.
- **Accurate Terminology**: Ruff performs comprehensive Python linting and formatting (covering rules inspired by Flake8, isort, pyupgrade, and Black); avoid describing it as merely enforcing PEP 8.

#### Handling Intentional Exceptions in Django Code
Django applications occasionally require imports that appear unused to a static linter but are necessary for module initialization and runtime side effects (for example, importing signal receivers inside an app's `AppConfig.ready()` method, registering custom model fields, or importing models in an app initialization file).

- **Avoid Global Disabling**: **Do not broadly disable rules like `F401` (unused import)** project-wide or across entire files simply because the project is built with Django. Doing so masks legitimate dead code and import bugs.
- **Explicit Inline Exception**: When an import is legitimately required solely for its side effects, mark that specific line with an inline `# noqa: <rule>` comment and document why the exception is needed:

```python
# apps/users/apps.py
from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"

    def ready(self) -> None:
        from . import signals  # noqa: F401 - Required for signal receiver registration
```

---

### 5.2 Local Git Hooks and Pre-Commit
Pre-commit hooks provide fast local feedback on your machine before a commit is created, preventing unformatted or broken code from entering your local Git history.

- **Fast Local Feedback**: Running checks before committing allows you to detect formatting flaws, unresolved lint errors, and syntax issues immediately, without waiting for remote CI runs.
- **Not a Security or Repository-Enforcement Boundary**:
  - Local git hooks execute solely in the contributor's local environment.
  - Because any contributor can bypass local hooks at any time by running `git commit --no-verify`, **local hooks are not a security mechanism or repository-enforcement boundary**.
- **Guidance on Bypassing Hooks**:
  - Bypassing local hooks with `--no-verify` is discouraged during normal development because it bypasses early quality feedback and risks pushing flawed commits.
  - However, **bypassing a local hook does not inherently cause CI to fail**. CI evaluates the pushed code independently in a clean container; if the submitted code complies with all project standards, CI will pass regardless of whether local hooks were executed.
- **Configured Repository Hooks (`.pre-commit-config.yaml`)**:
  Pre-commit is managed in `pyproject.toml` (`pre-commit>=4.6.2`) and configured in `.pre-commit-config.yaml`. Install the hooks into your local Git repository clone:
  ```bash
  uv run pre-commit install
  ```
  To manually trigger all hooks across all files at any time:
  ```bash
  uv run pre-commit run --all-files
  ```
- **Configured Hooks & Rationale**:
  - `trailing-whitespace`: Automatically trims trailing spaces from line endings.
  - `end-of-file-fixer`: Enforces a single standard newline at the end of text files.
  - `check-yaml`: Validates the syntax of all YAML files.
  - `check-added-large-files`: Prevents accidental commits of large binary files (>500KB).
  - `detect-private-key`: Blocks accidental commits of private cryptographic keys.
  - `ruff` (`v0.6.9`): Checks staged Python files for lint errors and improper imports.
    - *Intentional Safety Design*: `args: [--fix]` is intentionally **omitted** so that Ruff never automatically deletes Django imports needed for runtime side effects (e.g., signal handlers or model registration).
    - *Migrations Excluded*: Excludes `^apps/.*/migrations/` so that auto-generated Django migration files are not flagged.
  - `ruff-format` (`v0.6.9`): Enforces consistent Python code formatting on staged files (excluding migrations).

---

## 6. Continuous Integration (CI) and Quality Enforcement

While local checks and git hooks provide fast personal feedback to individual developers, **GitHub Actions CI is the authoritative verification platform** for the repository.

### 6.1 Intended CI Pipeline Checks
When pull requests are submitted against the `dev` branch, the CI pipeline is designed to execute the authoritative project checks in a clean environment:

| Quality Gate | Tool / Command | Purpose |
|---|---|---|
| **Linting & Import Order** | `uv run ruff check .` | Verifies code quality, detects programming defects, and checks import sorting |
| **Code Formatting** | `uv run ruff format --check .` | Verifies that all files conform to the project formatting style |
| **Automated Test Suite** | `uv run python manage.py test` | Executes the complete Django test suite to guarantee regression stability |
| **PR & Commit Conventions** | Automated PR title / commit check | Confirms PR title and commits follow the Conventional Commits specification |

### 6.2 Merge Requirements and Branch Protection
It is essential to distinguish between workflow execution and repository merge enforcement:

- **Workflows vs. Branch Protection**: Simply defining or running a GitHub Actions workflow **does not automatically block pull requests from merging**.
- **Required Status Checks**: A failed CI check only becomes a strict, blocking merge barrier when repository administrators configure GitHub **Branch Protection Rules** or **Repository Rulesets** for target branches (`dev` and `main`) and designate specific jobs as **Required Status Checks**.
- **Intended Quality Standard**: Where branch protection rulesets are not yet configured or enforced in repository settings, all contributors and peer reviewers are expected to treat these checks as mandatory quality gates. Never approve or squash-merge a pull request that has failing test or lint runs.

---

## 7. Coding Standards and BRB Architecture

To maintain clarity, scalability, and maintainability across the team, all backend code must conform to the architectural guidelines below.

### 7.1 Django REST Framework Architecture
Organize features by modular Django apps:

```
brb_server/
├── brb_server/              # Project settings, root urls, WSGI/ASGI
├── apps/
│   ├── core/               # Abstract base models (TimeStampedModel), SystemConfig runtime parameters (FR14)
│   ├── users/              # Custom User model, PUP webmail auth, profiles, affiliations, identity verification (FR1-FR3, FR13)
│   ├── listings/           # Items, categories, availability calendar, pickup locations, listing photos (FR6-FR7)
│   ├── orders/             # Order lifecycle, status overrides, disputes & evidence, unreturned cases (FR8)
│   ├── codes/              # Handover & return OTP generation, status tracking, rate-limiting attempts (FR8, NFR 4.4)
│   ├── chat/               # 1-to-1 conversations, order-linked chat history, user blocking (FR10)
│   ├── reviews/            # Mutual 5-star ratings and written reviews (FR9)
│   ├── reports/            # Listing, user, review, and message reporting & auto-flagging (FR12)
│   ├── notifications/      # In-app event notifications, notification types (FR11)
│   └── audit/              # Read-only admin activity and document access logs (FR14, NFR 4.2)
```

#### Layered Responsibilities
- **`models.py`**: Clean database schemas with explicit constraints, field validations, and indexes. Keep business logic minimal.
- **`serializers.py`**: Validate incoming request payloads and serialize outgoing responses. Keep serializers focused on data translation.
- **`services.py` / `selectors.py`**: Encapsulate core business logic, complex database queries, atomic transactions, and transitions here.
- **`views.py` / `viewsets.py`**: Keep views thin. Views must only authenticate, check permissions, invoke services/selectors, and return standard HTTP responses.

---

### 7.2 Non-Negotiable BRB Domain Rules (SRS Compliance)

#### 1. PUP Webmail Domain Validation (FR1, NFR 4.2)
- Registrations are strictly restricted to PUP webmail addresses:
  - Students: `@iskolarngbayan.pup.edu.ph`
   - Note: `Alumni` is **not** a supported affiliation (DECISIONS.md D-15). The
     enum is exactly `Student`, `Faculty`, `Staff`. Do not add it back.
  - Faculty and Staff: `@pup.edu.ph`
- All other domains must be rejected with a user-friendly error message.

#### 2. Dual-Role Permission Checks (FR4, FR5, NFR 4.2)
- A single account can act as both **Borrower** and **Lender**.
- **Rule**: Never evaluate permissions based on which UI dashboard view is currently open on the client. Validate the user's granted permissions and resource ownership on **every** backend endpoint.

#### 3. Identity Verification Privacy (FR3, NFR 4.2)
- ID pictures and supporting documents submitted during verification are strictly confidential.
- Stored securely and encrypted at rest.
- **Accessible exclusively to Administrators**. Identity documents must never be served or exposed to Borrowers, Lenders, or unauthenticated users.
- Every administrative view or download of an identity document must automatically create an immutable entry in the audit log (`FR14`).

#### 4. Handover & Return Authentication Codes (FR8, NFR 4.4)
- **Handover**: Generated for Lender $\rightarrow$ Borrower enters code in app to set order to `Active`.
- **Return**: Generated for Borrower $\rightarrow$ Lender enters code in app to confirm return.
- **Security Rules**:
  - Exactly 6 numeric digits.
  - Single-use and strictly time-limited.
  - Rate-limit code entry attempts. Temporarily lock code entry after repeated failed attempts to prevent brute-forcing.
  - Log every code generation, validation attempt, and failure.

#### 5. Zero In-Platform Monetary Processing (FR8, Section 1.2)
- Payment for rented items is negotiated and exchanged strictly outside the platform.
- **Prohibition**: The backend must **never** store, process, or record credit card numbers, GCash account details, or bank credentials.

#### 6. Scheduled Background Jobs Security (Section 2.4 & 5.2)
- Order status transitions for **Overdue** and **Unreturned** items are triggered by scheduled webhooks (e.g., `cron-job.org`).
- **Security Rule**: The background endpoint (e.g., `POST /api/v1/jobs/check-overdue/`) must require a secret token in the `Authorization` header matching `CRON_SECRET_TOKEN`. Unauthenticated requests must be rejected with `401 Unauthorized`.

#### 7. Read-Only Administrator Audit Logs (FR14, NFR 4.2)
- All administrative actions—approving/rejecting IDs, banning users, removing listings, viewing ID files, configuring parameters, and resolving disputes—must be recorded in a read-only audit log table.
- Audit log records must never be editable or deletable via the API or Admin UI.

#### 8. Timezone and Datetime Handling
- All database timestamps must be stored in UTC (`USE_TZ = True`).
- Convert to local Philippine Standard Time (PST / UTC+8) only when formatting representations for end users if required.

#### 9. Information Disclosure & Security
- When querying private resources belonging to another user, return `404 Not Found` rather than `403 Forbidden` to avoid leaking the existence of sensitive IDs.

---

## 8. Writing Issues and SRS Traceability

Every piece of work must be tracked as an issue on GitHub and traced back to the [SWE 2 | Group 3 - CoPUP (BRB SRS) - Google Docs](https://docs.google.com/document/d/19IqMZtnkvHDsBknI9umnIGfUrbnB-FxTYbEhW-_3rWE/edit?tab=t.xb7tp8rsiwyr).

### 8.1 Issue Titles and Prefixes
- **User Story**: `[US-XX] <User capability>` (e.g., `[US-04] Lender confirms item return with authentication code`)
- **Bug Fix**: `[BUG-XX] <Clear failure description>` (e.g., `[BUG-12] Expired borrow requests do not release calendar dates`)
- **Technical Task**: `[TASK-XX] <Imperative task statement>` (e.g., `[TASK-08] Setup DRF throttle classes for code verification`)

### 8.2 Labeling System
Every issue must carry at least three labels:
1. **`type:`**: `type:feature`, `type:bug`, `type:task`, `type:docs`
2. **`area:`**: `area:auth`, `area:listings`, `area:orders`, `area:codes`, `area:admin`
3. **`priority:`**: `priority:high`, `priority:medium`, `priority:low`

### 8.3 Issue Template Structure
```markdown
### SRS Traceability
- **Requirement Reference**: FR8 (Order Scheduling and Confirmation Sequence)
- **Non-Functional Requirement**: NFR 4.4 (Reliability)

### Description
As a verified Lender, I want to enter the Borrower's return code so that the item is recorded as Returned and the transaction concludes.

### Acceptance Criteria
- [ ] **AC-8.1**: Given a return code, When entered by the assigned Lender, Then order status changes from Active to Returned.
- [ ] **AC-8.2**: Given an expired or invalid code, When entered, Then the system increments the failed attempt counter and returns 400 Bad Request.
- [ ] **AC-8.3**: Given 5 consecutive failed code attempts, When entered, Then code verification is locked for 15 minutes.
```

---

## 9. Definition of Ready and Done

### Definition of Ready (DoR)
A task is **Ready to Start** when:
- [ ] The issue is linked to a parent Epic / SRS Functional Requirement (`FR1` - `FR14`).
- [ ] Clear acceptance criteria (`AC-X.Y`) with Given-When-Then statements are documented.
- [ ] Any UI or API schema dependencies from other teams are clarified.
- [ ] No unresolved blocking issues (`status:blocked`).

### Definition of Done (DoD)
A task is **Done** when:
- [ ] Every acceptance criterion is covered by automated unit/integration tests referencing the AC ID.
- [ ] Code passes all `ruff check` (linting) and `ruff format` (formatting) quality checks.
- [ ] Migrations are generated, tested, and backward-compatible.
- [ ] All automated CI checks pass cleanly on the pull request.
- [ ] At least one backend peer has approved the PR.
- [ ] The pull request is squash-merged into `dev`, and the linked issue is closed automatically.

---

## 10. Troubleshooting

| Issue / Symptom | Possible Cause | Solution |
|---|---|---|
| `uv: command not found` | `uv` is not installed or not in system `PATH` | Install `uv` following [official docs](https://docs.astral.sh/uv/getting-started/installation/) or restart your terminal. |
| `File ... cannot be loaded because running scripts is disabled` (PowerShell) | Windows PowerShell Execution Policy restricts script execution | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` in PowerShell. |
| `django.db.utils.OperationalError: no such table` | Unapplied database migrations | Run `uv run python manage.py migrate`. |
| Port 8000 already in use | Another service is using port 8000 | Run on a different port: `uv run python manage.py runserver 8001`. |
| Emails are not arriving during testing | `EMAIL_BACKEND` is set to console backend | This is intentional for local testing. Look at the terminal running `runserver`—the verification link or reset token is printed directly to `stdout`. |
| Ruff flags unused import needed for Django registration | Import is required for module side effects (signals/models) but unused by name | Do not disable `F401` globally. Add an explicit inline exception: `# noqa: F401 - <explanation>`. |
| `ruff check --fix` changed code unexpectedly | Automated fixer applied an unwanted syntax change | Inspect `git diff`, revert unwanted modifications with `git restore <file>`, and resolve the lint issue manually. |
| Commit message rejected or flagged | Commit message does not follow Conventional Commits format | Reformat the message: `git commit -m "<type>(<scope>): <description>"`. |
| Migration conflicts on `dev` pull | Two branches created conflicting migrations | Run `uv run python manage.py makemigrations --merge` and commit the merge migration. |
| Tests pass locally but fail in CI | Missing dependencies, untracked migration files, or uncommitted changes | Run `uv sync --dev`, verify `git status`, and run `uv run python manage.py makemigrations --check`. |

---

## Need Further Help?
If you are blocked or have questions regarding architecture, database schemas, or SRS interpretation:
1. Check the [SWE 2 | Group 3 - CoPUP (BRB SRS) - Google Docs](https://docs.google.com/document/d/19IqMZtnkvHDsBknI9umnIGfUrbnB-FxTYbEhW-_3rWE/edit?tab=t.xb7tp8rsiwyr).
2. Comment directly on your issue or open a discussion thread in the team channel.
3. Tag the team lead or product owner for resolution.
