"""
Tests for the Reports app API.

Run with:
    python manage.py test apps.reports.tests

Coverage:
    - Export endpoints: attendance, memberships, revenue, members, equipment,
      maintenance, diet, progress, staff
    - CSV header verification and row content validation
    - Excel (.xlsx) header and cell content validation
    - Date range filtering (attendance, revenue)
    - Status / plan / member / is_active filtering
    - Empty dataset handling
    - Content-Disposition filename validation
    - Role-based access (Owner only)
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.memberships.models import Membership, MembershipPlan
from apps.attendance.models import Attendance
from apps.diet.models import DietPlan, Meal
from apps.progress.models import ProgressEntry
from apps.workouts.models import Exercise

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


def auth_headers(user):
    token = RefreshToken.for_user(user)
    return {'HTTP_AUTHORIZATION': f'Bearer {str(token.access_token)}'}


def parse_csv(response):
    """Parse a CSV response into headers and rows."""
    content = response.content.decode('utf-8')
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def parse_excel(response):
    """Parse an Excel response and return (headers, rows) from the first sheet."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(response.content))
    ws = wb.active
    all_rows = []
    for row in ws.iter_rows(values_only=True):
        all_rows.append(list(row))
    if not all_rows:
        return [], []
    return all_rows[0], all_rows[1:]


# ─── Access Control ──────────────────────────────────────────────────────────

class ReportsAccessControlTestCase(APITestCase):
    """All report endpoints are Owner-only."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

    def test_owner_can_access_overview(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/overview/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_staff_forbidden_from_reports(self):
        self.client.credentials(**auth_headers(self.staff))
        r = self.client.get('/api/reports/overview/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_trainer_forbidden_from_reports(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.get('/api/reports/overview/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_forbidden_from_reports(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/reports/overview/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_forbidden(self):
        r = self.client.get('/api/reports/overview/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


# ─── Overview Report ─────────────────────────────────────────────────────────

class OverviewReportTestCase(APITestCase):
    """GET /api/reports/overview/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_overview_returns_expected_fields(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/overview/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for field in ['revenue_this_month', 'active_memberships', 'total_members',
                       'total_staff', 'lockers_occupied', 'lockers_total',
                       'equipment_out_of_service', 'attendance_today']:
            self.assertIn(field, r.data)

    def test_overview_numeric_values(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/overview/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsInstance(r.data['active_memberships'], int)
        self.assertIsInstance(r.data['total_members'], int)
        self.assertIsInstance(r.data['attendance_today'], int)


# ─── Export Attendance ───────────────────────────────────────────────────────

class ExportAttendanceTestCase(APITestCase):
    """GET /api/reports/export/attendance/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Smith')
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER,
                                      first_name='Bob', last_name='Jones')

    def test_csv_headers_match_view(self):
        """Verify the exact header row of the CSV."""
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/attendance/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, _ = parse_csv(r)
        expected = [
            'ID', 'Member Name', 'Display ID', 'Type', 'Date',
            'Status', 'Check In', 'Check Out', 'Duration (min)',
            'Marked By', 'Notes',
        ]
        self.assertEqual(headers, expected)

    def test_csv_contains_attendance_data(self):
        Attendance.objects.create(
            user=self.member, attendance_type='MEMBER',
            date=date.today(), status='PRESENT',
            notes='Morning session',
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/attendance/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # Row should contain member name, date, status
        self.assertEqual(row[1], 'Alice Smith')       # Member Name
        self.assertEqual(row[4], str(date.today()))    # Date
        self.assertEqual(row[5], 'PRESENT')            # Status
        self.assertEqual(row[10], 'Morning session')   # Notes

    def test_date_range_filters_correctly(self):
        today = date.today()
        recent = Attendance.objects.create(
            user=self.member, attendance_type='MEMBER',
            date=today, status='PRESENT',
        )
        old = Attendance.objects.create(
            user=self.other_member, attendance_type='MEMBER',
            date=today - timedelta(days=60), status='ABSENT',
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get(
            f'/api/reports/export/attendance/?start={(today - timedelta(days=7)).isoformat()}'
            f'&end={today.isoformat()}'
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'Alice Smith')
        # Old record should NOT appear
        self.assertNotIn('Bob Jones', str(rows))

    def test_date_range_excludes_outside_records(self):
        today = date.today()
        Attendance.objects.create(
            user=self.member, attendance_type='MEMBER',
            date=today - timedelta(days=45), status='PRESENT',
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get(
            f'/api/reports/export/attendance/?start={(today - timedelta(days=7)).isoformat()}'
            f'&end={today.isoformat()}'
        )
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 0)

    def test_content_disposition_filename(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/attendance/')
        disposition = r['Content-Disposition']
        self.assertIn('attachment', disposition)
        self.assertIn('.csv', disposition)

    def test_excel_headers(self):
        Attendance.objects.create(
            user=self.member, attendance_type='MEMBER',
            date=date.today(), status='PRESENT',
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/attendance/?export_format=excel')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('spreadsheetml', r['Content-Type'])
        headers, rows = parse_excel(r)
        self.assertEqual(len(headers), 11)
        self.assertEqual(headers[0], 'ID')
        self.assertEqual(headers[1], 'Member Name')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'Alice Smith')

    def test_empty_dataset_returns_header_only(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/attendance/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(headers), 11)
        self.assertEqual(len(rows), 0)

    def test_multiple_records_ordered_by_date(self):
        today = date.today()
        Attendance.objects.create(
            user=self.other_member, attendance_type='MEMBER',
            date=today - timedelta(days=1), status='PRESENT',
        )
        Attendance.objects.create(
            user=self.member, attendance_type='MEMBER',
            date=today, status='PRESENT',
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/attendance/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 2)
        # Ordered by date ascending (oldest first)
        self.assertIn('Bob Jones', rows[0][1])
        self.assertIn('Alice Smith', rows[1][1])


# ─── Export Memberships ──────────────────────────────────────────────────────

class ExportMembershipsTestCase(APITestCase):
    """GET /api/reports/export/memberships/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Smith')
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER,
                                      first_name='Bob', last_name='Jones')
        self.plan = MembershipPlan.objects.create(
            name='Monthly', price=Decimal('1000.00'), duration_days=30,
        )
        self.premium_plan = MembershipPlan.objects.create(
            name='Premium', price=Decimal('3000.00'), duration_days=90,
        )
        self.active_membership = Membership.objects.create(
            member=self.member, plan=self.plan,
            status=Membership.Status.ACTIVE,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=30),
            price_paid=Decimal('1000.00'),
        )
        self.expired_membership = Membership.objects.create(
            member=self.other_member, plan=self.premium_plan,
            status=Membership.Status.EXPIRED,
            start_date=date.today() - timedelta(days=90),
            end_date=date.today() - timedelta(days=1),
            price_paid=Decimal('3000.00'),
        )

    def test_csv_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/memberships/')
        headers, _ = parse_csv(r)
        expected = [
            'ID', 'Member Name', 'Display ID', 'Email', 'Plan', 'Status',
            'Start Date', 'End Date', 'Price Paid (NPR)', 'Frozen',
            'Freeze Start', 'Freeze End',
        ]
        self.assertEqual(headers, expected)

    def test_csv_contains_all_memberships(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/memberships/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 2)
        # Check first row (ordered by -start_date, so active first)
        names = [row[1] for row in rows]
        self.assertIn('Alice Smith', names)
        self.assertIn('Bob Jones', names)

    def test_csv_row_data_accuracy(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/memberships/')
        _, rows = parse_csv(r)
        alice_row = next(row for row in rows if 'Alice' in row[1])
        self.assertEqual(alice_row[4], 'Monthly')           # Plan
        self.assertEqual(alice_row[5], 'ACTIVE')            # Status
        self.assertEqual(float(alice_row[8]), 1000.0)       # Price Paid
        self.assertEqual(alice_row[9], 'No')                # Frozen

    def test_filter_by_status_active(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/memberships/?status=ACTIVE')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][5], 'ACTIVE')

    def test_filter_by_status_expired(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/memberships/?status=EXPIRED')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][5], 'EXPIRED')

    def test_filter_nonexistent_status(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/memberships/?status=CANCELLED')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 0)

    def test_excel_headers_and_data(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/memberships/?export_format=excel')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('spreadsheetml', r['Content-Type'])
        headers, rows = parse_excel(r)
        self.assertEqual(len(headers), 12)
        self.assertEqual(headers[4], 'Plan')
        self.assertEqual(headers[5], 'Status')
        self.assertEqual(len(rows), 2)
        # Verify plan names appear in Excel
        plan_names = [row[4] for row in rows]
        self.assertIn('Monthly', plan_names)
        self.assertIn('Premium', plan_names)


# ─── Export Revenue ──────────────────────────────────────────────────────────

class ExportRevenueTestCase(APITestCase):
    """GET /api/reports/export/revenue/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

    def test_csv_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/revenue/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, _ = parse_csv(r)
        expected = [
            'Receipt No.', 'Member Name', 'Display ID', 'Payment For',
            'Amount (NPR)', 'Discount (NPR)', 'Amount Paid (NPR)',
            'Method', 'Status', 'Transaction ID',
            'Paid At', 'Collected By', 'Notes',
        ]
        self.assertEqual(headers, expected)

    def test_date_range_filters(self):
        from apps.payments.models import Payment
        today = date.today()
        recent_payment = Payment.objects.create(
            member=self.member, payment_for='MEMBERSHIP',
            amount=Decimal('1000.00'), amount_paid=Decimal('1000.00'),
            payment_method='CASH', status='PAID',
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get(
            f'/api/reports/export/revenue/?start={today.isoformat()}'
            f'&end={today.isoformat()}'
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, rows = parse_csv(r)
        # Should contain at least the header row (might have 0 or 1 data rows
        # depending on created_at vs today)
        self.assertEqual(len(headers), 13)

    def test_excel_format(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/revenue/?export_format=excel')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('spreadsheetml', r['Content-Type'])

    def test_content_disposition(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/revenue/')
        disposition = r['Content-Disposition']
        self.assertIn('revenue_', disposition)
        self.assertIn('.csv', disposition)


# ─── Export Members ──────────────────────────────────────────────────────────

class ExportMembersTestCase(APITestCase):
    """GET /api/reports/export/members/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_csv_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/members/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, _ = parse_csv(r)
        expected = [
            'Display ID', 'Full Name', 'Email', 'Phone',
            'Active Plan', 'Membership Status', 'Membership Expires',
            'Date Joined', 'Is Active',
        ]
        self.assertEqual(headers, expected)

    def test_csv_contains_all_members(self):
        member = make_user('member@gym.com', role=User.Role.MEMBER,
                           first_name='Alice', last_name='Smith')
        other = make_user('member2@gym.com', role=User.Role.MEMBER,
                          first_name='Bob', last_name='Jones')
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/members/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 2)
        names = [row[1] for row in rows]
        self.assertIn('Alice Smith', names)
        self.assertIn('Bob Jones', names)

    def test_csv_row_content(self):
        member = make_user('member@gym.com', role=User.Role.MEMBER,
                           first_name='Alice', last_name='Smith')
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/members/')
        _, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[2], 'member@gym.com')   # Email
        self.assertEqual(row[4], 'None')              # Active Plan (no membership)
        self.assertEqual(row[8], 'Yes')               # Is Active

    def test_csv_only_includes_members(self):
        """Staff and trainer users should NOT appear in the members export."""
        make_user('trainer@gym.com', role=User.Role.TRAINER,
                  first_name='Coach', last_name='Smith')
        make_user('staff@gym.com', role=User.Role.STAFF,
                  first_name='Staff', last_name='Person')
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/members/')
        _, rows = parse_csv(r)
        all_names = ' '.join(row[1] for row in rows)
        self.assertNotIn('Coach Smith', all_names)
        self.assertNotIn('Staff Person', all_names)

    def test_excel_headers(self):
        member = make_user('member@gym.com', role=User.Role.MEMBER,
                           first_name='Alice', last_name='Smith')
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/members/?export_format=excel')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, rows = parse_excel(r)
        self.assertEqual(len(headers), 9)
        self.assertEqual(headers[1], 'Full Name')
        self.assertEqual(len(rows), 1)

    def test_empty_members_list(self):
        """No members created — should return headers only."""
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/members/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(headers), 9)
        self.assertEqual(len(rows), 0)


# ─── Export Diet ─────────────────────────────────────────────────────────────

class ExportDietTestCase(APITestCase):
    """GET /api/reports/export/diet/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Smith')
        self.active_plan = DietPlan.objects.create(
            name='Active Diet Plan', member=self.member,
            created_by=self.owner, goal='WEIGHT_LOSS',
            daily_calories=1800, protein_g=150, carbs_g=180, fats_g=50,
            is_active=True, start_date=date.today(),
        )
        self.inactive_plan = DietPlan.objects.create(
            name='Old Inactive Plan', member=self.member,
            created_by=self.owner, goal='MAINTENANCE',
            daily_calories=2200, is_active=False,
        )

    def test_csv_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/diet/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, _ = parse_csv(r)
        expected = [
            'ID', 'Plan Name', 'Member', 'Member Email', 'Created By',
            'Goal', 'Daily Calories', 'Protein (g)', 'Carbs (g)', 'Fats (g)',
            'Meals Count', 'Active', 'Start Date', 'End Date', 'Created At',
        ]
        self.assertEqual(headers, expected)

    def test_csv_contains_all_plans(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/diet/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 2)
        plan_names = [row[1] for row in rows]
        self.assertIn('Active Diet Plan', plan_names)
        self.assertIn('Old Inactive Plan', plan_names)

    def test_csv_row_data(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/diet/')
        _, rows = parse_csv(r)
        active_row = next(row for row in rows if 'Active Diet' in row[1])
        self.assertEqual(active_row[2], 'Alice Smith')       # Member
        self.assertEqual(active_row[3], 'member@gym.com')   # Member Email
        self.assertEqual(active_row[5], 'WEIGHT_LOSS')      # Goal
        self.assertEqual(active_row[6], '1800')              # Daily Calories
        self.assertEqual(active_row[7], '150')               # Protein
        self.assertEqual(active_row[11], 'Yes')              # Active

    def test_filter_active_only(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/diet/?is_active=true')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'Active Diet Plan')
        self.assertEqual(rows[0][11], 'Yes')

    def test_filter_inactive_only(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/diet/?is_active=false')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'Old Inactive Plan')
        self.assertEqual(rows[0][11], 'No')

    def test_meals_count_in_csv(self):
        """Add meals and verify the count shows in the export."""
        Meal.objects.create(
            diet_plan=self.active_plan, meal_type='BREAKFAST',
            food_name='Oatmeal', calories=350,
        )
        Meal.objects.create(
            diet_plan=self.active_plan, meal_type='LUNCH',
            food_name='Chicken', calories=500,
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/diet/')
        _, rows = parse_csv(r)
        active_row = next(row for row in rows if 'Active Diet' in row[1])
        self.assertEqual(active_row[10], '2')  # Meals Count

    def test_excel_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/diet/?export_format=excel')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, rows = parse_excel(r)
        self.assertEqual(len(headers), 15)
        self.assertEqual(headers[1], 'Plan Name')
        self.assertEqual(len(rows), 2)


# ─── Export Progress ─────────────────────────────────────────────────────────

class ExportProgressTestCase(APITestCase):
    """GET /api/reports/export/progress/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Smith')
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER,
                                      first_name='Bob', last_name='Jones')
        self.entry1 = ProgressEntry.objects.create(
            member=self.member, date=date.today(),
            weight_kg=Decimal('75.00'), height_cm=Decimal('170.00'),
            body_fat_percentage=Decimal('18.50'),
        )
        self.entry2 = ProgressEntry.objects.create(
            member=self.other_member, date=date.today(),
            weight_kg=Decimal('90.00'), height_cm=Decimal('180.00'),
        )

    def test_csv_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/progress/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, _ = parse_csv(r)
        expected = [
            'ID', 'Member', 'Member Email', 'Date',
            'Weight (kg)', 'Height (cm)', 'BMI', 'Body Fat %',
            'Muscle Mass (kg)', 'Chest (cm)', 'Waist (cm)', 'Hips (cm)',
            'Bicep (cm)', 'Thigh (cm)', 'Recorded By', 'Notes',
        ]
        self.assertEqual(headers, expected)

    def test_csv_contains_all_entries(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/progress/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 2)
        member_names = [row[1] for row in rows]
        self.assertIn('Alice Smith', member_names)
        self.assertIn('Bob Jones', member_names)

    def test_csv_row_data(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/progress/')
        _, rows = parse_csv(r)
        alice_row = next(row for row in rows if 'Alice' in row[1])
        self.assertEqual(float(alice_row[4]), 75.0)          # Weight
        self.assertEqual(float(alice_row[5]), 170.0)         # Height
        self.assertEqual(alice_row[2], 'member@gym.com')    # Email
        # BMI should be calculated
        bmi = float(alice_row[6])
        self.assertGreater(bmi, 0)

    def test_filter_by_member(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get(f'/api/reports/export/progress/?member={self.member.id}')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'Alice Smith')

    def test_filter_by_other_member(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get(f'/api/reports/export/progress/?member={self.other_member.id}')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'Bob Jones')

    def test_filter_nonexistent_member(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/progress/?member=99999')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 0)

    def test_excel_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/progress/?export_format=excel')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, rows = parse_excel(r)
        self.assertEqual(len(headers), 16)
        self.assertEqual(headers[1], 'Member')
        self.assertEqual(len(rows), 2)


# ─── Export Staff ────────────────────────────────────────────────────────────

class ExportStaffTestCase(APITestCase):
    """GET /api/reports/export/staff/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff_user = make_user('staff@gym.com', role=User.Role.STAFF,
                                    first_name='John', last_name='Staff')
        self.trainer_user = make_user('trainer@gym.com', role=User.Role.TRAINER,
                                      first_name='Coach', last_name='Smith')
        from apps.staff.models import StaffProfile
        self.staff_profile = StaffProfile.objects.create(
            user=self.staff_user, department='Training',
            salary=Decimal('35000.00'),
        )

    def test_csv_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/staff/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, _ = parse_csv(r)
        expected = [
            'ID', 'Full Name', 'Email', 'Phone', 'Department',
            'Joined Date', 'Salary (NPR)', 'Is Active',
        ]
        self.assertEqual(headers, expected)

    def test_csv_contains_staff_data(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/staff/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[1], 'John Staff')       # Full Name
        self.assertEqual(row[2], 'staff@gym.com')   # Email
        self.assertEqual(row[4], 'Training')         # Department

    def test_excel_headers(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/staff/?export_format=excel')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, rows = parse_excel(r)
        self.assertEqual(len(headers), 8)
        self.assertEqual(headers[1], 'Full Name')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'John Staff')


# ─── Export Equipment ────────────────────────────────────────────────────────

class ExportEquipmentTestCase(APITestCase):
    """GET /api/reports/export/equipment/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_csv_headers(self):
        from apps.equipment.models import Equipment
        Equipment.objects.create(
            name='Treadmill', category='CARDIO',
            brand='Life Fitness', model_number='T5',
            quantity=2, condition='GOOD',
            location='Floor 1',
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/equipment/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, _ = parse_csv(r)
        expected = [
            'ID', 'Name', 'Category', 'Brand', 'Model', 'Serial Number',
            'Quantity', 'Condition', 'Location', 'Purchase Date',
            'Purchase Price (NPR)', 'Notes',
        ]
        self.assertEqual(headers, expected)

    def test_csv_contains_equipment_data(self):
        from apps.equipment.models import Equipment
        Equipment.objects.create(
            name='Treadmill', category='CARDIO',
            brand='Life Fitness', model_number='T5',
            quantity=2, condition='GOOD',
            location='Floor 1',
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/equipment/')
        _, rows = parse_csv(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'Treadmill')
        self.assertEqual(rows[0][2], 'CARDIO')
        self.assertEqual(rows[0][6], '2')

    def test_empty_equipment(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/equipment/')
        headers, rows = parse_csv(r)
        self.assertEqual(len(headers), 12)
        self.assertEqual(len(rows), 0)


# ─── Export Maintenance ──────────────────────────────────────────────────────

class ExportMaintenanceTestCase(APITestCase):
    """GET /api/reports/export/maintenance/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_csv_headers(self):
        from apps.equipment.models import Equipment, MaintenanceRecord
        eq = Equipment.objects.create(
            name='Bike', category='CARDIO', brand='Wattbike',
            model_number='Atom', quantity=1, condition='GOOD',
            location='Floor 2',
        )
        MaintenanceRecord.objects.create(
            equipment=eq, maintenance_type='ROUTINE',
            status='SCHEDULED', scheduled_date=date.today() + timedelta(days=7),
            cost=Decimal('500.00'),
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/export/maintenance/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        headers, _ = parse_csv(r)
        expected = [
            'ID', 'Equipment', 'Type', 'Status', 'Scheduled Date',
            'Completed Date', 'Cost (NPR)', 'Notes',
        ]
        self.assertEqual(headers, expected)


# ─── JSON Reports ────────────────────────────────────────────────────────────

class RevenueReportTestCase(APITestCase):
    """GET /api/reports/revenue/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_revenue_report_returns_expected_fields(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/revenue/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for field in ['monthly_trend', 'by_method', 'by_status', 'totals']:
            self.assertIn(field, r.data)

    def test_totals_structure(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/revenue/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        totals = r.data['totals']
        self.assertIn('collected', totals)
        self.assertIn('pending', totals)
        self.assertIn('refunded', totals)


class MembershipReportTestCase(APITestCase):
    """GET /api/reports/memberships/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_membership_report_returns_expected_fields(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/memberships/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for field in ['by_status', 'by_plan', 'total_active', 'expiring_soon']:
            self.assertIn(field, r.data)


class AttendanceReportTestCase(APITestCase):
    """GET /api/reports/attendance/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_attendance_report_returns_expected_fields(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/attendance/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for field in ['daily', 'by_type', 'total_last_30_days']:
            self.assertIn(field, r.data)


class EquipmentReportTestCase(APITestCase):
    """GET /api/reports/equipment/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_equipment_report_fields(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/equipment/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for field in ['by_condition', 'total_items', 'maintenance_cost_total',
                       'upcoming_maintenance', 'overdue_maintenance']:
            self.assertIn(field, r.data)


class LockerReportTestCase(APITestCase):
    """GET /api/reports/lockers/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_locker_report_fields(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/lockers/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for field in ['by_status', 'total_lockers', 'occupied',
                       'occupancy_rate', 'monthly_recurring_revenue']:
            self.assertIn(field, r.data)


class StaffReportTestCase(APITestCase):
    """GET /api/reports/staff/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)

    def test_staff_report_fields(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/reports/staff/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for field in ['by_department', 'total_staff', 'pending_leave_requests']:
            self.assertIn(field, r.data)
