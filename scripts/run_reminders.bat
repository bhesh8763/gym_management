@echo off
:: ============================================================
:: run_reminders.bat
:: Runs the Django send_reminders management command.
:: Designed to be called from Windows Task Scheduler daily.
::
:: Setup (one-time, elevated PowerShell):
::   schtasks /create /tn "GymDailyReminders" /tr "C:\path\to\gym\scripts\run_reminders.bat" /sc DAILY /st 08:00 /ru SYSTEM /f
::
:: Or import the XML task definition:
::   schtasks /create /xml "%~dp0GymDailyReminders.xml" /tn "GymDailyReminders"
::
:: Edit the two variables below to match your actual install path.
:: ============================================================

:: ── EDIT THESE ──────────────────────────────────────────────
set PROJECT_DIR=C:\Users\bsaru\Desktop\gym
set PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe
:: ────────────────────────────────────────────────────────────

cd /d "%PROJECT_DIR%"
"%PYTHON%" manage.py send_reminders >> "%PROJECT_DIR%\logs\reminders.log" 2>&1
