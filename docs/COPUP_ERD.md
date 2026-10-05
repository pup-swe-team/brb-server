# BRB (Borrow, Return, Borrow) — Entity Relationship Diagram

**Master ERD (draw.io, source of truth for table layout):** `[PASTE SHARED DRAW.IO LINK HERE]`

Decisions that affect how these tables should be implemented (lookup tables
vs `TextChoices`, the admin flag, auth strategy) are recorded in `DECISIONS.md`.

This document defines the full database schema for BRB, organized into 7 logical
domains. The Django project implements them across 10 apps — see the app list
at the bottom of "Notes for implementation (Django)".

## ⚠ Open TODOs (as of latest Master ERD review)

These apply to the **draw.io Master ERD** and should be fixed there first; this
`.md` reflects them as inline notes so OpenCode and anyone reading this file
sees them too. See the "What to change in draw.io" list at the very bottom of
this document for exact field-level edits.

1. ~~`users.affiliation` enum still includes `Admin`~~ — **fixed differently
   than originally proposed.** `Admin` was removed from the enum, but instead
   of adding an `is_admin` boolean, administrator authority is carried by
   Django's built-in `is_staff`. See DECISIONS.md D-03 for the reasoning.
   `users` now inherits `is_staff`, `is_superuser` and the rest of
   `AbstractUser`'s columns, which this simplified diagram omits. draw.io
   should drop both the `Admin` enum value and the `is_admin` field.
2. ~~`reviews` is missing `reviewee_id`~~ — **fixed.** `Review.reviewee` now
   exists (`related_name="received_reviews"`), added in
   `reviews/migrations/0003_review_reviewee.py` together with a
   `review_reviewer_not_reviewee` check constraint.
3. ~~`order_status_overrides` is missing `new_status`~~ — **fixed.**
   `OrderStatusOverride.new_status` added in
   `orders/migrations/0003_orderstatusoverride_new_status.py`, matching the
   `CharField` type of `previous_status`.
4. ~~`disputes.status` enum values not confirmed~~ — **fixed.** Confirmed as
   `open, resolved, escalated` and now enforced by `Dispute.StatusChoices`
   (`orders/migrations/0004_alter_dispute_status.py`).
5. `user_municipalities` / `user_provinces` — confirm with the team whether
   this level of address normalization is actually needed, since the SRS only
   asks for a single "home address" field. **Still open.** The tables exist in
   the schema today; nothing has been removed.
6. **Not previously tracked:** the ERD lists `student, alumni, faculty, staff`
   for `affiliation`, but `Alumni` has never been implemented in the code, and
   student and alumni share the same email domain so they cannot be inferred
   from it. Needs a team decision — see DECISIONS.md.

Each domain is written as a [Mermaid](https://mermaid.js.org/syntax/entityRelationshipDiagram.html)
`erDiagram` block. Fields that are fixed state machines (not Admin-editable
lists) are modeled either as plain string columns with their valid values noted
in a comment (Django `TextChoices`) or as their own lookup table — the rule for
which applies is recorded in DECISIONS.md D-02.

Tables referenced from another domain (e.g. `users` referenced from `listings`)
appear as a minimal stub (PK only) in that domain's diagram, with a note
pointing to the domain where the full table is defined.

---

## 1. Accounts / Identity Domain

Full owner of the `users` table. Every other domain references `users` as a stub.

```mermaid
erDiagram
    USERS {
        int id PK
        string full_name
        string email
        string password_hash
        string contact_number
        string affiliation "enum: student, faculty, staff — Admin removed; admin authority is is_staff (DECISIONS.md D-03). TODO: alumni still undecided"
        bool is_staff "inherited from AbstractUser — carries Administrator authority (FR3). Replaces the proposed is_admin."
        text bio
        string photo
        datetime email_verified_at
        string account_status "enum: active, suspended, pending_review, banned, deactivated"
        string lender_status "enum: none, active, revoked"
        datetime created_at
        string street_address
        string municipality
        string province
    }

    IDENTITY_DOCUMENTS {
        int id PK
        int user_id FK
        string document_type "enum: pup_id, government_id"
        string id_number
        string file_reference
        string status "enum: pending, approved, rejected"
        text rejection_reason
        int reviewed_by FK
        datetime reviewed_at
        datetime submitted_at
    }

    ADMIN_ACCESS_LOGS {
        int id PK
        int document_id FK
        int admin_id FK
        datetime accessed_at
    }

    SYSTEM_CONFIGS {
        string config_key PK
        string config_value
        int updated_by FK
        datetime created_at
    }

    USERS ||--o{ IDENTITY_DOCUMENTS : "submits (user_id)"
    USERS ||--o{ IDENTITY_DOCUMENTS : "reviews (reviewed_by)"
    IDENTITY_DOCUMENTS ||--o{ ADMIN_ACCESS_LOGS : "is viewed via"
    USERS ||--o{ ADMIN_ACCESS_LOGS : "views as admin"
    USERS ||--o{ SYSTEM_CONFIGS : "updates as admin"
```

---

## 2. Listings / Catalog Domain

> `USERS` here is a **stub** — full schema lives in Domain 1 (Accounts).

```mermaid
erDiagram
    USERS {
        int id PK
    }

    PICKUP_LOCATIONS {
        int id PK
        string name
        text description
        datetime deleted_at
    }

    LISTINGS {
        int id PK
        int lender_id FK
        string title
        text description
        string category
        string condition
        int pickup_location_id FK
        decimal rate_per_day "nullable, display-only"
        bool is_ownership_confirmed
        string status "enum: active, deactivated, deleted"
        datetime created_at
    }

    LISTING_PHOTOS {
        int id PK
        int listing_id FK
        string file_reference
        datetime uploaded_at
    }

    AVAILABILITY_WINDOWS {
        int id PK
        int listing_id FK
        date start_date
        date end_date
    }

    USERS ||--o{ LISTINGS : "owns (lender_id)"
    PICKUP_LOCATIONS ||--o{ LISTINGS : "is used by"
    LISTINGS ||--o{ LISTING_PHOTOS : has
    LISTINGS ||--o{ AVAILABILITY_WINDOWS : has
```

---

## 3. Orders / Transaction Domain

> `USERS` and `LISTINGS` here are **stubs** — full schemas live in Domains 1 and 2.
> This is the highest-risk, most state-dependent domain (FR8).

```mermaid
erDiagram
    USERS {
        int id PK
    }

    LISTINGS {
        int id PK
    }

    ORDERS {
        int id PK
        int listing_id FK
        int borrower_id FK
        date start_date
        date end_date
        string status "enum: requested, confirmed, active, overdue, unreturned, returned, disputed, completed, declined, expired, cancelled"
        text cancel_reason
        datetime created_at
        datetime updated_at
    }

    ORDER_STATUS_OVERRIDES {
        int id PK
        int order_id FK
        int admin_id FK
        string previous_status
        string new_status "added 2026-10-05, mirrors previous_status"
        text reason
        datetime overridden_at
    }

    AUTH_CODES {
        int id PK
        int order_id FK
        string code_type "enum: handover, return"
        string code_value
        datetime generated_at
        datetime expires_at
        datetime used_at
        string status "enum: active, used, expired"
    }

    AUTH_CODE_ATTEMPTS {
        int id PK
        int code_id FK
        int attempted_by FK
        bool was_successful
        datetime attempted_at
    }

    UNRETURNED_CASES {
        int id PK
        int order_id FK
        string status "enum: open, escalated, returned, unresolved"
        datetime escalated_at
        int escalated_by FK
        text resolution_notes
    }

    DISPUTES {
        int id PK
        int order_id FK
        int raised_by FK
        text description
        text borrower_response
        string status "enum: open, resolved, escalated"
        int resolved_by FK
        text resolution_notes
        datetime created_at
    }

    DISPUTE_EVIDENCES {
        int id PK
        int dispute_id FK
        int submitted_by FK
        string file_reference
        string file_type "enum: photo, video"
        datetime uploaded_at
    }

    LISTINGS ||--o{ ORDERS : "is ordered via"
    USERS ||--o{ ORDERS : "borrows as (borrower_id)"
    ORDERS ||--o{ ORDER_STATUS_OVERRIDES : "is corrected via"
    USERS ||--o{ ORDER_STATUS_OVERRIDES : "corrects as admin"
    ORDERS ||--o{ AUTH_CODES : "generates"
    AUTH_CODES ||--o{ AUTH_CODE_ATTEMPTS : "is attempted via"
    USERS ||--o{ AUTH_CODE_ATTEMPTS : "attempts as"
    ORDERS ||--o| UNRETURNED_CASES : "may open"
    USERS ||--o{ UNRETURNED_CASES : "escalates as admin"
    ORDERS ||--o| DISPUTES : "may open"
    USERS ||--o{ DISPUTES : "raises (raised_by)"
    USERS ||--o{ DISPUTES : "resolves as admin"
    DISPUTES ||--o{ DISPUTE_EVIDENCES : has
    USERS ||--o{ DISPUTE_EVIDENCES : submits
```

---

## 4. Chat Domain

> `USERS`, `LISTINGS`, `ORDERS` here are **stubs** — full schemas live in
> Domains 1, 2, and 3.

```mermaid
erDiagram
    USERS {
        int id PK
    }

    LISTINGS {
        int id PK
    }

    ORDERS {
        int id PK
    }

    CONVERSATIONS {
        int id PK
        int user_a_id FK
        int user_b_id FK
        int listing_id FK "nullable"
        int order_id FK "nullable"
        bool is_blocked
    }

    MESSAGES {
        int id PK
        int conversation_id FK
        int sender_id FK
        text content
        datetime sent_at
        datetime read_at
    }

    USERS ||--o{ CONVERSATIONS : "participates as (user_a_id)"
    USERS ||--o{ CONVERSATIONS : "participates as (user_b_id)"
    LISTINGS ||--o{ CONVERSATIONS : "may start from"
    ORDERS ||--o{ CONVERSATIONS : "may start from"
    CONVERSATIONS ||--o{ MESSAGES : contains
    USERS ||--o{ MESSAGES : sends
```

---

## 5. Reviews Domain

> `USERS`, `ORDERS` here are **stubs** — full schemas live in Domains 1 and 3.

```mermaid
erDiagram
    USERS {
        int id PK
    }

    ORDERS {
        int id PK
    }

    REVIEWS {
        int id PK
        int order_id FK
        int reviewer_id FK
        int reviewee_id FK
        int rating "1 to 5"
        text comment
        datetime created_at
        datetime edited_at
        datetime deleted_at
    }

    ORDERS ||--o{ REVIEWS : "generates (max 2)"
    USERS ||--o{ REVIEWS : "writes as (reviewer_id)"
    USERS ||--o{ REVIEWS : "receives as (reviewee_id)"
```

---

## 6. Reports / Moderation Domain

> `USERS`, `LISTINGS` here are **stubs**. `target_review_id` and
> `target_message_id` reference `REVIEWS` (Domain 5) and `MESSAGES` (Domain 4)
> respectively — add stub tables for those if rendering this diagram alone.

```mermaid
erDiagram
    USERS {
        int id PK
    }

    LISTINGS {
        int id PK
    }

    LISTING_REPORT_CATEGORIES {
        int id PK
        string name "prohibited, counterfeit, misleading_description, wrong_category, inappropriate_content"
    }

    LISTING_REPORTS {
        int id PK
        int reporter_id FK
        int target_listing_id FK
        int category_id FK
        text description
        string status "enum: open, resolved"
        datetime created_at
    }

    USER_REPORT_CATEGORIES {
        int id PK
        string name "scam_fraud, harassment, fake_account, spam, inappropriate_pfp"
    }

    USER_REPORTS {
        int id PK
        int reporter_id FK
        int target_user_id FK
        int category_id FK
        text description
        string status "enum: open, resolved"
        datetime created_at
    }

    REVIEW_REPORT_CATEGORIES {
        int id PK
        string name "fake_review, harassment, spam, offensive_content, irrelevant_review"
    }

    REVIEW_REPORTS {
        int id PK
        int reporter_id FK
        int target_review_id FK "references reviews.id in Domain 5"
        int category_id FK
        text description
        string status "enum: open, resolved"
        datetime created_at
    }

    MESSAGE_REPORT_CATEGORIES {
        int id PK
        string name "scam_fraud, harassment, spam, threats, inappropriate_content"
    }

    MESSAGE_REPORTS {
        int id PK
        int reporter_id FK
        int target_message_id FK "references messages.id in Domain 4"
        int category_id FK
        text description
        string status "enum: open, resolved"
        datetime created_at
    }

    USERS ||--o{ LISTING_REPORTS : files
    LISTINGS ||--o{ LISTING_REPORTS : "is target of"
    LISTING_REPORT_CATEGORIES ||--o{ LISTING_REPORTS : categorizes

    USERS ||--o{ USER_REPORTS : "files (reporter_id)"
    USERS ||--o{ USER_REPORTS : "is target of (target_user_id)"
    USER_REPORT_CATEGORIES ||--o{ USER_REPORTS : categorizes

    USERS ||--o{ REVIEW_REPORTS : files
    REVIEW_REPORT_CATEGORIES ||--o{ REVIEW_REPORTS : categorizes

    USERS ||--o{ MESSAGE_REPORTS : files
    MESSAGE_REPORT_CATEGORIES ||--o{ MESSAGE_REPORTS : categorizes
```

---

## 7. Notifications Domain

> `USERS` here is a **stub** — full schema lives in Domain 1.

```mermaid
erDiagram
    USERS {
        int id PK
    }

    NOTIFICATIONS {
        int id PK
        int user_id FK
        string type "enum matching FR11's event list: new_request, acceptance, decline, expiry, cancellation, code_generation, confirmed_handover, confirmed_return, upcoming_due_date, overdue_status, unreturned_status, new_message, new_review, verification_result, report_updates"
        int reference_id "nullable, links to related order/report/etc."
        bool is_read
        datetime created_at
    }

    USERS ||--o{ NOTIFICATIONS : receives
```

---

## Notes for implementation (Django)

- **Team decision (supersedes the earlier guidance in this file):** lookup
  tables are used for state-machine fields, matching what the code already
  implements. Concretely:
  - Fields drawn as their own table in the diagrams below (`order_statuses`,
    `listing_statuses`, `auth_code_types`, `auth_code_statuses`,
    `identity_document_types`, `identity_document_statuses`,
    `unreturned_cases_statuses`, `file_types`) are real Django models with
    `db_table` names as shown.
  - Fields drawn as an inline `"enum: ..."` string **on a model the platform
    also needs to seed or validate inline** — `users.affiliation`,
    `users.account_status`, `users.lender_status`, `disputes.status` — are
    Django `TextChoices` classes on the model.
  - `*_report_categories` tables are real tables, Admin-managed per FR14.
- This mirrors the code as of the `test/aaron-scratch` branch. If you change
  one side, change the other in the same PR — the diagrams and the models are
  expected to stay in sync.
- `users.affiliation` does **not** include "Admin" — `Admin` was removed from
  the enum and administrator authority is carried by `users.is_staff`
  (inherited from `AbstractUser`). See DECISIONS.md D-03.
- `users` also inherits the rest of `AbstractUser` — `is_superuser`,
  `is_active`, `last_login`, `date_joined`, `password` — plus the M2M tables
  `users_groups` and `users_user_permissions`. None are drawn above because
  this is a simplified diagram; they do exist in the database.
- `users.affiliation` does **not** include "Alumni" either, even though the
  original enum in this diagram listed it. Undecided — see DECISIONS.md.
- Stub tables (PK-only boxes) in Domains 2–7 exist only so each diagram
  renders independently; they are not separate tables in the actual database.
  The real, full-column table is defined once, in its home domain.
- The diagrams use **7 logical domains**, but the Django project splits them
  across **10 apps**: `core`, `users`, `listings`, `orders`, `codes`, `chat`,
  `reviews`, `reports`, `notifications`, `audit`. `core` holds
  `system_configs`, `codes` holds `auth_codes`/`auth_code_attempts`, and
  `audit` holds `admin_access_logs` — all three of which appear inside a
  logical domain in the diagrams above.

---

## What to change in the draw.io Master ERD

Exact field-level edits needed, in priority order. Items 2–4 have already been
applied to the Django models; they still need to be mirrored in draw.io so the
Master ERD stops disagreeing with the code.

1. **`users` table** — **done in code, but the draw.io change differs from what
   this document originally asked for.** Do the following:
   - Remove `Admin` from the `affiliation` enum bracket, leaving
     `[Student, Faculty, Staff]`.
   - Do **not** add an `is_admin` field. Administrator authority is
     `users.is_staff` (inherited from `AbstractUser`). See DECISIONS.md D-03
     for why a separate `is_admin` was rejected.
   - Still undecided: whether to add `Alumni` to the enum.

2. **`reviews` table** — **done in code.** `reviewee_id` (Int, FK →
   `users.id`) now exists directly after `reviewer_id`. Mirror it in draw.io.

3. **`order_status_overrides` table** — **done in code.** `new_status` exists
   immediately after `previous_status`, same type. Mirror it in draw.io.

4. **`disputes` table** — **done in code.** The `status` enum is confirmed as
   `[open, resolved, escalated]` and enforced by `Dispute.StatusChoices`.
   Mirror the confirmed bracket in draw.io.

5. **`user_municipalities` / `user_provinces`** (team decision, not a fix)
   - If the team decides this level of detail isn't needed, remove both
     tables and the `municipality`/`province` FK fields on `users`, replacing
     them with the plain string fields already present
     (`street_address`, `municipality`, `province` as free text) — the SRS
     only specifies a single "home address," no cascading dropdowns.
   - If keeping it, no change needed, just confirm it's intentional.

Once these are fixed in draw.io, paste the diagram's shareable link at the
top of this document (replacing `[PASTE SHARED DRAW.IO LINK HERE]`) so this
`.md` and the Master ERD stay cross-referenced for OpenCode and the rest of
the team.
