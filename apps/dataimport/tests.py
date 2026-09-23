"""
Tests for the bulk workbook import.

Run with:
    python manage.py test apps.dataimport

Coverage:
    - Schema/template endpoints (Owner only)
    - Dry run: previews counts without writing anything
    - Commit: creates plans, people, memberships, payments, attendance, etc.
    - Idempotency: re-uploading the same file skips every existing record
    - All-or-nothing: one bad row blocks the whole commit
    - Cross-sheet references (unknown plan / unknown member)
    - Role-derived attendance type, default passwords, permissions, extensions
"""
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.attendance.models import Attendance
from apps.equipment.models import Equipment
from apps.lockers.models import Locker, LockerAssignment
from apps.members.models import MemberProfile
from apps.memberships.models import Membership, MembershipPlan, Offer, PromoCode
from apps.payments.models import Payment
from apps.progress.models import ProgressEntry
from apps.staff.models import StaffProfile
from apps.trainers.models import TrainerMemberAssignment, TrainerProfile

User = get_user_model()

IMPORT_URL = '/api/import/'
TEMPLATE_URL = '/api/import/template/'


# ─── Helpers ─────────────────────────────────────────────────────────────────

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


def sheet_entry(report, key):
    """Report entry for one sheet — sheets always arrive in SHEETS order."""
    return {entry['key']: entry for entry in report['sheets']}[key]


def build_upload(sheets):
    """sheets = {'Members': [[header...], [row...], ...]} → uploaded .xlsx"""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(
        'import.xlsx', buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


PLAN_SHEET = [
    ['Name', 'Description', 'Billing Cycle', 'Duration (Days)', 'Price (NPR)', 'Features', 'Is Active'],
    ['Monthly Basic', 'Starter plan', 'MONTHLY', 30, 1500, 'Gym floor; Locker', 'Yes'],
]

MEMBER_SHEET = [
    ['Email', 'First Name', 'Last Name', 'Phone', 'Password', 'Gender', 'Fitness Goal'],
    ['anita.sharma@example.com', 'Anita', 'Sharma', '9841234567', '', 'Female', 'Weight Loss'],
    ['dipak.rey@example.com', 'Dipak', 'Rey', '9841000001', '', 'Male', 'Muscle Gain'],
]

MEMBERSHIP_SHEET = [
    ['Member Email', 'Plan Name', 'Status', 'Start Date', 'End Date', 'Price Paid (NPR)'],
    ['anita.sharma@example.com', 'Monthly Basic', 'ACTIVE', '2026-01-15', '2026-02-14', 1500],
]

PAYMENT_SHEET = [
    ['Receipt Number', 'Member Email', 'Payment For', 'Amount (NPR)',
     'Discount (NPR)', 'Method', 'Status', 'Paid At', 'Plan Name'],
    ['RCP-1001', 'anita.sharma@example.com', 'MEMBERSHIP', 1500, 100,
     'CASH', 'PAID', '2026-01-15 10:30', 'Monthly Basic'],
]

ATTENDANCE_SHEET = [
    ['Email', 'Date', 'Status', 'Check In', 'Check Out'],
    ['anita.sharma@example.com', '2026-01-15', 'PRESENT', '07:30', '09:00'],
]

EQUIPMENT_SHEET = [
    ['Name', 'Category', 'Brand', 'Serial Number', 'Quantity', 'Condition', 'Location'],
    ['Treadmill', 'Cardio', 'Life Fitness', 'LF-T5-0001', 2, 'GOOD', 'Cardio Floor'],
]

LOCKER_SHEET = [
    ['Locker Number', 'Location', 'Status', 'Monthly Fee (NPR)'],
    ['A-01', "Men's Block A", 'AVAILABLE', 500],
]

LOCKER_ASSIGN_SHEET = [
    ['Locker Number', 'Member Email', 'Start Date', 'Is Active'],
    ['A-01', 'anita.sharma@example.com', '2026-01-15', 'Yes'],
]

TRAINER_SHEET = [
    ['Email', 'First Name', 'Last Name', 'Specializations', 'Experience (Years)'],
    ['coach.ram@fitcore.com', 'Ram', 'Thapa', 'Strength Training; Mobility', 6],
]

TRAINER_ASSIGN_SHEET = [
    ['Trainer Email', 'Member Email', 'Assigned Date', 'Is Active'],
    ['coach.ram@fitcore.com', 'anita.sharma@example.com', '2026-01-15', 'Yes'],
]

PROGRESS_SHEET = [
    ['Member Email', 'Date', 'Weight (kg)', 'Height (cm)', 'Body Fat %'],
    ['anita.sharma@example.com', '2026-01-15', 58.5, 165, 26.4],
]

OFFER_SHEET = [
    ['Name', 'Description', 'Discount Type', 'Discount Value', 'Valid From', 'Valid Until'],
    ['Dashain Sale', '20% off', 'PERCENTAGE', 20, '2026-10-01 00:00', '2026-10-15 23:59'],
]

PROMO_SHEET = [
    ['Code', 'Offer Name', 'Status', 'Max Uses', 'Used Count', 'Valid From', 'Valid Until'],
    ['DASHAIN20', 'Dashain Sale', 'ACTIVE', 50, 0, '2026-10-01 00:00', '2026-10-15 23:59'],
]

STAFF_SHEET = [
    ['Email', 'First Name', 'Last Name', 'Staff Role', 'Joined Date', 'Salary (NPR)'],
    ['reception@fitcore.com', 'Sita', 'Adhikari', 'RECEPTIONIST', '2025-01-15', 32000],
]

FULL_SHEETS = {
    'Membership Plans': PLAN_SHEET,
    'Members': MEMBER_SHEET,
    'Staff': STAFF_SHEET,
    'Trainers': TRAINER_SHEET,
    'Offers': OFFER_SHEET,
    'Promo Codes': PROMO_SHEET,
    'Memberships': MEMBERSHIP_SHEET,
    'Payments': PAYMENT_SHEET,
    'Attendance': ATTENDANCE_SHEET,
    'Equipment': EQUIPMENT_SHEET,
    'Lockers': LOCKER_SHEET,
    'Locker Assignments': LOCKER_ASSIGN_SHEET,
    'Trainer Assignments': TRAINER_ASSIGN_SHEET,
    'Progress': PROGRESS_SHEET,
}


# ─── Test cases ──────────────────────────────────────────────────────────────

class ImportEndpointTestCase(APITestCase):
    """Schema + template endpoints and access control."""

    def setUp(self):
        self.owner = make_user('owner@fit.test', role=User.Role.OWNER,
                               first_name='Own', last_name='Er')
        self.member = make_user('plain.member@example.com', role=User.Role.MEMBER)
        self.staff = make_user('desk@fit.test', role=User.Role.STAFF)

    def test_schema_endpoint_lists_supported_sheets(self):
        self.client.credentials(**auth_headers(self.owner))
        response = self.client.get(IMPORT_URL, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [sheet['name'] for sheet in response.data['sheets']]
        self.assertIn('Members', names)
        self.assertIn('Membership Plans', names)
        self.assertEqual(response.data['limits']['max_rows_per_sheet'], 20000)

    def test_template_download_is_a_valid_workbook(self):
        self.client.credentials(**auth_headers(self.owner))
        response = self.client.get(TEMPLATE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('spreadsheetml', response['Content-Type'])
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'PK'))

        import openpyxl
        workbook = openpyxl.load_workbook(io.BytesIO(response.content))
        self.assertIn('Read Me', workbook.sheetnames)
        self.assertIn('Members', workbook.sheetnames)
        self.assertEqual(len(workbook.sheetnames), 15)

    def test_non_owner_is_rejected(self):
        for user in (self.member, self.staff):
            self.client.credentials(**auth_headers(user))
            self.assertEqual(
                self.client.get(IMPORT_URL).status_code,
                status.HTTP_403_FORBIDDEN,
            )
            self.assertEqual(
                self.client.post(IMPORT_URL, {}, format='multipart').status_code,
                status.HTTP_403_FORBIDDEN,
            )

    def test_unauthenticated_is_rejected(self):
        self.assertEqual(self.client.get(IMPORT_URL).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_file_returns_400(self):
        self.client.credentials(**auth_headers(self.owner))
        response = self.client.post(IMPORT_URL, {'dry_run': 'true'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Excel', response.data['error'])

    def test_non_excel_extension_rejected(self):
        self.client.credentials(**auth_headers(self.owner))
        upload = SimpleUploadedFile('data.csv', b'a,b\n1,2\n', content_type='text/csv')
        response = self.client.post(
            IMPORT_URL, {'file': upload, 'dry_run': 'true'}, format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('.xlsx', response.data['error'])


class ImportDryRunTestCase(APITestCase):
    """Preview mode: full validation, zero writes."""

    def setUp(self):
        self.owner = make_user('owner@fit.test', role=User.Role.OWNER)

    def _post(self, sheets, dry_run=True, **extra):
        data = {'file': build_upload(sheets)}
        data['dry_run'] = 'true' if dry_run else 'false'
        data.update(extra)
        self.client.credentials(**auth_headers(self.owner))
        return self.client.post(IMPORT_URL, data, format='multipart')

    def test_dry_run_reports_counts_and_writes_nothing(self):
        response = self._post(FULL_SHEETS, default_password='ChangeMe123')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        report = response.data
        self.assertTrue(report['dry_run'])
        self.assertTrue(report['ok'])

        by_key = {entry['key']: entry for entry in report['sheets']}
        self.assertTrue(all(entry['present'] for entry in report['sheets']))
        self.assertEqual(by_key['members']['to_create'], 2)
        self.assertEqual(by_key['plans']['to_create'], 1)
        self.assertEqual(by_key['memberships']['to_create'], 1)
        self.assertEqual(by_key['payments']['to_create'], 1)
        self.assertEqual(report['totals']['errors'], 0)
        self.assertEqual(report['accounts_using_default_password'], 4)  # 2 members + staff + trainer

        # Nothing may have been written.
        self.assertEqual(User.objects.count(), 1)  # only the owner
        self.assertEqual(MembershipPlan.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(Attendance.objects.count(), 0)
        self.assertEqual(LockerAssignment.objects.count(), 0)

    def test_dry_run_ok_flag_true_when_clean(self):
        response = self._post({'Membership Plans': PLAN_SHEET})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['ok'])
        self.assertEqual(response.data['totals']['to_create'], 1)

    def test_bad_email_is_reported_without_writing(self):
        sheets = {'Members': [
            ['Email', 'First Name', 'Last Name'],
            ['not-an-email', 'Bad', 'Row'],
            ['fine@example.com', 'Fine', 'Row'],
        ]}
        response = self._post(sheets)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['ok'])
        entry = sheet_entry(response.data, 'members')
        self.assertEqual(entry['error_count'], 1)
        error = entry['errors'][0]
        self.assertEqual(error['row'], 2)
        self.assertIn('not a valid email', error['message'])
        # Valid sibling row still previews as "to create"
        self.assertEqual(entry['to_create'], 1)
        self.assertEqual(User.objects.filter(email='fine@example.com').count(), 0)

    def test_duplicate_rows_inside_file_are_errors(self):
        sheets = {'Members': [
            ['Email', 'First Name', 'Last Name'],
            ['dup@example.com', 'One', 'Row'],
            ['dup@example.com', 'Two', 'Row'],
        ]}
        response = self._post(sheets)
        entry = sheet_entry(response.data, 'members')
        self.assertEqual(entry['error_count'], 1)
        self.assertIn('Duplicate of row 2', entry['errors'][0]['message'])

    def test_unknown_plan_reference_is_an_error(self):
        sheets = {
            'Members': MEMBER_SHEET,
            'Memberships': [
                ['Member Email', 'Plan Name', 'Start Date', 'End Date', 'Price Paid (NPR)'],
                ['anita.sharma@example.com', 'Ghost Plan', '2026-01-15', '2026-02-14', 100],
            ],
        }
        response = self._post(sheets)
        self.assertFalse(response.data['ok'])
        entry = sheet_entry(response.data, 'memberships')
        self.assertEqual(entry['error_count'], 1)
        self.assertIn('Ghost Plan', entry['errors'][0]['message'])

    def test_unknown_member_reference_is_an_error(self):
        sheets = {'Memberships': MEMBERSHIP_SHEET}  # member not in file or DB
        response = self._post(sheets)
        entry = sheet_entry(response.data, 'memberships')
        self.assertEqual(entry['error_count'], 1)
        self.assertIn('No account found', entry['errors'][0]['message'])

    def test_missing_required_column_is_a_sheet_error(self):
        sheets = {'Membership Plans': [['Name', 'Description'], ['X', 'Y']]}
        response = self._post(sheets)
        entry = sheet_entry(response.data, 'plans')
        self.assertEqual(entry['error_count'], 1)
        self.assertEqual(entry['errors'][0]['row'], 1)
        self.assertIn('Duration (Days)', entry['errors'][0]['column'])

    def test_workbook_without_supported_sheets(self):
        response = self._post({'Random Tab': [['A'], [1]]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('No supported sheets', response.data['error'])

    def test_garbage_file_reports_friendly_error(self):
        self.client.credentials(**auth_headers(self.owner))
        upload = SimpleUploadedFile('import.xlsx', b'this is not a zip archive')
        response = self.client.post(
            IMPORT_URL, {'file': upload, 'dry_run': 'true'}, format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('could not be read', response.data['error'])

    def test_date_and_time_cells_are_tolerant(self):
        sheets = {
            'Members': MEMBER_SHEET,
            'Attendance': [
                ['Email', 'Date', 'Check In', 'Check Out'],
                ['anita.sharma@example.com', '15/01/2026', '7:30 AM', '09:00'],
                ['dipak.rey@example.com', '2026-01-16', '19:00', '20:30'],
            ],
        }
        response = self._post(sheets)
        entry = sheet_entry(response.data, 'attendance')
        self.assertEqual(entry['error_count'], 0)
        self.assertEqual(entry['to_create'], 2)


class ImportCommitTestCase(APITestCase):
    """Commit mode: writes everything, atomically."""

    def setUp(self):
        self.owner = make_user('owner@fit.test', role=User.Role.OWNER)

    def _post(self, sheets, dry_run=True, **extra):
        data = {'file': build_upload(sheets)}
        data['dry_run'] = 'true' if dry_run else 'false'
        data.update(extra)
        self.client.credentials(**auth_headers(self.owner))
        return self.client.post(IMPORT_URL, data, format='multipart')

    def test_commit_creates_the_full_dataset(self):
        response = self._post(FULL_SHEETS, dry_run=False, default_password='ChangeMe123')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        report = response.data
        self.assertFalse(report['dry_run'])
        self.assertTrue(report['ok'])
        self.assertEqual(report['totals']['errors'], 0)

        # People
        self.assertEqual(User.objects.filter(role=User.Role.MEMBER).count(), 2)
        self.assertEqual(User.objects.filter(role=User.Role.STAFF).count(), 1)
        self.assertEqual(User.objects.filter(role=User.Role.TRAINER).count(), 1)
        member = User.objects.get(email='anita.sharma@example.com')
        self.assertTrue(member.display_id.startswith('MEM-'))
        self.assertTrue(member.check_password('ChangeMe123'))
        self.assertTrue(hasattr(member, 'member_profile'))
        self.assertEqual(member.member_profile.gender, 'F')
        self.assertEqual(member.member_profile.fitness_goal, 'WEIGHT_LOSS')
        self.assertTrue(hasattr(User.objects.get(email='reception@fitcore.com'), 'staff_profile'))
        trainer_profile = User.objects.get(email='coach.ram@fitcore.com').trainer_profile
        self.assertEqual(trainer_profile.specializations, ['Strength Training', 'Mobility'])
        self.assertEqual(trainer_profile.experience_years, 6)

        # Plans / offers / promo codes
        plan = MembershipPlan.objects.get(name='Monthly Basic')
        self.assertEqual(plan.duration_days, 30)
        self.assertEqual(plan.price, 1500)
        self.assertEqual(plan.features, ['Gym floor', 'Locker'])
        offer = Offer.objects.get(name='Dashain Sale')
        promo = PromoCode.objects.get(code='DASHAIN20')
        self.assertEqual(promo.offer, offer)
        self.assertEqual(promo.created_by, self.owner)

        # Business records
        membership = Membership.objects.get(member=member, plan=plan)
        self.assertEqual(membership.status, 'ACTIVE')
        self.assertEqual(membership.end_date.isoformat(), '2026-02-14')

        payment = Payment.objects.get(receipt_number='RCP-1001')
        self.assertEqual(payment.member, member)
        self.assertEqual(payment.membership, membership)
        self.assertEqual(payment.amount, 1500)
        self.assertEqual(payment.discount, 100)
        # amount_paid is recomputed on save: amount - discount
        self.assertEqual(payment.amount_paid, 1400)
        self.assertIsNotNone(payment.paid_at)

        attendance = Attendance.objects.get(user=member, date='2026-01-15')
        self.assertEqual(attendance.attendance_type, 'MEMBER')  # derived from role
        self.assertEqual(str(attendance.check_in), '07:30:00')
        self.assertEqual(attendance.marked_by, self.owner)

        equipment = Equipment.objects.get(serial_number='LF-T5-0001')
        self.assertEqual(equipment.quantity, 2)

        locker = Locker.objects.get(locker_number='A-01')
        assignment = LockerAssignment.objects.get(locker=locker, member=member)
        self.assertTrue(assignment.is_active)
        self.assertEqual(locker.status, Locker.LockerStatus.OCCUPIED)

        trainer_assignment = TrainerMemberAssignment.objects.get(member=member)
        self.assertEqual(trainer_assignment.trainer.email, 'coach.ram@fitcore.com')
        self.assertEqual(trainer_assignment.assigned_date.isoformat(), '2026-01-15')

        progress = ProgressEntry.objects.get(member=member, date='2026-01-15')
        self.assertEqual(progress.body_fat_percentage, Decimal('26.4'))
        self.assertEqual(progress.recorded_by, self.owner)

        self.assertEqual(report['accounts_using_default_password'], 4)

    def test_commit_is_idempotent(self):
        first = self._post(FULL_SHEETS, dry_run=False)
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        counts = {
            'users': User.objects.count(),
            'plans': MembershipPlan.objects.count(),
            'memberships': Membership.objects.count(),
            'payments': Payment.objects.count(),
            'attendance': Attendance.objects.count(),
            'equipment': Equipment.objects.count(),
            'lockers': Locker.objects.count(),
            'locker_assignments': LockerAssignment.objects.count(),
            'assignments': TrainerMemberAssignment.objects.count(),
            'progress': ProgressEntry.objects.count(),
            'offers': Offer.objects.count(),
            'promo': PromoCode.objects.count(),
        }

        second = self._post(FULL_SHEETS, dry_run=False)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.assertTrue(second.data['ok'])
        self.assertEqual(second.data['totals']['to_create'], 0)
        self.assertEqual(second.data['totals']['skipped'],
                         first.data['totals']['rows'])

        after = {
            'users': User.objects.count(),
            'plans': MembershipPlan.objects.count(),
            'memberships': Membership.objects.count(),
            'payments': Payment.objects.count(),
            'attendance': Attendance.objects.count(),
            'equipment': Equipment.objects.count(),
            'lockers': Locker.objects.count(),
            'locker_assignments': LockerAssignment.objects.count(),
            'assignments': TrainerMemberAssignment.objects.count(),
            'progress': ProgressEntry.objects.count(),
            'offers': Offer.objects.count(),
            'promo': PromoCode.objects.count(),
        }
        self.assertEqual(counts, after)

    def test_one_bad_row_blocks_the_whole_commit(self):
        sheets = {'Members': [
            ['Email', 'First Name', 'Last Name'],
            ['good@example.com', 'Good', 'Row'],
            ['broken@@example', 'Broken', 'Row'],
        ]}
        response = self._post(sheets, dry_run=False)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['ok'])
        self.assertIn('Nothing was imported', response.data['error'])
        # All-or-nothing: the good row must NOT exist either.
        self.assertFalse(User.objects.filter(email='good@example.com').exists())

    def test_commit_skips_validation_but_not_schema_errors(self):
        # Missing sheet header → commit rejected before any write.
        response = self._post({'Payments': [['Receipt Number'], ['RCP-1']]}, dry_run=False)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Payment.objects.count(), 0)

    def test_existing_account_of_wrong_role_is_an_error(self):
        make_user('switched@example.com', role=User.Role.TRAINER)
        sheets = {'Members': [
            ['Email', 'First Name', 'Last Name'],
            ['switched@example.com', 'Now', 'Member'],
        ]}
        dry = self._post(sheets, dry_run=True)
        entry = sheet_entry(dry.data, 'members')
        self.assertEqual(entry['error_count'], 1)
        self.assertIn('already exists', entry['errors'][0]['message'])

        commit = self._post(sheets, dry_run=False)
        self.assertEqual(commit.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.filter(email='switched@example.com').count(), 1)

    def test_account_created_in_file_cannot_appear_in_two_sheets(self):
        sheets = {
            'Members': MEMBER_SHEET,
            'Staff': [
                ['Email', 'First Name', 'Last Name', 'Staff Role'],
                ['anita.sharma@example.com', 'Anita', 'Sharma', 'RECEPTIONIST'],
            ],
        }
        response = self._post(sheets)
        entry = sheet_entry(response.data, 'staff')
        self.assertEqual(entry['error_count'], 1)
        self.assertIn('already being imported', entry['errors'][0]['message'])

    def test_active_locker_conflict_is_rejected(self):
        existing_member = make_user('old.member@example.com')
        locker = Locker.objects.create(locker_number='A-01', status=Locker.LockerStatus.OCCUPIED)
        LockerAssignment.objects.create(
            locker=locker, member=existing_member,
            start_date='2026-01-01', is_active=True,
        )
        sheets = {
            'Members': MEMBER_SHEET,
            'Locker Assignments': LOCKER_ASSIGN_SHEET,  # tries to reuse A-01
        }
        response = self._post(sheets)
        entry = sheet_entry(response.data, 'locker_assignments')
        self.assertEqual(entry['error_count'], 1)
        self.assertIn('already has an active assignment', entry['errors'][0]['message'])

    def test_default_password_requires_six_chars(self):
        self.client.credentials(**auth_headers(self.owner))
        response = self.client.post(IMPORT_URL, {
            'file': build_upload({'Membership Plans': PLAN_SHEET}),
            'dry_run': 'true',
            'default_password': 'abc',
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('6 characters', response.data['error'])

    def test_account_without_password_gets_unusable_password(self):
        sheets = {'Members': MEMBER_SHEET}
        dry = self._post(sheets, dry_run=True)
        self.assertEqual(dry.data['accounts_without_password'], 2)
        self.assertEqual(dry.data['accounts_using_default_password'], 0)

        response = self._post(sheets, dry_run=False)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        member = User.objects.get(email='anita.sharma@example.com')
        self.assertFalse(member.has_usable_password())
        self.assertFalse(member.check_password('anything'))
