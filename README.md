# 🏋️ FitCore — Gym Management System

A full-stack, role-based web application for managing gym operations: memberships, attendance, member payments, trainers, workouts, diet plans, progress tracking, lockers, equipment, messaging, bulk imports, notifications, and analytics.

Public registration is a **gym-owner onboarding flow**: it creates an `OWNER` account, carries the selected annual plan through signup, records a simulated plan checkout, and gates the application until checkout is complete. This owner-plan checkout is a demo flow and does not contact a payment gateway. Member dues use the separate eSewa/Khalti sandbox payment system.

## 🌐 Live Deployment

The production FitCore application is deployed on Render:

| Resource | URL |
|----------|-----|
| **Application** | **[https://fitcore-k5zr.onrender.com](https://fitcore-k5zr.onrender.com)** |
| API base | `https://fitcore-k5zr.onrender.com/api` |
| Health check | `https://fitcore-k5zr.onrender.com/api/health/` |
| Django admin | `https://fitcore-k5zr.onrender.com/admin/` |

The frontend and API are served from the same HTTPS origin. The health endpoint returns `200` when the application and PostgreSQL database are healthy.

![Stack](https://img.shields.io/badge/Django-5.2-092E20?style=flat-square&logo=django)
![Stack](https://img.shields.io/badge/DRF-3.15-A93C2D?style=flat-square)
![Stack](https://img.shields.io/badge/PostgreSQL-14-4169E1?style=flat-square&logo=postgresql)
![Stack](https://img.shields.io/badge/JWT-SimpleJWT-green?style=flat-square)
![Stack](https://img.shields.io/badge/Allauth-65.7-blue?style=flat-square)
![Stack](https://img.shields.io/badge/Social%20Auth-Google%20%2F%20Facebook-4285F4?style=flat-square)

---

## Table of Contents

- [Live Deployment](#-live-deployment)
- [Quick Start](#-quick-start)
- [Project Architecture](#-project-architecture)
- [Environment Variables](#-environment-variables)
- [User Guide](#-user-guide)
  - [Owner Onboarding](#owner-onboarding)
  - [Multi-gym tenancy](#multi-gym-tenancy)
  - [Roles & Permissions](#roles--permissions)
  - [Frontend Pages](#frontend-pages)
  - [Common Workflows](#common-workflows)
- [Developer Guide](#-developer-guide)
  - [Tech Stack](#tech-stack)
  - [App Module Reference](#app-module-reference)
  - [Database Schema](#database-schema-key-relationships)
  - [API Reference](#-api-reference)
  - [Authentication](#authentication)
  - [Rate Limiting](#rate-limiting)
  - [Dark Mode](#dark-mode)
  - [Notifications System](#notifications-system)
  - [Realtime Messaging (WebSockets)](#realtime-messaging-websockets)
  - [Scheduled Tasks](#scheduled-tasks)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Frontend Architecture](#frontend-architecture)
- [Troubleshooting](#-troubleshooting)

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- A static HTTP server for local frontend development (for example, VS Code Live Server)

### 1. Clone & set up

```bash
git clone <repo-url>
cd gym_management

# Create virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure environment

Copy the documented template (`.env.example` lists every variable) or create
a `.env` file in the project root:

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

DB_NAME=gym_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Browser origins used when the frontend runs separately from Django
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5500
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:5500

# Email (console backend in dev)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend

# Public frontend URL (password-reset and OAuth redirects)
FRONTEND_URL=http://127.0.0.1:5500

# Local rollout compatibility (Render enables both)
TENANCY_REQUIRE_MEMBERSHIP=False
REQUIRE_OWNER_SUBSCRIPTION=False

# Social login (optional)
# GOOGLE_CLIENT_ID=your-google-client-id
# GOOGLE_CLIENT_SECRET=your-google-client-secret
# FACEBOOK_APP_ID=your-facebook-app-id
# FACEBOOK_APP_SECRET=your-facebook-app-secret

# Member-dues gateways (sandbox; not used by the simulated owner-plan checkout)
# KHALTI_SECRET_KEY=
# ESEWA_MERCHANT_CODE=EPAYTEST
# ESEWA_SECRET_KEY=8gBm/:&EnhH.1/q
```

### 3. Create database & migrate

```sql
-- In PostgreSQL:
CREATE DATABASE gym_db;
```

```bash
python manage.py migrate
```

### 4. Prepare django-allauth and the optional Django admin

```bash
python manage.py ensure_site --domain localhost:5500 --name FitCore

# Optional: creates an ADMIN account for /admin/, not an application OWNER.
python manage.py createsuperuser
```

Application owners are created through the public signup flow at `signup.html`; the registration API always assigns the `OWNER` role server-side.

### 5. Run the Django backend

```bash
python manage.py runserver
```

### 6. Open the frontend

For local development, serve `frontend/` on port `5500` (for example, with VS Code Live Server) and open:

```
http://127.0.0.1:5500/
```

`api.js` uses `http://<current-host>:8000/api` for the separately served local frontend. In production, WhiteNoise serves `frontend/` and Django from the same origin, so the API base is `/api`.

| Local URL | Purpose |
|-----------|---------|
| `http://127.0.0.1:5500/` | Static FitCore frontend |
| `http://127.0.0.1:8000/` | Django backend service-information JSON |
| `http://127.0.0.1:8000/api/` | Django REST API |
| `http://127.0.0.1:8000/api/health/` | Backend/database health check |

When `DEBUG=True`, WhiteNoise root serving is disabled and `/` returns backend service metadata, so port `8000` never duplicates the frontend on port `5500`.

---

## 🏗️ Project Architecture

```
gym_management/          # Django project settings & URLs
├── apps/                # 16 local Django apps
│   ├── accounts/        # User, JWT auth, RBAC, owner-plan subscriptions
│   ├── gyms/            # Gyms, memberships, branches, invitations, audit
│   ├── members/         # Member profiles and fitness goals
│   ├── memberships/     # Plans, subscriptions, offers, promo codes
│   ├── attendance/      # Check-in/out, QR and biometric enrollment
│   ├── payments/        # Member dues, eSewa/Khalti, PDF receipts
│   ├── staff/           # Staff profiles and leave requests
│   ├── trainers/        # Trainer profiles and member assignments
│   ├── workouts/        # Exercises, templates, assignments, messaging
│   ├── diet/            # Diet plans, meals, daily logs
│   ├── progress/        # Body metrics and personal records
│   ├── lockers/         # Locker inventory and assignments
│   ├── equipment/       # Equipment inventory and maintenance
│   ├── notifications/   # Alerts, group messages, pinned conversations
│   ├── reports/         # Analytics and CSV/Excel exports
│   └── dataimport/      # Owner-only Excel import preview/commit
├── frontend/            # 47 static HTML pages plus CSS/JS assets, PWA manifest and service worker
│   ├── css/             # theme, landing, and authentication styles
│   └── js/              # shared API client, validation, mobile navigation
├── templates/           # Django/allauth and notification email templates
├── scripts/             # Windows Task Scheduler helpers
├── static/              # Project static assets
├── staticfiles/         # collectstatic output
├── logs/                # Rotating application logs
├── render.yaml          # Render blueprint (web service + PostgreSQL)
└── manage.py
```

### Design Principles

- **One app per domain**: Each Django app owns its models, serializers, views, and URLs
- **Role-Based Access Control (RBAC)**: API permissions are enforced server-side; frontend guards are only a usability layer
- **Gym-scoped tenancy**: every operational record carries a `gym` (and, where applicable, `branch`) boundary; authenticated JWTs select an active `GymMembership` and the request-local tenant manager prevents cross-gym queries
- **Versioned JWT authentication**: Access/refresh rotation plus a `token_version` claim invalidates existing sessions after password changes
- **Frontend-agnostic API**: The REST API can serve the bundled web client or another client
- **Single-origin production**: WhiteNoise serves the static frontend and Django serves `/api` from one host
- **Dark by default**: CSS custom properties support dark and light themes, with the preference persisted locally

---

## 🔧 Environment Variables

| Variable | Required | Default / recommended | Description |
|----------|----------|-----------------------|-------------|
| `SECRET_KEY` | ✅ | — | Django signing key; generate a unique production value |
| `DEBUG` | ❌ | `False` | Enables Django debug mode |
| `ALLOWED_HOSTS` | Production | `fitcore-k5zr.onrender.com` | Comma-separated host allowlist |
| `RENDER_EXTERNAL_HOSTNAME` | Render only | Provided by Render | Public Render hostname; auto-added to host/CSRF allowlists |
| `DB_NAME` | Production | `gym_db` | PostgreSQL database name |
| `DB_USER` | Production | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | Production | `postgres` | PostgreSQL password |
| `DB_HOST` | Production | `localhost` | PostgreSQL host |
| `DB_PORT` | Production | `5432` | PostgreSQL port |
| `CORS_ALLOWED_ORIGINS` | ❌ | Local origins built in | Extra comma-separated browser origins for a split frontend |
| `CSRF_TRUSTED_ORIGINS` | Production | `https://fitcore-k5zr.onrender.com` | Comma-separated full origins used by Django CSRF checks |
| `FRONTEND_URL` | Production | `https://fitcore-k5zr.onrender.com` | Public frontend URL for reset emails and OAuth redirects |
| `TENANCY_REQUIRE_MEMBERSHIP` | Production | `False` locally / `True` on Render | Reject API requests without an active gym membership |
| `REQUIRE_OWNER_SUBSCRIPTION` | Production | `False` locally / `True` on Render | Enforce the paid owner-plan gate on management APIs, not only in JavaScript |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | ❌ | `5242880` | Maximum non-file request body size (5 MiB) |
| `FILE_UPLOAD_MAX_MEMORY_SIZE` | ❌ | `5242880` | In-memory file upload threshold (5 MiB) |
| `EMAIL_BACKEND` | ❌ | Auto: SMTP when credentials are set, otherwise console | Django email transport; an explicit value wins over the automatic choice |
| `EMAIL_HOST` | SMTP | `smtp.gmail.com` | SMTP host |
| `EMAIL_PORT` | SMTP | `587` | SMTP port |
| `EMAIL_HOST_USER` | SMTP | — | SMTP username; setting it **together with** `EMAIL_HOST_PASSWORD` switches the backend to SMTP automatically |
| `EMAIL_HOST_PASSWORD` | SMTP | — | SMTP password (Gmail: app password); pairs with `EMAIL_HOST_USER` to enable SMTP |
| `EMAIL_USE_TLS` | SMTP | `True` | Enables STARTTLS |
| `EMAIL_TIMEOUT` | ❌ | `15` | Seconds before an unresponsive SMTP server gives up |
| `DEFAULT_FROM_EMAIL` | ❌ | `Gym Management <noreply@gym.local>` | Sender address |
| `TRUST_X_FORWARDED_PROTO` | Production proxy | `False` | Trust the platform's HTTPS forwarding header |
| `SESSION_COOKIE_SECURE` | Production | `False` | Send session cookies over HTTPS only |
| `CSRF_COOKIE_SECURE` | Production | `False` | Send CSRF cookies over HTTPS only |
| `SECURE_SSL_REDIRECT` | Production | `False` | Redirect HTTP requests to HTTPS; enable after health checks are green |
| `SECURE_HSTS_SECONDS` | ❌ | `0` | HSTS duration in seconds |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | ❌ | `False` | Add HSTS to subdomains |
| `SECURE_HSTS_PRELOAD` | ❌ | `False` | Opt into HSTS preload |
| `SECURE_CONTENT_TYPE_NOSNIFF` | ❌ | `True` | Prevent MIME-type sniffing |
| `KHALTI_SECRET_KEY` | Member dues | — | Khalti sandbox/merchant secret |
| `KHALTI_BASE_URL` | ❌ | `https://dev.khalti.com/api/v2` | Khalti API base |
| `KHALTI_WEBHOOK_URL` | Production dues | — | Public Khalti webhook URL |
| `ESEWA_MERCHANT_CODE` | Member dues | `EPAYTEST` | eSewa sandbox/merchant code |
| `ESEWA_SECRET_KEY` | Member dues | `8gBm/:&EnhH.1/q` | Published eSewa sandbox secret |
| `ESEWA_BASE_URL` | ❌ | eSewa sandbox form URL | eSewa checkout endpoint |
| `ESEWA_STATUS_CHECK_URL` | ❌ | eSewa sandbox status URL | Server-side eSewa verification endpoint |
| `GOOGLE_CLIENT_ID` | Social login | — | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Social login | — | Google OAuth client secret |
| `FACEBOOK_APP_ID` | Social login | — | Facebook OAuth app ID |
| `FACEBOOK_APP_SECRET` | Social login | — | Facebook OAuth app secret |
| `VAPID_PUBLIC_KEY` | Web Push | `manage.py generate_vapid_keys` | VAPID public key handed to browsers when they subscribe to push |
| `VAPID_PRIVATE_KEY` | Web Push | Same command (keep secret!) | VAPID private key used to sign outgoing Web Push requests |
| `VAPID_SUBJECT` | Web Push | `mailto:you@example.com` | Contact mailbox or URL the push protocol requires |

> The owner-plan prices in `payment.html` are fixed demo values in `apps.accounts.views.SubscribeView`. Gateway variables above apply only to member dues under `/api/payments/`.

---

## 👤 User Guide

### Owner Onboarding

FitCore's public signup is for gym owners. Members, reception staff, and trainers are created later from authenticated management pages.

| Plan | Annual price | Checkout code |
|------|-------------:|---------------|
| Starter | NPR 4,999 | `starter` |
| Gold | NPR 9,999 | `gold` |
| Platinum | NPR 19,999 | `platinum` |

The onboarding flow is:

1. `getting-started.html` sends the selected plan to `signup.html?plan=<code>` and stores it temporarily in `localStorage`.
2. `POST /api/auth/register/` creates an `OWNER`, ignores any caller-supplied role, and immediately returns JWT access and refresh tokens.
3. `signup.html` stores the session and opens `payment.html` with the selected plan.
4. `payment.html` lets the owner choose eSewa, Khalti, or card for the demo and submits only `plan` and `method` to `POST /api/auth/subscribe/`.
5. Django validates the choices, derives the annual price server-side, creates a paid `PlanSubscription`, and returns a `TXN-...` reference.
6. The owner enters `dashboard.html`. Until a subscription exists, `GET /api/auth/subscription/` returns `{"has_plan": false}` and `api.js` redirects app pages back to checkout.

`payment.html` is intentionally a **simulated checkout**: no card data is collected and no gateway is contacted. Its prices live in `SubscribeView.PLAN_PRICES`; the browser copy is display-only. The stored record has no automatic renewal billing or expiry enforcement. This is separate from the sandbox eSewa/Khalti integration used for actual member dues.

### Multi-gym tenancy

The API now treats a `Gym` as the tenant boundary. Public owner registration provisions a gym, an owner membership, and a primary branch atomically. Existing installations are assigned a legacy gym and branch by migration; operational records are backfilled before the new constraints are enabled.

- `GymMembership` stores the role (`OWNER`, `STAFF`, `TRAINER`, or `MEMBER`) per gym. A user may belong to more than one gym and switch with `POST /api/gyms/switch/`.
- `Branch` and `BranchMembership` provide physical-location access. Non-owner requests may use `X-Branch-ID`; the branch must be granted to the membership.
- Tenant-owned operational models use a request-local manager and a `gym`/`branch` boundary. Gym-wide records with a null branch remain visible to each granted branch.
- Invitations are one-time and hashed at rest. Existing users must confirm their current password when accepting an invitation; accepting never silently resets an account password.
- Owner impersonation requires a reason, is limited to 15 minutes, records actor/subject/session metadata, and is rejected after the session ends. The owner must also have an active subscription when production enforcement is enabled.
- `AuditLog` records membership, branch, invitation, subscription, and impersonation lifecycle events.

Useful headers are `X-Gym-ID` (validated active membership) and `X-Branch-ID` (validated branch access). The frontend stores the active IDs and `switchGym()` in `frontend/js/api.js` rotates the JWT for the selected gym.

### Roles & Permissions

| Role | Can Do | Cannot Do |
|------|--------|-----------|
| **Owner** | Full gym administration, reports/imports, staff and trainer management, plan configuration | — |
| **Staff / Receptionist** | Manage day-to-day members, attendance, payments, memberships, offers, freezes, and trainer profiles | View owner reports/imports; the bundled staff navigation hides workout/diet builders and owner settings |
| **Trainer** | View assigned members, create workout/diet plans and meals, review attendance, message assigned members | Manage payments, staff, reports, or other trainers' members |
| **Member** | View/edit own profile, membership, progress, workouts and diet; log meals/workouts; check in/out; pay own dues; message permitted staff/trainers | Access management data or see other members' private records |
| **Admin** | Developer/Django-admin role; not a normal gym workflow role | Does not inherit application-owner permissions |

### Frontend Pages

#### Public / Authentication Pages
| Page | URL | Purpose |
|------|-----|---------|
| Landing | `index.html` | Marketing page, feature overview, and pricing entry point |
| Pricing | `getting-started.html` | Compare Starter, Gold, and Platinum annual plans |
| Login | `login.html` | Email/password JWT login and optional social login |
| Sign Up | `signup.html` | Create a gym-owner account and preserve the selected plan |
| Accept invitation | `accept-invitation.html` | Accept a one-time gym invitation and set up the account |
| Checkout | `payment.html` | Simulated annual owner-plan checkout (normally authenticated) |
| Forgot Password | `forgot-password.html` | Request a password-reset email |
| Reset Password | `reset-password.html` | Set a new password with a one-time token |

#### Member Pages
| Page | URL | Purpose |
|------|-----|---------|
| My Attendance | `my-attendance.html` | Check-in history, QR code scanning |
| My Diet | `my-diet.html` | Assigned diet plan, daily meal logging |
| My Workouts | `my-workouts.html` | Assigned workout plan, completion logging |
| My Progress | `my-progress.html` | Body metrics over time, personal records |
| My Memberships | `my-memberships.html` | Current plan, renewal, freeze request |
| My Payments | `my-payments.html` | Payment history, receipts |
| My Locker | `my-locker.html` | Locker assignment status |
| My Trainer | `my-trainer.html` | Assigned trainer info |
| Notifications | `notifications.html` | In-app notification center |
| Notification Detail | `notification-detail.html` | Single-notification detail view (bell, list, and push deep link) |
| Member Card | `member-card.html` | QR code for check-in |
| My Messages | `my-messages.html` | Direct messaging with staff/trainers |

#### Owner / Staff / Trainer Pages
| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | `dashboard.html` | Role-aware KPIs, charts, and quick actions |
| Members | `members.html` | Member list, search, and account creation |
| Member Detail | `member-detail.html` | Individual member drill-down, incl. the missed-meal adherence monitor in the Diet Plan panel |
| Attendance | `attendance.html` | Manual and QR check-in/out management |
| Attendance Devices | `attendance-devices.html` | Biometric enrollment and verification stats |
| Memberships | `memberships.html` | Gym membership plans, assignments, renewals, and freezes |
| Offers | `offers.html` | Percentage/fixed discounts and promo codes |
| Payments | `payments.html` | Member-dues collection, history, filters, and receipts |
| Staff | `staff.html` | Staff profiles and leave management |
| Staff Detail | `staff-detail.html` | Individual staff profile |
| Trainers | `trainers.html` | Trainer profiles and availability |
| Trainer Assignments | `trainer-assignments.html` | Assign members to trainers |
| Workouts | `workouts.html` | Exercise library and template builder |
| Workout Detail | `workout-template-detail.html` | Template days, exercises, versions, and review actions |
| Diet | `diet.html` | Diet-plan builder |
| Meals | `meals.html` | Meal library and plan assignment |
| Progress | `progress.html` | Progress entries and personal records |
| Lockers | `lockers.html` | Locker inventory and assignments |
| Equipment | `equipment.html` | Equipment inventory and maintenance |
| Reports | `reports.html` | Owner analytics and CSV/Excel exports |
| Import | `import.html` | Owner-only `.xlsx` / `.csv` import: template download, dry run, commit |
| Messages | `messages.html` | Direct and group messaging |
| Notifications | `notifications.html` | Notification center and read state |
| Notification Detail | `notification-detail.html` | Single-notification detail view (bell, list, and push deep link) |
| Trainer Dashboard | `trainer-dashboard.html` | Assigned-member overview |
| Trainer Members | `trainer-members.html` | Trainer-scoped member list |
| Trainer Messages | `trainer-messages.html` | Trainer conversation view |

### Common Workflows

#### Adding a New Member
1. An authenticated Owner or Staff member opens `members.html` and creates the member account/profile.
2. Staff assigns a gym membership plan in `memberships.html`.
3. Payment is collected in `payments.html`, or the member pays their own dues through `my-payments.html`.
4. Owner/Staff optionally assign a trainer in `trainer-assignments.html`.
5. The member signs in with the credentials issued for that account. Public `signup.html` is reserved for owner onboarding.

#### Member Check-In
1. A member can use their QR code, a kiosk/shared QR flow, an enrolled biometric ID, or a staff member's manual action.
2. QR and biometric scan endpoints validate the token/device reference before creating the daily attendance record.
3. The member can also use the authenticated self-service check-in/check-out endpoints; the record includes check-in, check-out, and duration.

#### Workout Assignment Flow
1. Trainer creates a **Workout Template** with days and exercises
2. Template submitted for review → Owner/Staff approves
3. Trainer **assigns the template** to a member
4. Member sees the assigned workout in `my-workouts.html`
5. Member logs completion after each session

#### Freeze Membership
1. Member submits a **freeze request** via `my-memberships.html`
2. Staff/Owner reviews the request in the memberships page
3. On approval, membership is frozen and end-date is extended on unfreeze

#### Diet Plan Assignment
1. Trainer creates a **Diet Plan** with meals and macros
2. Plan is assigned to a specific member
3. Member sees the plan in `my-diet.html` and logs daily meals

#### Member Dues and Online Payment
1. A member opens `my-payments.html`; the frontend requests `GET /api/payments/my-dues/`.
2. The member chooses a due and a method. The server recomputes the amount from the referenced membership or locker and never trusts a client-supplied amount.
3. Khalti/eSewa payments are verified server-side against the gateway and stored with a unique receipt number.
4. Paid records can be downloaded as PDF receipts. Payment lists support server-side filtering and pagination.

#### Social Login (Google/Facebook)
1. User clicks "Google" or "Facebook" button on `login.html` or `signup.html`
2. Browser redirects to provider's OAuth consent screen
3. User authorizes the app on Google/Facebook
4. Provider redirects back to `/api/auth/<provider>/callback/`
5. django-allauth creates/links the social account to a FitCore user
6. User is redirected to `FRONTEND_URL` with JWT tokens
7. Frontend stores tokens and routes to the appropriate dashboard

The password-based `/api/auth/register/` endpoint is the owner-onboarding path. OAuth provisioning is separate and should only be enabled with the intended role policy for social accounts.

---

## 🛠️ Developer Guide

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.2.16, Django REST Framework 3.15.2 |
| Database | PostgreSQL 14+ (`psycopg2`) |
| Auth | SimpleJWT access/refresh rotation, token blacklist/versioning, django-allauth + dj-rest-auth |
| Frontend | Vanilla HTML/CSS/JavaScript; Bootstrap 5 and Bootstrap Icons via CDN |
| Production serving | daphne (ASGI: HTTP + WebSocket) + WhiteNoise; same-origin frontend/API |
| Payments | Simulated owner-plan checkout; eSewa/Khalti sandbox for member dues |
| Imports/exports | `openpyxl` workbooks, CSV, ReportLab PDF receipts |
| QR / images | `qrcode`, Pillow |
| Testing | Django test runner, pytest/pytest-django compatible |

### App Module Reference

#### `accounts` — Authentication, Users & Owner Plans
- **Models**: `User`, `RoleSequence`, `PlanSubscription`, `PasswordResetToken`
- **Key features**: owner-only public registration, JWT rotation/versioning, password reset, profile management, plan checkout/status, Google/Facebook OAuth
- **Roles**: `OWNER`, `STAFF`, `TRAINER`, `MEMBER`, and developer-only `ADMIN`
- **Permissions**: single-role, owner/staff, staff-role, member, object-owner, and read-only member variants

#### `gyms` — Multi-gym Tenancy & Security
- **Models**: `Gym`, `GymMembership`, `Branch`, `BranchMembership`, `Invitation`, `ImpersonationSession`, `AuditLog`
- **Key features**: tenant provisioning, per-gym roles, branch access, gym switching, hashed invitations, audited time-bound impersonation, owner subscription enforcement

#### `members` — Member Profiles
- **Model**: `MemberProfile` (one profile per user per gym)
- **Key features**: profile management, deactivation/reactivation, fitness goals, BMI, emergency contacts, template UI routes

#### `memberships` — Gym Memberships & Discounts
- **Models**: `MembershipPlan`, `Membership`, `FreezeRequest`, `Offer`, `PromoCode`, `PromoCodeUsage`
- **Key features**: assignment/renewal/cancellation, freeze workflow, auto-unfreeze support, percentage/fixed offers, promo redemption audit trail

#### `attendance` — Check-In/Out
- **Models**: `Attendance`, `QRAttendanceToken`, `BiometricRecord`
- **Key features**: one record per user/date, self-service check-in/out, QR/kiosk flows, biometric reference enrollment and verification, duration calculation

#### `payments` — Member Dues & Gateways
- **Model**: `Payment`
- **Key features**: server-calculated member dues, unique receipts, discounts, PDF receipts, eSewa/Khalti initiation and verification, Khalti webhook reconciliation

#### `staff` — Staff Operations
- **Models**: `StaffProfile`, `LeaveRequest`
- **Key features**: staff CRUD, role/compensation fields, document upload, password reset, leave review/cancellation, expired-leave cleanup

#### `trainers` — Trainer Operations
- **Models**: `TrainerProfile`, `TrainerMemberAssignment`
- **Key features**: specialties/certifications, availability, member assignment, trainer-scoped member lists

#### `workouts` — Workouts & Messaging
- **Models**: `Exercise`, `WorkoutTemplate`, `WorkoutDay`, `WorkoutDayExercise`, `WorkoutAssignment`, `WorkoutTemplateVersion`, `WorkoutCompletionLog`
- **Key features**: template builder, review/archive/clone/restore, assignment lifecycle, completion logs/export, direct and group messaging

#### `diet` — Nutrition Plans
- **Models**: `DietPlan`, `Meal`, `MealLog`
- **Key features**: macro targets, meal assignment, daily intake logging, daily/weekly summaries

#### `progress` — Body Metrics & PRs
- **Models**: `ProgressEntry`, `PersonalRecord`
- **Key features**: BMI, body measurements, exercise records, trend/stat summaries

#### `lockers` — Locker Inventory
- **Models**: `Locker`, `LockerAssignment`
- **Key features**: inventory/fees, bulk creation, assignment lifecycle, member read-only access

#### `equipment` — Equipment & Maintenance
- **Models**: `Equipment`, `MaintenanceRecord`
- **Key features**: inventory/photos, condition tracking, scheduled/completed maintenance, cost and due-date reporting

#### `notifications` — Alerts & Group Messaging
- **Models**: `Notification`, `MessageGroup`, `GroupMessage`, `PinnedConversation`
- **Key features**: typed alerts, read state, email helpers, direct/group chat, pins, scheduled reminder commands

#### `reports` — Analytics & Export
- **No models** (queries across the operational apps)
- **Key features**: owner-only revenue, membership, attendance, equipment, locker, staff, and retention reports; CSV/Excel exports

#### `dataimport` — Bulk Excel Import
- **No models**
- **Key features**: owner-only schema discovery, downloadable `.xlsx` / per-sheet `.csv` templates, dry-run validation, bounded multipart upload, transactional commit

---

### Database Schema (Key Relationships)

```text
User ──1:1──> MemberProfile / StaffProfile / TrainerProfile
User ──1:N──> PlanSubscription / PasswordResetToken
User ──1:N──> Membership ──N:1──> MembershipPlan
MembershipPlan <──M:N──> Offer (specific plans); Offer ──1:N──> PromoCode
Membership ──1:N──> FreezeRequest / Payment
User ──1:N──> Attendance / ProgressEntry / Notification
User ──1:1──> QRAttendanceToken / BiometricRecord
User ──N:1──> TrainerMemberAssignment ──N:1──> User (member)
User ──1:N──> WorkoutAssignment ──N:1──> WorkoutTemplate
WorkoutTemplate ──1:N──> WorkoutDay ──1:N──> WorkoutDayExercise ──N:1──> Exercise
WorkoutAssignment ──1:N──> WorkoutCompletionLog
DietPlan ──1:N──> Meal; User ──1:N──> MealLog
User ──1:N──> PersonalRecord ──N:1──> Exercise
User ──1:N──> LockerAssignment ──N:1──> Locker
User ──1:N──> MessageGroup; MessageGroup ──1:N──> GroupMessage
```

---

## 📡 API Reference

### Base URL

```text
Local backend:  http://127.0.0.1:8000/api
Production API: https://fitcore-k5zr.onrender.com/api
```

### Authentication

All endpoints require JWT authentication unless marked as public.

**Login:**
```http
POST /api/auth/login/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "yourpassword"
}

Response:
{
  "access": "eyJ...",
  "refresh": "eyJ...",
  "user": { ... }
}
```

**Use the access token in subsequent requests:**
```
Authorization: Bearer <access_token>
```

**Refresh an expired access token:**
```http
POST /api/auth/token/refresh/
{ "refresh": "<refresh_token>" }
```

**Owner registration and demo checkout:**

```http
POST /api/auth/register/
Content-Type: application/json

{
  "first_name": "Gym",
  "last_name": "Owner",
  "email": "owner@example.com",
  "password": "StrongPassword123!",
  "password2": "StrongPassword123!"
}
```

The response contains `message`, `user`, and `tokens: { access, refresh }`. The user is always `OWNER`; a submitted `role` is not part of the serializer. Then use the returned access token:

```http
POST /api/auth/subscribe/
Authorization: Bearer <access_token>
Content-Type: application/json

{ "plan": "gold", "method": "khalti" }
```

`plan` accepts `starter|gold|platinum`; `method` accepts `esewa|khalti|card`. The response includes the server-derived `price`, `status`, and unique `reference`. This endpoint records a demo subscription only and does not charge a gateway.

### Endpoint Summary

In the tables below, **staff-side** follows the application's `IsAnyStaffRole` policy and includes Owner, Staff, Trainer, and Admin. Rows that say **Owner/Staff** are narrower. Authenticated tenant requests may include `X-Gym-ID` and `X-Branch-ID`; both are checked against active `GymMembership`/`BranchMembership` records rather than trusted as raw IDs.

#### Health (`/api/health/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/health/` | ❌ | API health check (DB connectivity) |

#### Auth (`/api/auth/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/register/` | ❌ | Register a gym `OWNER`; returns nested access/refresh tokens |
| POST | `/subscribe/` | ✅ | Record a simulated owner-plan purchase; server enforces price |
| GET | `/subscription/` | ✅ | Return the caller's latest plan subscription or `has_plan: false` |
| POST | `/login/` | ❌ | Get JWT tokens |
| POST | `/token/refresh/` | ❌ | Refresh access token |
| POST | `/logout/` | ✅ | Blacklist refresh token |
| GET | `/me/` | ✅ | Get own profile |
| PATCH | `/me/` | ✅ | Update own profile |
| PUT/PATCH | `/change-password/` | ✅ | Change password; invalidates existing sessions |
| POST | `/forgot-password/` | ❌ | Request reset email |
| POST | `/reset-password/` | ❌ | Reset password with token |
| GET | `/google/login/` | ❌ | Google OAuth login (redirect) |
| GET | `/google/callback/` | ❌ | Google OAuth callback |
| GET | `/facebook/login/` | ❌ | Facebook OAuth login (redirect) |
| GET | `/facebook/callback/` | ❌ | Facebook OAuth callback |
| GET | `/3rdparty/login/` | ❌ | List available social providers |
| POST | `/3rdparty/login/` | ❌ | Social account login (allauth) |
| POST | `/3rdparty/login/callback/` | ❌ | Social account callback (allauth) |

#### Gym tenancy (`/api/gyms/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | ✅ | List gyms available to the current user |
| GET | `/current/` | ✅ | Return the active gym from the JWT/header context |
| POST | `/switch/` | ✅ | Issue a JWT pair for another active gym membership |
| GET/POST | `/<gym_id>/memberships/` | Owner/Staff | List or create gym memberships |
| PATCH | `/<gym_id>/memberships/<membership_id>/` | Owner/Staff | Change role, status, or branch access |
| GET/POST | `/<gym_id>/branches/` | Owner/Staff | List or create branches (create is Owner-only) |
| POST | `/<gym_id>/invitations/` | Owner/Staff | Create a one-time invitation; response contains its accept URL |
| POST | `/invitations/accept/` | ❌ | Accept an invitation (existing users confirm their password) |
| POST | `/<gym_id>/impersonate/` | Owner | Start a 15-minute audited impersonation session |
| POST | `/impersonations/<session_id>/end/` | Participant | End an impersonation session |
| GET | `/<gym_id>/audit/` | Owner | List recent tenant audit events |

#### Members (`/api/members/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | Owner/Staff/Trainer | List member accounts/profiles |
| POST | `/` | Owner/Staff | Create a member account/profile |
| GET/PATCH | `/me/` | Member | Retrieve/update the current member profile |
| GET/PUT/PATCH/DELETE | `/<id>/` | Role-scoped | Retrieve, update, or deactivate a member |
| GET | `/<id>/profile-detail/` | Role-scoped | Member profile details |
| POST | `/<id>/reactivate/` | Owner/Staff | Reactivate a member |
| GET | `/ui/`, `/ui/add/`, `/ui/<id>/`, `/ui/<id>/edit/` | Owner/Staff | Django template member screens |

#### Memberships (`/api/memberships/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/plans/` | ✅ | List membership plans |
| POST | `/plans/` | Owner/Staff | Create plan |
| GET/PUT/PATCH/DELETE | `/plans/<id>/` | Authenticated / Owner-Staff write | Plan detail (DELETE = deactivate) |
| GET | `/` | ✅ | List memberships |
| POST | `/` | ✅ | Assign membership |
| GET | `/<id>/` | ✅ | Membership detail |
| PATCH | `/<id>/` | Owner/Staff | Update membership |
| DELETE | `/<id>/` | Owner/Staff | Cancel membership |
| POST | `/<id>/freeze/` | Owner/Staff | Freeze membership |
| POST | `/<id>/unfreeze/` | Owner/Staff | Unfreeze (extends end date) |
| POST | `/<id>/renew/` | ✅ | Renew membership |
| GET | `/expiring/?days=7` | Owner/Staff/Trainer | Expiring soon |
| GET/POST | `/freeze-requests/` | ✅ | List/create freeze requests |
| POST | `/freeze-requests/<id>/approve/` | Owner/Staff | Approve freeze request |
| POST | `/freeze-requests/<id>/reject/` | Owner/Staff | Reject freeze request |

#### Attendance (`/api/attendance/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/records/` | Authenticated / staff-side write | Role-scoped attendance list or manual record |
| GET/PATCH/DELETE | `/records/<id>/` | Role-scoped | Record detail; members may only update their own check-out |
| POST | `/records/check-in/` | Member | Self check-in for today |
| POST | `/records/check-out/` | Member | Self check-out for today |
| GET | `/records/current-occupancy/` | Authenticated | Members currently checked in |
| GET | `/checkin-qr/` | Staff-side | Shared entrance/kiosk QR |
| GET | `/qr/my/`, `/qr/<member_id>/` | Authenticated / staff for another member | Attendance QR images/data |
| POST | `/qr/scan/` | Public kiosk token validation | Scan an attendance token and check in/out |
| GET/POST | `/biometric/` | Staff-side | List or enroll biometric references |
| GET/PATCH/DELETE | `/biometric/<id>/` | Staff-side | Manage an enrollment |
| POST | `/biometric/scan/` | Public device token validation | Verify a device/biometric reference |
| GET | `/biometric/stats/` | Staff-side | Biometric verification statistics |
| GET | `/member-profile/<id>/` | Public | Limited QR profile returned to a scanner |

#### Payments (`/api/payments/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/` | Authenticated / staff-side write | Paginated, role-scoped history or staff-recorded payment |
| GET/PATCH/DELETE | `/<id>/` | Authenticated / staff-side write | Payment detail or staff-managed update |
| GET | `/my-dues/` | Member | Server-calculated membership/locker balances |
| POST | `/pay/` | Member | Start payment for a selected due; amount is server-derived |
| POST | `/verify-khalti/`, `/verify-esewa/` | Member | Verify gateway return against the stored transaction and amount |
| POST | `/retry-khalti/`, `/retry-esewa/` | Member | Retry a pending gateway payment |
| GET | `/<id>/receipt/` | Owner/Staff/Trainer or owning member | Download a PDF receipt for a paid payment |
| GET | `/summary/` | Owner/Staff | Totals by status and payment method |
| POST | `/khalti-webhook/` | Public gateway callback | Look up the transaction with Khalti; the webhook body is not trusted as proof |

#### Workouts & Messaging (`/api/workouts/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/exercises/` | Authenticated / Owner-Staff-Trainer write | Exercise library |
| GET/PATCH/DELETE | `/exercises/<id>/` | Authenticated / scoped write | Exercise detail |
| GET/POST | `/templates/` | Authenticated / Owner-Staff-Trainer write | Workout templates |
| GET/PATCH/DELETE | `/templates/<id>/` | Authenticated / scoped write | Template detail |
| POST | `/templates/<id>/submit-review/`, `/approve/`, `/archive/`, `/duplicate/` | Role-scoped | Template review/lifecycle actions |
| GET | `/templates/<id>/versions/` | Owner/Staff/Trainer | Version history |
| POST | `/templates/<id>/versions/<version_id>/restore/` | Owner/Staff/Trainer | Restore a template version |
| GET/POST/PATCH/DELETE | `/days/`, `/days/<id>/`, `/day-exercises/` | Owner/Staff/Trainer | Template builder resources |
| GET/POST/PATCH/DELETE | `/assignments/`, `/assignments/<id>/` | Authenticated / Owner-Staff-Trainer write | Workout assignments |
| POST | `/assignments/<id>/pause/`, `/resume/`, `/cancel/` | Owning member | Member assignment lifecycle |
| GET/POST | `/completion-logs/` | Authenticated / assignment-scoped | Workout completion history |
| GET | `/export-csv/` | Authenticated / assignment-scoped | Completion-log CSV export |
| GET/POST | `/messages/direct/`, `/message-groups/` | Authenticated | Direct/group message lists and creation |
| POST | `/message-trainer/` | Member | Send a message to the assigned trainer |
| GET | `/trainer-messages/` | Authenticated / role-scoped | Trainer conversation inbox |
| POST | `/trainer-reply/` | Owner/Staff/Trainer | Reply to a member conversation |

#### Diet (`/api/diet/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/diet-plans/` | Authenticated / Owner-Staff-Trainer write | Role-scoped diet plans |
| GET/PATCH/DELETE | `/diet-plans/<id>/` | Role-scoped | Plan detail and lifecycle |
| GET | `/diet-plans/stats/` | Authenticated | Diet-plan statistics |
| GET/POST | `/meals/` | Owner/Staff/Trainer | Meals; filter with `?diet_plan=<id>` |
| GET/POST/PATCH/DELETE | `/meal-logs/` | Authenticated / own-record write | Daily meal logs |
| GET | `/meal-logs/daily-summary/` | Authenticated | Calorie and macro summary |
| GET | `/meal-logs/weekly-summary/` | Authenticated | Seven-day meal summary |
| GET/POST | `/meal-checklist/today/` | Member | Today's personal meal checklist (self-only) |
| GET | `/meal-checklist/` | Role-scoped | Checklist history; `?member=<id>`, `?date=` |
| GET | `/meal-checklist/adherence/` | Owner/Staff/Trainer/self | Missed-meal monitor: per-day planned vs. completed over `?days=` (1–60, default 14) for `?member=<id>` |

#### Progress (`/api/progress/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/entries/` | ✅ | Body metric entries |
| GET/PUT/PATCH/DELETE | `/entries/<id>/` | ✅ | Entry detail |
| GET/POST | `/personal-records/` | ✅ | Personal records |
| GET/PUT/PATCH/DELETE | `/personal-records/<id>/` | ✅ | PR detail |
| GET | `/member-stats/` | Member | Aggregated stats dashboard |

#### Reports (`/api/reports/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/overview/` | Owner | KPI dashboard |
| GET | `/revenue/` | Owner | Revenue analytics |
| GET | `/memberships/` | Owner | Membership analytics |
| GET | `/attendance/` | Owner | Attendance analytics |
| GET | `/equipment/` | Owner | Equipment analytics |
| GET | `/lockers/` | Owner | Locker analytics |
| GET | `/staff/` | Owner | Staff analytics |
| GET | `/retention/` | Owner | Member retention analytics (cohort-based) |
| GET | `/export/attendance/` | Owner | Export attendance CSV/Excel |
| GET | `/export/memberships/` | Owner | Export memberships CSV/Excel |
| GET | `/export/revenue/` | Owner | Export revenue CSV/Excel |
| GET | `/export/members/` | Owner | Export members CSV/Excel |
| GET | `/export/equipment/` | Owner | Export equipment CSV/Excel |
| GET | `/export/maintenance/` | Owner | Export maintenance CSV/Excel |
| GET | `/export/diet/` | Owner | Export diet plans CSV/Excel |
| GET | `/export/progress/` | Owner | Export progress CSV/Excel |
| GET | `/export/staff/` | Owner | Export staff CSV/Excel |

**Export query parameters:**
- `?export_format=excel` — returns `.xlsx` (default: CSV)
- `?start=YYYY-MM-DD&end=YYYY-MM-DD` — date range (attendance, revenue)
- `?status=ACTIVE` — filter by status (memberships)
- `?is_active=true` — filter active only (diet)
- `?member=<id>` — filter by member (progress)

#### Notifications (`/api/notifications/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | Authenticated | Current user's notifications |
| POST | `/` | Owner/Staff | Send a notification to one or more recipients |
| GET | `/unread-count/` | Authenticated | Current unread count |
| POST | `/mark-all-read/` | Authenticated | Mark all visible notifications as read |
| PATCH | `/<id>/read/` | Authenticated / own notification | Mark one notification as read |
| GET | `/<id>/` | Authenticated / own notification | Fetch one notification (backs the detail page) |
| DELETE | `/<id>/` | Owner/Staff or owning recipient | Delete a notification |

**WebSocket (realtime, not REST):** `WS /ws/messages/?token=<JWT access token>`
— server-pushed `message.new` events for open chat tabs (see
[Realtime Messaging](#realtime-messaging-websockets)). Send paths stay plain
HTTPS POST; only delivery back to the recipient is live.

#### Offers & Promo Codes (`/api/memberships/offers/`, `/api/memberships/promo-codes/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/offers/` | Owner/Staff | List all offers |
| POST | `/offers/` | Owner/Staff | Create offer |
| GET/PUT/PATCH/DELETE | `/offers/<id>/` | Owner/Staff | Offer detail |
| POST | `/offers/validate/` | Authenticated | Validate a promo code and calculate the discounted price |
| GET | `/promo-codes/` | Owner/Staff | List all promo codes |
| POST | `/promo-codes/` | Owner/Staff | Create promo code |
| GET/PUT/PATCH/DELETE | `/promo-codes/<id>/` | Owner/Staff | Promo code detail |
| GET | `/promo-code-usages/` | Owner/Staff | List promo code usage records |

#### Trainers (`/api/trainers/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/profiles/` | Owner/Staff read; Owner write | Trainer profiles and availability |
| GET/PATCH/DELETE | `/profiles/<id>/` | Owner/Staff read; Owner write | Trainer profile detail |
| GET/POST | `/assignments/` | Owner/Staff | Trainer/member assignment management |
| GET/PATCH/DELETE | `/assignments/<id>/` | Role-scoped | Assignment detail/lifecycle |
| GET | `/my-members/` | Trainer | Members assigned to the current trainer |

#### Staff (`/api/staff/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/profiles/` | Owner/Staff | Staff profile list/creation |
| GET/PATCH/DELETE | `/profiles/<id>/` | Owner/Staff | Staff profile detail/lifecycle |
| POST | `/profiles/<id>/activate/`, `/deactivate/`, `/reset-password/` | Owner/Staff | Account lifecycle and credential reset |
| GET/POST | `/leave-requests/` | Staff-side | Leave request list/submission |
| GET/PATCH/DELETE | `/leave-requests/<id>/` | Role-scoped | Leave request detail/lifecycle |
| POST | `/leave-requests/<id>/review/` | Owner/Staff | Approve or reject with a status payload |
| POST | `/leave-requests/<id>/cancel/` | Owning requester | Cancel a pending request |

#### Lockers (`/api/lockers/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/lockers/` | Owner/Staff | Locker inventory |
| POST | `/lockers/bulk-create/` | Owner/Staff | Generate up to 200 numbered lockers from a prefix/range |
| GET/PATCH/DELETE | `/lockers/<id>/` | Owner/Staff | Locker detail/status |
| GET/POST | `/assignments/` | Owner/Staff write; member read | Locker assignments |
| GET/PATCH/DELETE | `/assignments/<id>/` | Owner/Staff write; member read | Assignment lifecycle |

#### Equipment (`/api/equipment/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/equipment/` | Owner/Staff | Equipment inventory |
| GET/PATCH/DELETE | `/equipment/<id>/` | Owner/Staff | Equipment detail/lifecycle |
| GET/POST | `/maintenance/` | Owner/Staff | Maintenance records |
| GET/PATCH/DELETE | `/maintenance/<id>/` | Owner/Staff | Maintenance detail/lifecycle |

#### Data Import (`/api/import/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | Owner | Supported workbook sheets, columns, and limits |
| GET | `/template/` | Owner | Download `fitcore_import_template.xlsx`, or `?sheet=<key>` for that sheet as `.csv` |
| POST | `/` | Owner | Multipart `.xlsx` / `.csv` (CSVs also send `sheet=<key>`) dry run (`dry_run=true`) or commit (`false`) |

---

### Authentication

**JWT Flow:**
1. Login → receive `access` (60 min) + `refresh` (7 days) tokens
2. Use the access token in `Authorization: Bearer <token>`
3. When access expires, POST the refresh token to `/api/auth/token/refresh/`
4. Refresh tokens rotate on use and the previous token is blacklisted
5. Logout blacklists the supplied refresh token
6. Password changes/resets bump `token_version` and blacklist outstanding refresh tokens, so old access/refresh sessions stop authenticating immediately

**Rate Limits on Auth:**
- Login: 10 requests/hour per IP
- Register: 10 requests/hour per IP
- Password reset: 10 requests/hour per IP

**Social Login (Google & Facebook):**
1. Click "Google" or "Facebook" button on login/signup page
2. Redirected to provider's OAuth consent screen
3. After authorization, redirected back to callback URL
4. django-allauth creates/links the social account
5. User receives JWT tokens and is logged in

**Setup:**
1. Create OAuth credentials in [Google Cloud Console](https://console.cloud.google.com/) or [Facebook Developers](https://developers.facebook.com/)
2. Register the applicable redirect URIs:
   - Local: `http://localhost:8000/api/auth/<provider>/callback/`
   - Production: `https://fitcore-k5zr.onrender.com/api/auth/<provider>/callback/`

   The custom adapters use `localhost` for local HTTP OAuth; Render uses the HTTPS production origin above.
3. Add client ID and secret to `.env` file

---

### Rate Limiting

| Scope | Rate | Applied To |
|-------|------|------------|
| Anonymous | 200/hour | All unauthenticated requests |
| Authenticated | 2000/hour | All authenticated requests |
| Auth endpoints | 10/hour | Login, register, forgot/reset password |
| Membership writes | 30/min | Freeze, unfreeze, and renew operations |

DRF includes rate metadata when a scope is active:
```http
Retry-After: 3600
X-RateLimit-Limit: 200
X-RateLimit-Remaining: 195
X-RateLimit-Reset: 1693500000
```

When rate limited, the API returns HTTP `429`:
```json
{
  "detail": "Request was throttled. Expected available in 1234 seconds."
}
```

---

### Dark Mode

The frontend supports light/dark mode with a toggle button in the topbar and defaults to dark for a new browser.

**Implementation:**
- Light tokens are defined on `:root` in `theme.css`
- Dark tokens/component overrides use `html:not([data-theme="light"])`
- `api.js` applies the saved `theme` immediately and injects the toggle into the topbar
- The preference is persisted in `localStorage`

**To extend either theme:**
1. Add shared variables to `:root` in `theme.css`
2. Override only the values that differ under `html:not([data-theme="light"])`
3. Use semantic variables such as `var(--bg-card)` and `var(--text-primary)` rather than hard-coded colors
4. Test both themes and the persisted preference

---

### Notifications System

**Automated/event-driven notifications include:**
- Membership renewal reminders (3 days before expiry) and expiry notices
- Auto-unfreeze notices when a frozen period ends
- Pending/partial payment reminders
- Paid-payment receipts and gateway confirmations
- Member inactivity alerts (14+ days without a check-in)
- Workout reminders (active assignment with no completion for 3+ days)
- Trainer assignment, workout-plan, and diet-plan events
- Welcome/announcement helpers and direct/group chat events

**Delivery and storage:**
- In-app records are exposed through `/api/notifications/`; every notification has a detail page (`notification-detail.html?id=<id>`) opened by tapping a bell/list row or the push notification itself, and reading it there is what marks it read
- Notification services can also send email through Django's configured backend
- Stored types include membership expiry/renewal, payment due/received, inactivity, workout reminder, general, announcement, member message, trainer reply, and trainer assigned
- Direct/group conversation read state and pins are managed by the messaging endpoints

---

### Realtime Messaging (WebSockets)

Messages reach the targeted user **live** — two delivery layers, both fired
from the send path inside `transaction.on_commit` (a rolled-back send never
wakes anyone):

| Layer | Reaches | Mechanism |
|-------|---------|-----------|
| WebSocket | every open browser tab of the recipient | Django Channels consumer at `WS /ws/messages/` |
| Web Push | the app when it's closed | `pywebpush` through `notifications.services.send_push` |

**How it fits together:**

- **Send stays HTTPS.** `POST /api/workouts/messages/direct/`, `.../message-trainer/`
  and `POST /api/workouts/message-groups/<id>/messages/` create the rows, then
  `_send_notification()` / `MessageGroupSendView` call
  `services.send_push()` + `services.broadcast_to_user()` after commit.
- **`broadcast_to_user(user_id, payload)`** fans a `message.new` event out to
  the `ws_user_<id>` channel-layer group. If the recipient has a live tab, the
  `group_send` is scheduled **on that tab's event loop**
  (`asyncio.run_coroutine_threadsafe`) — a blind cross-thread put would resolve
  the waiter future without waking a loop parked in `select()`, delaying
  delivery until some unrelated timer or socket activity.
- **The consumer** (`apps/notifications/consumers.py`) authenticates at
  handshake time from `?token=<JWT>` (refused with close code 4401 when
  missing/expired), joins `ws_user_<id>`, and only ever pushes server →
  client (`connected`, `message.new`, `pong`). A ping every 30 s doubles as
  Render free-tier inbound traffic so an open chat keeps the instance awake;
  no server traffic for 90 s triggers a client reconnect.
- **The client** (`frontend/js/realtime.js`) is loaded explicitly by
  `messages.html`, `my-messages.html` and `trainer-messages.html` (and lazily
  by `api.js` everywhere else for the bell badge). On `message.new` it calls
  the page's own `loadMessages()` (open conversation included) and
  `loadTopbarNotifications()`. While the socket is down and the tab is
  visible it polls every 8 s, so updates are slower but never silent.
- **Channel layer:** `InMemoryChannelLayer` (no Redis) — correct for the
  single-process daphne deployment on Render's free plan; switch to
  `RedisChannelLayer` if the service ever scales past one worker/instance.
  The ASGI entrypoint is `gym_management.asgi.py` (HTTP → Django,
  WebSocket → `AllowedHostsOriginValidator` → consumer), served by **daphne**
  in production and by `manage.py runserver` in development (Channels
  auto-switches runserver to ASGI once `channels` is in `INSTALLED_APPS`).

---

### Scheduled Tasks

Run the operational commands from an external scheduler (Render Cron, cron, or Windows Task Scheduler):

| Command | Purpose | Suggested cadence |
|---------|---------|-------------------|
| `python manage.py send_reminders` | Auto-unfreeze memberships; renewal/expiry, due-payment, inactivity, and workout reminders | Daily |
| `python manage.py send_scheduled_notifications` | Alternate 7/3/1-day expiry schedule, overdue-payment alerts, and inactivity notifications; supports `--dry-run` | Daily, if used |
| `python manage.py expire_stale_khalti_payments` | Reconcile pending Khalti transactions older than 30 minutes; supports `--minutes` and `--dry-run` | Every 15–30 min |
| `python manage.py auto_reject_expired_leaves` | Reject pending leave requests whose end date passed; supports `--dry-run` | Daily |
| `python manage.py backup_db` | Create a timestamped PostgreSQL dump; `--compress` is available | Per retention policy |

Choose one notification schedule if both reminder commands would create overlapping alerts.

**Windows (Task Scheduler):**
```powershell
# Import the included daily reminder definition:
schtasks /create /xml "scripts\GymDailyReminders.xml" /tn "GymDailyReminders"

# Manual run:
schtasks /run /tn "GymDailyReminders"
```

**Linux (cron):**
```cron
0 8 * * * cd /path/to/gym && venv/bin/python manage.py send_reminders >> logs/reminders.log 2>&1
*/30 * * * * cd /path/to/gym && venv/bin/python manage.py expire_stale_khalti_payments >> logs/khalti-reconcile.log 2>&1
```

---

## 🧪 Testing

### Run All Tests

```bash
python manage.py test
```

### Run Specific App Tests

```bash
python manage.py test apps.accounts.tests     # 62 tests
python manage.py test apps.memberships.tests  # 71 tests
python manage.py test apps.workouts.tests     # 72 tests
python manage.py test apps.reports.tests      # 60 tests
```

### Test Coverage Summary

| App | Tests | Main coverage |
|-----|------:|---------------|
| **accounts** | 62 | Owner-only registration, server-priced checkout/status, JWT rotation/versioning, password/reset/session security, display IDs |
| **attendance** | 57 | Manual/self attendance, QR flows, biometric enrollment/scanning/stats, role scoping |
| **dataimport** | 36 | Workbook schema, template, CSV+XLSX import (validate/dry-run/commit), validation, owner-only access |
| **diet** | 50 | Plans, meals, meal logs, daily/weekly summaries, meal checklist + adherence monitor, filtering, RBAC |
| **equipment** | 21 | Inventory and maintenance CRUD/validation/RBAC |
| **gyms** | 53 | Tenant provisioning, custom roles and permission resolution, trash/restore |
| **lockers** | 46 | Inventory, bulk creation, assignment lifecycle, status synchronization, filters |
| **members** | 44 | Profile CRUD, reactivation, own-profile access, validation |
| **memberships** | 71 | Plans, assignment/renewal/cancel, freeze workflows, offers/promo codes, expiry sync, filters |
| **notifications** | 90 | Notification types/read state/detail endpoint, scheduled services/commands, push payloads, model-level push parity hook + delivery test endpoint, group messaging and pins, WebSocket consumer (token handshake, keepalive, live fan-out) |
| **payments** | 32 | Staff recording, member scoping, discounts, partial self-service payments, summaries and access control |
| **progress** | 33 | Progress/PR CRUD, BMI, member stats, trainer/member scoping |
| **reports** | 60 | JSON analytics plus CSV/Excel content, filters, empty datasets, and RBAC |
| **staff** | 73 | Staff profiles/actions, shift templates and weekly schedules, roster, password reset, leave lifecycle/review/date rules |
| **trainers** | 34 | Trainer profiles, assignments, trainer-scoped members and notifications |
| **workouts** | 72 | Exercise/template/version workflows, assignments/completions, messaging (incl. live push + WebSocket delivery on commit), exports, RBAC |

**Total: 834 tests across 16 local apps.** Latest full run: **834 passed**, with Django system checks clean.

### Test Patterns Used

- `APITestCase` from DRF for API endpoint testing
- JWT token authentication via `RefreshToken.for_user()`
- CSV parsing with `csv.reader` for content validation
- Excel parsing with `openpyxl.load_workbook()` for .xlsx validation; CSV tables are sniffed (encoding + delimiter) and fed through the same pipeline as a one-tab workbook
- Role-based test coverage (Owner, Staff, Trainer, Member, public kiosk/gateway callbacks)
- Versioned-JWT and password/session invalidation tests
- Server-authoritative price/amount and owner-plan tamper-resistance tests

---

## 🚀 Deployment

### Current Production Deployment

FitCore is currently deployed at **https://fitcore-k5zr.onrender.com**. The checked-in `render.yaml` configures this hostname for `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and `FRONTEND_URL`; settings also reads Render's `RENDER_EXTERNAL_HOSTNAME` automatically.

Production requests use:

```text
Frontend:  https://fitcore-k5zr.onrender.com
API:       https://fitcore-k5zr.onrender.com/api
Health:    https://fitcore-k5zr.onrender.com/api/health/
Admin:     https://fitcore-k5zr.onrender.com/admin/
```

### Production Checklist

1. Set `DEBUG=False` and generate a unique `SECRET_KEY`.
2. Configure PostgreSQL through `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`.
3. Set `ALLOWED_HOSTS=fitcore-k5zr.onrender.com`, `CSRF_TRUSTED_ORIGINS=https://fitcore-k5zr.onrender.com`, and `FRONTEND_URL=https://fitcore-k5zr.onrender.com`.
4. Run `python manage.py migrate --noinput` during deployment.
5. Run `python manage.py collectstatic --noinput`; WhiteNoise serves `frontend/` and collected static assets.
6. Bind daphne (the ASGI server — HTTP + WebSocket) to the platform-assigned port (`-b 0.0.0.0 -p $PORT` on Render).
7. Configure email: set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` (the sender must be the same mailbox as `EMAIL_HOST_USER`, or Gmail will rewrite it) in Render's environment — the backend flips to SMTP automatically as soon as both credentials are present; leave them unset to print emails to the logs instead. Verify with a password-reset email.
8. Use production Khalti/eSewa credentials for member dues; the owner-plan checkout remains simulated.
9. Schedule reminders, Khalti reconciliation, database backups, and log monitoring.
10. Configure persistent storage for `media/`; without a Render disk, uploaded files are ephemeral.
11. Create the allauth site if it is missing: `python manage.py ensure_site --domain fitcore-k5zr.onrender.com --name FitCore`; update an existing `Site(id=1)` in Django admin when its domain changes.
12. Keep `logs/` and any database backups outside the deployed source tree when possible.

### Redeploy to Render with the Included Blueprint

The current service at `fitcore-k5zr.onrender.com` was created from `render.yaml`. The blueprint provisions one Python web service and one PostgreSQL database in the same region (Singapore). The frontend and API share one origin, so production does not require split-origin CORS.

1. Push the repository to the GitHub/GitLab repository connected to the existing Render service.
2. Normal deployments run from the connected branch's auto-deploy configuration. For a first-time setup only, choose **New → Blueprint** and apply `render.yaml`.
3. Render maps the managed database connection into the app's `DB_*` variables.
4. The build runs `pip install -r requirements.txt && python manage.py collectstatic --noinput`.
5. Startup runs migrations, then `daphne -b 0.0.0.0 -p $PORT gym_management.asgi:application` (ASGI — the WebSocket realtime endpoint needs it; gunicorn is WSGI-only).
6. Render health-checks `/api/health/`, which also verifies database connectivity.

The blueprint currently uses free plans. Free web services sleep after inactivity, and the free database is time-limited. If Render changes the generated service hostname, update `FRONTEND_URL`; `settings.py` automatically appends `RENDER_EXTERNAL_HOSTNAME` to host and CSRF allowlists.

### Generic ASGI Deployment

```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
daphne -b 0.0.0.0 -p $PORT gym_management.asgi:application
```

daphne serves HTTP and WebSockets from the same process (the realtime
messaging endpoint `/ws/messages/` requires ASGI). Gunicorn stays pinned in
`requirements.txt` as a WSGI-only fallback for setups that don't need
WebSockets: `gunicorn gym_management.wsgi:application --bind 0.0.0.0:$PORT`.

There is no committed Dockerfile. The deployment path currently provided by the repository is the Render blueprint plus daphne/WhiteNoise.

---

## 🖥️ Frontend Architecture

### File Structure

```text
frontend/
├── css/
│   ├── theme.css        # Shared design tokens/components, dark/light themes
│   ├── landing.css      # Landing and pricing pages
│   └── login.css        # Login, signup, and checkout pages
├── js/
│   ├── api.js           # API/auth client, role guards, owner-plan gate, router, shared UI
│   ├── pwa.js           # Service-worker registration (included by every page)
│   └── validate.js      # Shared form validation
├── icons/               # Generated PWA icons (scripts/generate_pwa_icons.py)
├── *.html               # 47 page files
├── logo.png             # Application logo
├── manifest.webmanifest # Web app manifest (install metadata)
├── offline.html         # Offline fallback page served by the service worker
└── sw.js                # Service worker (offline/caching strategy)
```

### Progressive Web App (PWA)

FitCore is installable as a PWA (Add to Home Screen / install icon) and shows an
offline fallback page when the network is unavailable. Live data always requires
a connection — API responses are deliberately never cached.

**Session persistence:** tokens live in `localStorage` and survive app
relaunches. The installed icon launches the landing page (`start_url "./"`), so
`index.html` and `login.html` redirect already-signed-in users straight into
their dashboard (trainers to `trainer-dashboard.html`) — reopening the app can
never *look* like a logout while the session is still valid.

| File | Purpose |
|------|---------|
| `manifest.webmanifest` | Install metadata: name, icons, standalone display, dark theme colour, page shortcuts |
| `sw.js` | Service worker: precaches the shell, decides the caching strategy per request type |
| `offline.html` | Self-contained offline fallback page (no external assets) |
| `js/pwa.js` | Registers `sw.js`; injected into the `<head>` of every page; also provides the install UI (`window.FitCorePWA`) |
| `icons/` | 192/512 icons, a maskable 512 icon, and a 180px `apple-touch-icon` |

**Caching policy (`sw.js`):**

| Request type | Strategy |
|--------------|----------|
| Page navigations | Network-first; offline falls back to a cached copy of the landing page, then `offline.html` |
| Same-origin CSS/JS/images | Stale-while-revalidate (served from cache instantly, refreshed in the background) |
| `/api/*` | Strict network-only, **never cached** (JWT-protected, user-specific; returns `503` JSON offline) |
| Cross-origin CDN/fonts | Stale-while-revalidate so the shell renders offline after the first visit |

**Installing the app:**

`js/pwa.js` exposes `window.FitCorePWA` and injects the install entry points
itself, so no page markup carries them:

| Surface | Behaviour |
|---------|-----------|
| Floating **Install app** pill (logged-out public pages only) | The dedicated pre-login install entry point. Always shown while the app is not installed, on every platform, without waiting for Chrome to report installability — so the app can be (re-)installed at any time, including after the user uninstalled it. Deliberately hidden after login (checked via `#profilePanel` and `access_token`) so no floating button sits over the app. The `×` hides it for the current session only (`sessionStorage`); it returns on the next visit. A `display-mode` listener re-shows the entry point if the app is uninstalled. |
| **Install app** item in the profile menu (app pages) | The install entry point after login — always available from any logged-in page, so the app can be installed or reinstalled without leaving the app. |
| Android / desktop Chrome | Installs directly on click through the native install dialog (`beforeinstallprompt`). If the browser hasn't reported installability yet, the click waits up to 2s for the event (Chrome fires it late, and re-fires it after a dismissed dialog) before falling back to the manual steps — which only browsers without the install API ever reach |
| iOS Safari / any iOS browser (no install event exists) | Click opens the step-by-step instructions immediately: **Share → Add to Home Screen → Add** (iOS 16.4+ also enables push in the installed PWA) |

**Web Push notifications:**

Every in-app notification is also delivered as a Web Push to the recipient's
subscribed devices (installed PWAs and browsers that allowed notifications).
Push is best-effort: the in-app `Notification` row is always created first,
push failures are only logged (a push can never break the calling code), and
subscriptions a push service reports as dead (HTTP 404/410) are deleted
automatically.

| Piece | Purpose |
|-------|---------|
| `manage.py generate_vapid_keys` | Generates the VAPID keypair; paste the output into `.env` and Render's env vars |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | Identify this server to the browser push services (see Environment Variables) |
| `apps.notifications.models.PushSubscription` | One row per browser endpoint; a user may have several devices |
| `GET /api/notifications/push/public-key/` | Hands the VAPID public key to the browser |
| `POST /api/notifications/push/subscribe/` | Registers the browser's subscription for the logged-in user (upserts by endpoint — a new login on the same browser reassigns it) |
| `POST /api/notifications/push/unsubscribe/` | Removes it (called on logout) |
| `apps.notifications.services.send_push()` | Sends from the central `notify()` after the DB transaction commits |
| `sw.js` `push` / `notificationclick` handlers | Shows the notification and opens `notification-detail.html?id=<id>` — that exact notification's page — when tapped (falls back to opening a new window if the browser refuses in-place navigation) |

**User flow:** after a successful login (or signup) the browser asks for
notification permission inside the click gesture — iOS only accepts the prompt
there, and iOS 16.4+ requires the PWA on the Home Screen (which this PWA
satisfies). The prompt appears at most once per browser; a dismissed prompt is
never repeated. Every subsequent authenticated page load silently re-registers
the subscription (repairs endpoints the browser rotates), and it re-syncs
whenever the app returns to the foreground (Android suspends backgrounded PWAs,
and push endpoints can rotate while suspended). Because the automatic prompt is
one-shot, the notifications page shows the current push state: while permission
is still unset it offers a **Turn on notifications** button that re-asks inside
a click gesture; blocked permission and a server without VAPID keys each get an
explicit explanation instead of failing silently.

**Setup for production:**

1. `python manage.py generate_vapid_keys` and copy the printed keys.
2. Add `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` to
   Render → Environment (keep the private key secret; changing keys only
   invalidates subscriptions — users re-subscribe on next login).
3. Deploy — no other wiring needed; `notify()` already pushes everywhere it runs
   (signals, reminders command, messaging, manual announcements).

**Scripts** (both are idempotent and safe to re-run):

```bash
# Regenerate frontend/icons/ from frontend/logo.png (needs Pillow)
venv\Scripts\python.exe scripts/generate_pwa_icons.py

# Inject manifest/theme-color/service-worker tags into any new HTML pages
python scripts/inject_pwa_tags.py
```

**Maintenance notes:**
- Add the injection script run to your routine whenever you add a new `frontend/*.html` page — new pages need `js/pwa.js` to register the worker.
- Bump `VERSION` in `sw.js` to force every client to drop its caches and refetch the shell.
- Browsers only grant service workers/installability over HTTPS or on `localhost` — production (Render, HTTPS) and the local dev origins both qualify.
- Verify with Chrome DevTools → **Application → Manifest / Service Workers**, or a Lighthouse audit.

### Design System (`theme.css`)

All visual properties use CSS custom properties:

```css
/* Light tokens */
:root {
  --brand-red: #e63946;
  --bg-root: #f5f6f8;
  --bg-card: #ffffff;
  --text-primary: #111827;
  --border-light: #e5e7eb;
}

/* Dark tokens (the default selected by api.js) */
html:not([data-theme="light"]) {
  --bg-root: #07070a;
  --bg-card: #101117;
  --text-primary: #f2f3f5;
  --border-light: rgba(255,255,255,0.08);
}
```

**Component classes available:**
- `.card`, `.stat-card` — Content containers
- `.btn`, `.btn-primary`, `.btn-danger` — Buttons
- `.badge`, `.badge-success`, `.badge-warning` — Status badges
- `.table`, `.table-striped` — Data tables
- `.sidebar`, `.topbar` — Layout components
- `.modal`, `.modal-content` — Modal dialogs
- `.skeleton` — Loading skeletons (applied to 19+ pages)

### API Client (`api.js`)

```javascript
// Split-host local development uses :8000; same-origin deployments use /api.
const API_BASE = window.FITCORE_API_BASE || detectApiBase();

// Token/session helpers
getAccessToken()
getRefreshToken()
saveTokens(access, refresh)
clearTokens()
refreshAccessToken()

// One request helper for every verb; callers pass method/body as needed.
apiRequest(path, { method: 'POST', body: JSON.stringify(data) })

// Shared application behavior
buildSidebar(activePage)
enforcePageRoleAccess()
enforceOwnerPlanGate()
exportTableToCsv(tableId, filename)
formatApiError(error)
confirmAction(message, options)
```

`apiRequest()` attaches the bearer token, serializes failures consistently, retries one request after a coordinated token refresh, and sends the active `X-Gym-ID` header. Shared in-flight refresh logic prevents concurrent 401 responses from consuming multiple rotating refresh tokens. `switchGym()` rotates the token when a user changes gyms. `enforceOwnerPlanGate()` redirects authenticated owners without a plan subscription, while public/auth pages are excluded to prevent loops.

### Dark Mode Toggle

Automatically injected into the topbar by `api.js`:
- Moon/sun toggle with `dark` as the first-visit default
- Saves the choice in `localStorage.theme`
- Sets `data-theme="light"` or `data-theme="dark"` on `<html>`
- Applies the saved theme during script initialization to avoid a theme flash

---

## 🔍 Troubleshooting

### Common Issues

**Migration/column errors** (for example, `accounts_user.display_id` or `plan_subscriptions` missing):
```bash
python manage.py showmigrations accounts
python manage.py migrate
```

**A stale test database blocks the test runner**
```bash
# Reuse an existing test database when its schema is disposable:
python manage.py test --keepdb

# Or terminate connections and remove it with PostgreSQL tools:
psql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='test_gym_db';"
psql -d postgres -c "DROP DATABASE IF EXISTS test_gym_db;"
```

**CORS or CSRF errors in the browser**
- Add the exact frontend origin to `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` (scheme + host + port).
- Keep `FRONTEND_URL` equal to the public frontend origin.
- When Django serves the frontend in production, the same-origin `/api` request needs no split-origin CORS allowance.

**JWT 401 errors**
- Access tokens expire after 60 minutes; `api.js` normally refreshes once and retries the request.
- Verify `Authorization: Bearer <token>` and the refresh token in `localStorage`.
- Password changes/resets intentionally invalidate old access and refresh tokens; log in again.
- Check `token_version` if a token issued after a password change is still rejected.

**Owner keeps returning to checkout**
- Confirm the session has `user_role=OWNER` and a valid access token.
- `GET /api/auth/subscription/` should return `has_plan: true` after a successful checkout.
- Run migrations if `PlanSubscription` queries fail.
- The gate fails open if the status request cannot complete, so a persistent redirect normally means a successful API response with `has_plan: false`.

**Render returns HTTP 400 / `DisallowedHost`**
- Confirm the live application is available at `https://fitcore-k5zr.onrender.com` and check `https://fitcore-k5zr.onrender.com/api/health/`.
- Verify the public hostname in `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- `RENDER_EXTERNAL_HOSTNAME` is automatically added by settings when Render provides it.
- Confirm daphne binds to `0.0.0.0:$PORT` and `/api/health/` is reachable.

**Static frontend or assets return 404 in production**
- Run `python manage.py collectstatic --noinput`.
- Confirm WhiteNoise is enabled and the static/frontend files were included in the deployed build.
- The frontend is served from `frontend/`; the API remains under `/api/`.

**Email is not sending**
- In development, messages print to the console with `console.EmailBackend`.
- Configure the production SMTP backend, host, port, credentials, TLS flag, and sender in the environment.

**Rate limiting (HTTP 429)**
- Auth endpoints: 10/hour per IP
- General anonymous API: 200/hour per IP
- Authenticated API: 2000/hour per user
- Membership writes: 30/min per user
- Wait for `Retry-After` / `X-RateLimit-Reset` or reduce request frequency

---

## 📄 License

This project is for educational and internal use.

---

*Built with ❤️ for gym management*
