# 🏋️ FitCore — Gym Management System

A full-stack role-based web application for managing gym operations: memberships, attendance, payments, trainers, workouts, diet plans, progress tracking, lockers, equipment, notifications, and analytics.

![Stack](https://img.shields.io/badge/Django-5.2-092E20?style=flat-square&logo=django)
![Stack](https://img.shields.io/badge/DRF-3.15-A93C2D?style=flat-square)
![Stack](https://img.shields.io/badge/PostgreSQL-14-4169E1?style=flat-square&logo=postgresql)
![Stack](https://img.shields.io/badge/JWT-SimpleJWT-green?style=flat-square)

---

## Table of Contents

- [Quick Start](#-quick-start)
- [Project Architecture](#-project-architecture)
- [Environment Variables](#-environment-variables)
- [User Guide](#-user-guide)
  - [Roles & Permissions](#roles--permissions)
  - [Frontend Pages](#frontend-pages)
  - [Common Workflows](#common-workflows)
- [Developer Guide](#-developer-guide)
  - [Tech Stack](#tech-stack)
  - [App Module Reference](#app-module-reference)
  - [Database Schema](#database-schema)
  - [API Reference](#-api-reference)
  - [Authentication](#authentication)
  - [Rate Limiting](#rate-limiting)
  - [Dark Mode](#dark-mode)
  - [Notifications System](#notifications-system)
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
- Node.js (optional, for frontend tooling)

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

Create a `.env` file in the project root:

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=127.0.0.1

DB_NAME=gym_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Email (console backend in dev)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend

# Frontend URL (for password reset links)
FRONTEND_URL=http://127.0.0.1:5500
```

### 3. Create database & migrate

```sql
-- In PostgreSQL:
CREATE DATABASE gym_db;
```

```bash
python manage.py migrate
```

### 4. Create the Owner account

```bash
python manage.py createsuperuser
```

### 5. Run the server

```bash
python manage.py runserver
```

### 6. Open the frontend

Serve the `frontend/` folder with any static server (e.g., VS Code Live Server on port 5500) and open:

```
http://127.0.0.1:5500/login.html
```

---

## 🏗️ Project Architecture

```
gym_management/          # Django project settings & URLs
├── apps/                # 14 Django apps (one per domain)
│   ├── accounts/        # Custom user model, JWT auth, RBAC
│   ├── members/         # Member profiles, fitness goals
│   ├── memberships/     # Plans, freeze/unfreeze, renewals
│   ├── attendance/      # Check-in/out, QR tokens
│   ├── payments/        # Transactions, receipts, eSewa/Khalti
│   ├── staff/           # Staff profiles, departments, leaves
│   ├── trainers/        # Trainer profiles, member assignments
│   ├── workouts/        # Exercise library, templates, assignments
│   ├── diet/            # Diet plans, meals, daily logs
│   ├── progress/        # Body metrics, personal records
│   ├── lockers/         # Locker inventory & assignments
│   ├── equipment/       # Equipment inventory & maintenance
│   ├── notifications/   # In-app notifications, email alerts
│   └── reports/         # Analytics & CSV/Excel export
├── frontend/            # Static HTML/CSS/JS frontend
│   ├── css/             # theme.css (design tokens + dark mode)
│   └── js/              # api.js (API client + utilities)
├── templates/           # Django email templates
├── scripts/             # Windows Task Scheduler scripts
├── logs/                # Application logs
└── manage.py
```

### Design Principles

- **One app per domain**: Each Django app owns its models, serializers, views, and URLs
- **Role-Based Access Control (RBAC)**: Every endpoint enforces permissions via custom permission classes
- **JWT Authentication**: Stateless auth with access/refresh token rotation
- **Frontend-agnostic API**: The REST API can serve any client (web, mobile, etc.)
- **Dark mode first**: CSS custom properties with `[data-theme="dark"]` tokens

---

## 🔧 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | ✅ | — | Django secret key |
| `DEBUG` | ❌ | `False` | Enable debug mode |
| `ALLOWED_HOSTS` | ❌ | `127.0.0.1` | Comma-separated allowed hosts |
| `DB_NAME` | ❌ | `gym_db` | PostgreSQL database name |
| `DB_USER` | ❌ | `postgres` | Database user |
| `DB_PASSWORD` | ❌ | `postgres` | Database password |
| `DB_HOST` | ❌ | `localhost` | Database host |
| `DB_PORT` | ❌ | `5432` | Database port |
| `EMAIL_BACKEND` | ❌ | Console backend | Email transport |
| `EMAIL_HOST` | ❌ | `smtp.gmail.com` | SMTP server |
| `EMAIL_PORT` | ❌ | `587` | SMTP port |
| `EMAIL_HOST_USER` | ❌ | — | SMTP username |
| `EMAIL_HOST_PASSWORD` | ❌ | — | SMTP password |
| `DEFAULT_FROM_EMAIL` | ❌ | `Gym Management <noreply@gym.local>` | Sender address |
| `FRONTEND_URL` | ❌ | `http://127.0.0.1:5500` | Frontend base URL for reset links |
| `KHALTI_SECRET_KEY` | ❌ | — | Khalti merchant key |
| `KHALTI_BASE_URL` | ❌ | `https://dev.khalti.com/api/v2` | Khalti API base |
| `ESEWA_MERCHANT_CODE` | ❌ | `EPAYTEST` | eSewa test merchant code |
| `ESEWA_SECRET_KEY` | ❌ | `8gBm/:&EnhH.1/q` | eSewa test secret |

---

## 👤 User Guide

### Roles & Permissions

| Role | Can Do | Cannot Do |
|------|--------|-----------|
| **Owner** | Everything — full admin access, reports, settings, staff management | — |
| **Staff** | Manage members, attendance, payments, memberships, freeze requests | View reports, manage trainers, system settings |
| **Trainer** | View assigned members, create workout/diet plans, log attendance | Manage payments, view other trainers' members |
| **Member** | View own profile, plans, progress, log meals, check in/out | Access admin features, see other members' data |

### Frontend Pages

#### Public Pages (no login required)
| Page | URL | Purpose |
|------|-----|---------|
| Landing | `index.html` | Marketing page with features and pricing |
| Login | `login.html` | JWT login with email + password |
| Sign Up | `signup.html` | New member registration |
| Forgot Password | `forgot-password.html` | Request password reset email |
| Reset Password | `reset-password.html` | Set new password via token |

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
| Member Card | `member-card.html` | QR code for check-in |

#### Staff/Admin Pages
| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | `dashboard.html` | KPI overview, charts, quick actions |
| Members | `members.html` | Member list, search, CRUD |
| Member Detail | `member-detail.html` | Individual member profile drill-down |
| Attendance | `attendance.html` | Manual attendance marking, today's stats |
| Memberships | `memberships.html` | Plan management, assign/renew/freeze |
| Payments | `payments.html` | Payment collection, history, refunds |
| Staff | `staff.html` | Staff profiles, departments, leaves |
| Workouts | `workouts.html` | Exercise library, template builder |
| Diet | `diet.html` | Diet plan builder, meal management |
| Progress | `progress.html` | All members' progress entries |
| Lockers | `lockers.html` | Locker inventory & assignments |
| Equipment | `equipment.html` | Equipment inventory & maintenance |
| Notifications | `notifications.html` | Send/manage notifications |
| Reports | `reports.html` | Analytics dashboards, CSV/Excel export |

#### Trainer Pages
| Page | URL | Purpose |
|------|-----|---------|
| Trainer Dashboard | `trainer-dashboard.html` | Assigned members, stat cards, charts |
| Trainer Members | `trainer-members.html` | List of assigned members with details |

### Common Workflows

#### Adding a New Member
1. **Sign up** via `signup.html` (creates a MEMBER account)
2. **Staff assigns a membership plan** via `memberships.html`
3. **Payment collected** via `payments.html`
4. **Member assigned to a trainer** by Owner/Staff via staff management

#### Member Check-In
1. Member opens `my-attendance.html` and shows their QR code
2. Staff scans the QR code or manually marks attendance via `attendance.html`
3. Attendance record is created with timestamp

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

---

## 🛠️ Developer Guide

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.2, Django REST Framework 3.15 |
| Database | PostgreSQL 14+ |
| Auth | JWT (SimpleJWT) with token blacklist |
| Frontend | Vanilla HTML/CSS/JS (no framework) |
| Payments | eSewa (sandbox), Khalti (sandbox) |
| Exports | CSV (stdlib), Excel (openpyxl) |
| QR Codes | `qrcode` library |
| Images | Pillow |

### App Module Reference

#### `accounts` — Authentication & User Model
- **Model**: Custom `User` with roles (OWNER, STAFF, TRAINER, MEMBER)
- **Key features**: JWT login/logout, password reset via email, profile management
- **Permission classes**: `IsOwner`, `IsStaff`, `IsTrainer`, `IsMember`, `IsOwnerOrStaff`, `IsOwnerOrStaffOrTrainer`

#### `members` — Member Profiles
- **Model**: `MemberProfile` (OneToOne with User)
- **Key features**: Fitness goals, BMI calculation, emergency contacts

#### `memberships` — Plans & Subscriptions
- **Models**: `MembershipPlan`, `Membership`, `FreezeRequest`
- **Key features**: Auto-computed end dates, freeze/unfreeze with day extension, renewal chain, approval workflow

#### `attendance` — Check-In/Out
- **Models**: `Attendance`, `QRAttendanceToken`
- **Key features**: QR code scanning, duration calculation, daily uniqueness

#### `payments` — Financial Transactions
- **Model**: `Payment`
- **Key features**: Receipt numbers, discounts, eSewa/Khalti integration, status tracking

#### `workouts` — Exercise & Workout Management
- **Models**: `Exercise`, `WorkoutTemplate`, `WorkoutDay`, `WorkoutDayExercise`, `WorkoutAssignment`, `WorkoutCompletionLog`, `WorkoutTemplateVersion`
- **Key features**: Exercise library, template builder with clone, version history, assignment tracking

#### `diet` — Nutrition Plans
- **Models**: `DietPlan`, `Meal`, `MealLog`
- **Key features**: Macro targets, meal scheduling, daily intake logging, calorie summary

#### `progress` — Body Metrics & PRs
- **Models**: `ProgressEntry`, `PersonalRecord`
- **Key features**: BMI calculation, body measurements, exercise PRs, trend tracking

#### `notifications` — In-App Alerts
- **Model**: `Notification`
- **Key features**: Auto-generated alerts, read/unread tracking, email delivery
- **Management command**: `send_reminders` — generates daily notifications

#### `reports` — Analytics & Export
- **No models** (queries across all apps)
- **Key features**: Revenue/attendance/membership/equipment dashboards, CSV and Excel export with date filtering

---

### Database Schema (Key Relationships)

```
User ──1:1──> MemberProfile
User ──1:N──> Membership ──N:1──> MembershipPlan
User ──1:N──> Attendance
User ──1:N──> Payment
User ──1:N──> WorkoutAssignment ──N:1──> WorkoutTemplate
User ──1:N──> DietPlan ──1:N──> Meal
User ──1:N──> ProgressEntry
User ──1:N──> PersonalRecord ──N:1──> Exercise
User ──1:N──> Notification
User ──1:N──> FreezeRequest ──N:1──> Membership
```

---

## 📡 API Reference

### Base URL

```
http://127.0.0.1:8000/api
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

### Endpoint Summary

#### Auth (`/api/auth/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/register/` | ❌ | Register new member |
| POST | `/login/` | ❌ | Get JWT tokens |
| POST | `/token/refresh/` | ❌ | Refresh access token |
| POST | `/logout/` | ✅ | Blacklist refresh token |
| GET | `/me/` | ✅ | Get own profile |
| PATCH | `/me/` | ✅ | Update own profile |
| POST | `/change-password/` | ✅ | Change password |
| POST | `/forgot-password/` | ❌ | Request reset email |
| POST | `/reset-password/` | ❌ | Reset password with token |

#### Members (`/api/members/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | Staff+ | List all members |
| POST | `/` | Staff+ | Create member profile |
| GET | `/<id>/` | Staff+ | Member detail |
| PATCH | `/<id>/` | Staff+ | Update member |
| DELETE | `/<id>/` | Staff+ | Deactivate member |
| GET | `/ui/` | Staff+ | Member list (template) |
| GET | `/ui/<id>/` | Staff+ | Member detail (template) |

#### Memberships (`/api/memberships/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/plans/` | ✅ | List membership plans |
| POST | `/plans/` | Owner/Staff | Create plan |
| GET/PUT/PATCH/DELETE | `/plans/<id>/` | Owner/Staff | Plan detail (DELETE = deactivate) |
| GET | `/` | ✅ | List memberships |
| POST | `/` | ✅ | Assign membership |
| GET | `/<id>/` | ✅ | Membership detail |
| PATCH | `/<id>/` | Owner/Staff | Update membership |
| DELETE | `/<id>/` | Owner/Staff | Cancel membership |
| POST | `/<id>/freeze/` | Owner/Staff | Freeze membership |
| POST | `/<id>/unfreeze/` | Owner/Staff | Unfreeze (extends end date) |
| POST | `/<id>/renew/` | ✅ | Renew membership |
| GET | `/expiring/?days=7` | Owner/Staff | Expiring soon |
| GET/POST | `/freeze-requests/` | ✅ | List/create freeze requests |
| POST | `/freeze-requests/<id>/approve/` | Owner/Staff | Approve freeze request |
| POST | `/freeze-requests/<id>/reject/` | Owner/Staff | Reject freeze request |

#### Attendance (`/api/attendance/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/records/` | ✅ | List attendance records |
| POST | `/records/` | Staff+ | Mark attendance |
| GET/PUT/PATCH/DELETE | `/records/<id>/` | Staff+ | Record detail |
| POST | `/check-in/` | ✅ | Quick check-in |
| POST | `/check-out/` | ✅ | Quick check-out |
| GET | `/today/` | ✅ | Today's attendance |
| GET | `/stats/` | Owner/Staff | Attendance statistics |
| GET/POST | `/qr-tokens/` | ✅ | QR token management |
| POST | `/qr-scan/` | Staff+ | Scan QR code for attendance |

#### Payments (`/api/payments/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | Staff+ | List payments |
| POST | `/` | Staff+ | Record payment |
| GET | `/<id>/` | Staff+ | Payment detail |
| POST | `/<id>/refund/` | Owner/Staff | Refund payment |
| GET | `/stats/` | Owner/Staff | Payment statistics |

#### Workouts (`/api/workouts/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/exercises/` | ✅ | Exercise library |
| GET/PUT/PATCH/DELETE | `/exercises/<id>/` | Trainer+ | Exercise detail |
| GET/POST | `/templates/` | Trainer+ | Workout templates |
| GET/PUT/PATCH/DELETE | `/templates/<id>/` | Trainer+ | Template detail |
| POST | `/templates/<id>/submit/` | Trainer | Submit for review |
| POST | `/templates/<id>/approve/` | Owner/Staff | Approve template |
| GET/POST | `/assignments/` | ✅ | Workout assignments |
| GET/POST | `/completions/` | ✅ | Completion logs |

#### Diet (`/api/diet/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET/POST | `/diet-plans/` | ✅ | Diet plans (scoped by role) |
| GET/PUT/PATCH/DELETE | `/diet-plans/<id>/` | ✅ | Plan detail |
| GET | `/diet-plans/stats/` | ✅ | Plan statistics |
| GET/POST | `/meals/` | Trainer+ | Meals (filter by `?diet_plan=<id>`) |
| GET/POST | `/meal-logs/` | ✅ | Daily meal logs |
| GET | `/meal-logs/daily-summary/` | ✅ | Daily calorie/macro summary |

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
| GET | `/` | ✅ | List notifications |
| GET/PATCH/DELETE | `/<id>/` | ✅ | Notification detail |
| PATCH | `/<id>/read/` | ✅ | Mark as read |
| POST | `/read-all/` | ✅ | Mark all as read |
| GET | `/unread-count/` | ✅ | Unread count |

#### Trainers (`/api/trainers/`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/profiles/` | Owner/Staff | List trainer profiles |
| GET/POST | `/assignments/` | Owner/Staff | Member assignments |
| GET | `/my-members/` | Trainer | My assigned members |

---

### Authentication

**JWT Flow:**
1. Login → receive `access` (60 min) + `refresh` (7 days) tokens
2. Use `access` token in `Authorization: Bearer <token>` header
3. When access expires, POST refresh token to `/api/auth/token/refresh/`
4. Refresh tokens rotate on each use (old one is blacklisted)
5. Logout blacklists the refresh token

**Rate Limits on Auth:**
- Login: 10 requests/hour per IP
- Register: 10 requests/hour per IP
- Password reset: 10 requests/hour per IP

---

### Rate Limiting

| Scope | Rate | Applied To |
|-------|------|------------|
| Anonymous | 50/hour | All unauthenticated requests |
| Authenticated | 200/hour | All authenticated requests |
| Auth endpoints | 10/hour | Login, register, password reset |
| Membership writes | 30/min | Freeze, unfreeze, renew operations |

Rate limit headers are included in responses:
```
X-RateLimit-Limit: 200
X-RateLimit-Remaining: 195
X-RateLimit-Reset: 1693500000
```

When rate limited, the API returns:
```json
{
  "detail": "Request was throttled. Please try again in 1234 seconds."
}
```

---

### Dark Mode

The frontend supports light/dark mode with a toggle button in the topbar.

**Implementation:**
- CSS custom properties in `theme.css` with `[data-theme="dark"]` overrides
- Toggle button injected dynamically by `api.js`
- Preference persisted in `localStorage`
- Applied immediately on page load (no flash)

**To extend dark mode:**
1. Add CSS variables to the `[data-theme="dark"]` block in `theme.css`
2. Use `var(--bg-card)`, `var(--text-primary)`, etc. in your styles
3. Test with the toggle button in the topbar

---

### Notifications System

**Auto-generated notifications (via `send_reminders` command):**
- Membership expiry (7 days before)
- Pending payments
- Member inactivity (14+ days no check-in)
- Workout reminders (active plan but no session in 3+ days)
- Welcome messages for new members
- Workout/diet plan assignments

**Notification delivery:**
- In-app notifications (via API)
- Email notifications (via Django email backend)
- Notification types: GENERAL, MEMBERSHIP, PAYMENT, WORKOUT, DIET, ATTENDANCE

---

### Scheduled Tasks

The `send_reminders` management command runs daily to generate notifications.

**Windows (Task Scheduler):**
```powershell
# One-time setup:
schtasks /create /xml "scripts\GymDailyReminders.xml" /tn "GymDailyReminders"

# Manual run:
schtasks /run /tn "GymDailyReminders"
```

**Linux (cron):**
```bash
0 8 * * * cd /path/to/gym && venv/bin/python manage.py send_reminders >> logs/reminders.log 2>&1
```

---

## 🧪 Testing

### Run All Tests

```bash
python manage.py test
```

### Run Specific App Tests

```bash
python manage.py test apps.diet.tests        # 35 tests
python manage.py test apps.progress.tests    # 33 tests
python manage.py test apps.memberships.tests # 50 tests
python manage.py test apps.reports.tests     # 60 tests
python manage.py test apps.trainers.tests    # 31 tests
```

### Test Coverage Summary

| App | Tests | What's Tested |
|-----|-------|---------------|
| **diet** | 35 | DietPlan CRUD, nested meals, Meal CRUD, MealLog, DailySummaryView, filtering (`?q=`, `?goal=`), stats, disclaimer |
| **progress** | 33 | ProgressEntry CRUD, BMI calculation, PersonalRecord CRUD + validation, MemberStatsView, role-based access |
| **memberships** | 50 | Plan CRUD, membership assign/cancel, freeze/unfreeze (end_date extension), renew, FreezeRequest create/approve/reject, expiring endpoint, auto-expiry sync, search/filter/ordering |
| **reports** | 60 | CSV/Excel header validation, row content parsing, date range filtering, status/plan/member filtering, empty datasets, Content-Disposition, role-based access |
| **trainers** | 31 | TrainerMemberAssignment CRUD, my-members endpoint, workout/diet/attendance visibility, notification access |

**Total: 212 tests across 5 apps**

### Test Patterns Used

- `APITestCase` from DRF for API endpoint testing
- JWT token authentication via `RefreshToken.for_user()`
- CSV parsing with `csv.reader` for content validation
- Excel parsing with `openpyxl.load_workbook()` for .xlsx validation
- Role-based test coverage (Owner, Staff, Trainer, Member)

---

## 🚀 Deployment

### Production Checklist

1. **Environment variables**: Set `DEBUG=False`, configure real database credentials
2. **Static files**: `python manage.py collectstatic`
3. **Database**: Run `python manage.py migrate`
4. **Secret key**: Generate a new `SECRET_KEY` (never use the dev key)
5. **Allowed hosts**: Set to your production domain
6. **HTTPS**: Configure SSL (nginx, Cloudflare, etc.)
7. **Email**: Switch to production SMTP backend
8. **Payment gateways**: Switch Khalti/eSewa to production URLs and keys
9. **Task scheduler**: Set up cron/Task Scheduler for `send_reminders`
10. **Logs**: Configure structured logging (consider Sentry for error tracking)

### Docker (Not Yet Implemented)

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput
CMD ["gunicorn", "gym_management.wsgi:application", "--bind", "0.0.0.0:8000"]
```

### WSGI Server (Production)

```bash
pip install gunicorn
gunicorn gym_management.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

---

## 🖥️ Frontend Architecture

### File Structure

```
frontend/
├── css/
│   ├── theme.css        # Design tokens, component styles, dark mode
│   ├── landing.css      # Landing page styles
│   └── login.css        # Login/signup page styles
├── js/
│   ├── api.js           # API client, auth helpers, dark mode, utilities
│   └── bottom-tabs.js   # Mobile bottom navigation
├── *.html               # 32 page files (one per view)
└── logo.png             # App logo
```

### Design System (`theme.css`)

All visual properties use CSS custom properties:

```css
/* Light mode (default) */
:root {
  --brand-red: #E63946;
  --bg-root: #F1F5F9;
  --bg-card: #FFFFFF;
  --text-primary: #1E293B;
  --border-light: #E2E8F0;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.08);
}

/* Dark mode */
[data-theme="dark"] {
  --bg-root: #0C1220;
  --bg-card: #151D2E;
  --text-primary: #E2E8F0;
  --border-light: #1E2D42;
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
// Base URL (configurable)
const API_BASE = window.FITCORE_API_BASE || 'http://127.0.0.1:8000/api';

// Auth helpers
function getToken()        // Get access token from localStorage
function getRefreshToken() // Get refresh token
function setTokens(access, refresh)  // Store tokens
function clearTokens()     // Logout

// API helpers
async function apiGet(path)           // GET request
async function apiPost(path, data)    // POST request
async function apiPatch(path, data)   // PATCH request
async function apiDelete(path)        // DELETE request

// UI utilities
function showToast(message, type)     // Toast notifications
function formatDate(dateStr)          // Human-readable dates
function formatCurrency(amount)       // NPR currency formatting
```

### Dark Mode Toggle

Automatically injected into the topbar by `api.js`:
- Toggle button with moon/sun icon
- Saves preference to `localStorage`
- Applies `[data-theme="dark"]` to `<html>` element
- No flash of wrong theme on page load

---

## 🔍 Troubleshooting

### Common Issues

**"column \"accounts_user.display_id\" does not exist"**
```bash
python manage.py migrate
```

**"database 'test_gym_db' already exists"**
```bash
# Drop the test database:
python -c "
import os; os.environ['DJANGO_SETTINGS_MODULE']='gym_management.settings'
import django; django.setup()
from django.db import connection
conn = connection.cursor().connection; conn.autocommit = True
conn.cursor().execute('DROP DATABASE IF EXISTS test_gym_db')
"
```

**CORS errors in browser**
- Check `CORS_ALLOWED_ORIGINS` in `settings.py`
- Ensure your frontend port is listed

**JWT 401 errors**
- Access tokens expire after 60 minutes
- Use the refresh endpoint to get a new access token
- Check that `Authorization: Bearer <token>` header is set

**Email not sending**
- In development, emails print to console (`console.EmailBackend`)
- Configure SMTP credentials in `.env` for production

**Rate limiting (429 errors)**
- Auth endpoints: 10/hour per IP
- General API: 200/hour per authenticated user
- Wait for the `X-RateLimit-Reset` time or reduce request frequency

---

## 📄 License

This project is for educational and internal use.

---

*Built with ❤️ for gym management*
