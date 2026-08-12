# Gym Management System

A role-based web application for managing gym memberships, attendance, payments, trainers, workout plans, diet plans, progress tracking, lockers, equipment, and notifications.

**Stack:** Django 5.2 · Django REST Framework · PostgreSQL · JWT Authentication

---

## Quick Start

### 1. Create & activate virtual environment
```
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # macOS/Linux
```

### 2. Install dependencies
```
pip install -r requirements.txt
```

### 3. Configure environment
Create a `.env` file in the project root and set your credentials:
```
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=127.0.0.1

DB_NAME=gym_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

### 4. Create database in PostgreSQL
```sql
CREATE DATABASE gym_db;
```

### 5. Run migrations
```
python manage.py makemigrations
python manage.py migrate
```

### 6. Create superuser (Owner)
```
python manage.py createsuperuser
```

### 7. Run development server
```
python manage.py runserver
```

### 8. Run auth tests
```
python manage.py test apps.accounts.tests
```

### 9. Run all tests
```
python manage.py test
```

---

## Scheduled Tasks (Windows Task Scheduler)

The `send_reminders` management command generates daily notifications for:
- Membership renewals / expiry
- Pending payments
- Member inactivity (no check-in for 14+ days)
- Workout reminders (active plan but no session logged in 3+ days)

### Quick setup

1. Create the log directory:
```
mkdir C:\Users\bsaru\Desktop\gym\logs
```

2. Register the task (elevated PowerShell — **edit the path first**):
```powershell
schtasks /create `
  /tn "GymDailyReminders" `
  /tr "C:\Users\bsaru\Desktop\gym\scripts\run_reminders.bat" `
  /sc DAILY `
  /st 08:00 `
  /ru SYSTEM `
  /f
```

Or import the included XML definition (already configured for this machine):
```powershell
schtasks /create /xml "C:\Users\bsaru\Desktop\gym\scripts\GymDailyReminders.xml" /tn "GymDailyReminders"
```

3. Verify:
```
schtasks /query /tn "GymDailyReminders"
```

4. Test immediately:
```
schtasks /run /tn "GymDailyReminders"
```

Output is appended to `logs\reminders.log`.

> **Moving to Linux?** Replace the batch script with a cron job:
> ```
> 0 8 * * * cd /path/to/gym && venv/bin/python manage.py send_reminders >> logs/reminders.log 2>&1
> ```

---

## API Endpoints

### Auth

| Method | URL                        | Description             | Auth Required |
|--------|----------------------------|-------------------------|---------------|
| POST   | /api/auth/register/        | Register new user       | No            |
| POST   | /api/auth/login/           | Login, get JWT tokens   | No            |
| POST   | /api/auth/token/refresh/   | Refresh access token    | No            |
| POST   | /api/auth/logout/          | Blacklist refresh token | Yes           |
| GET    | /api/auth/me/              | Get own profile         | Yes           |
| PATCH  | /api/auth/me/              | Update own profile      | Yes           |
| POST   | /api/auth/change-password/ | Change password         | Yes           |

---

## Roles

| Role    | Description                                      |
|---------|--------------------------------------------------|
| OWNER   | Full access — manages staff, reports, settings   |
| STAFF   | Front-desk operations — members, payments        |
| TRAINER | Manage assigned members, workout & diet plans    |
| MEMBER  | View own profile, plans, progress, notifications |

---

## Modules

| Module        | Description                                              |
|---------------|----------------------------------------------------------|
| Accounts      | Custom user model, JWT auth, RBAC                        |
| Members       | Member profiles, fitness goals, BMI                      |
| Memberships   | Plans, renewals, freeze/cancel                           |
| Attendance    | Check-in/out for members, staff, and trainers            |
| Payments      | Transactions, discounts, receipts (cash/eSewa/Khalti)    |
| Staff         | Staff profiles, departments, leave requests              |
| Trainers      | Trainer profiles, specializations, member assignments    |
| Workouts      | Exercise library, workout plans, days, and sets/reps     |
| Diet          | Diet plans, meals, macros                                |
| Progress      | Body metrics over time, personal records (PRs)           |
| Lockers       | Locker inventory and member assignments                  |
| Equipment     | Equipment inventory and maintenance schedules            |
| Notifications | Membership expiry, payment due, inactivity alerts        |

---

## Admin

http://127.0.0.1:8000/admin/
