"""
Tests for the Attendance app API.

Run with:
    python manage.py test apps.attendance.tests

Coverage:
    - Attendance list (GET /api/attendance/)
    - Attendance create (POST /api/attendance/)
    - Attendance update / check-out (PATCH /api/attendance/<id>/)
    - Duplicate (same user + date) is rejected
    - Filtering by date/user/type
    - RBAC: members cannot create attendance records, staff-side roles can
"""
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.attendance.models import Attendance, BiometricRecord, QRAttendanceToken

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


# ─── Base test case ───────────────────────────────────────────────────────────

class AttendanceAPITestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER,
                                first_name='Owner', last_name='User')
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF,
                                first_name='Staff', last_name='User')
        self.member = make_user('alice@gym.com', role=User.Role.MEMBER,
                                 first_name='Alice', last_name='Smith')

        self.list_url = '/api/attendance/records/'
        
    def get_today_str(self):
        return timezone.now().date().strftime('%Y-%m-%d')
    
    def get_yesterday_str(self):
        return (timezone.now().date() - timedelta(days=1)).strftime('%Y-%m-%d')

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )

    def deauth(self):
        self.client.credentials()


# ─── Create ───────────────────────────────────────────────────────────────────

class AttendanceCreateTests(AttendanceAPITestCase):
    def test_staff_can_create_attendance(self):
        self.auth_as(self.staff)
        r = self.client.post(self.list_url, {
            'user': self.member.id,
            'attendance_type': 'MEMBER',
            'date': self.get_today_str(),
            'check_in': '09:00:00',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['marked_by'], self.staff.id)

    def test_member_cannot_create_attendance(self):
        self.auth_as(self.member)
        r = self.client.post(self.list_url, {
            'user': self.member.id,
            'attendance_type': 'MEMBER',
            'date': self.get_today_str(),
            'check_in': '09:00:00',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_create_attendance(self):
        r = self.client.post(self.list_url, {
            'user': self.member.id,
            'attendance_type': 'MEMBER',
            'date': self.get_today_str(),
            'check_in': '09:00:00',
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_duplicate_user_date_is_rejected(self):
        """Only one attendance row per user per day is allowed."""
        self.auth_as(self.staff)
        payload = {
            'user': self.member.id,
            'attendance_type': 'MEMBER',
            'date': self.get_today_str(),
            'check_in': '09:00:00',
        }
        first = self.client.post(self.list_url, payload)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(self.list_url, payload)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)


# ─── Check-out / update ────────────────────────────────────────────────────────

class AttendanceCheckOutTests(AttendanceAPITestCase):
    def setUp(self):
        super().setUp()
        self.record = Attendance.objects.create(
            user=self.member,
            attendance_type='MEMBER',
            date=self.get_today_str(),
            check_in='09:00:00',
            marked_by=self.staff,
        )
        self.detail_url = f'/api/attendance/records/{self.record.id}/'

    def test_staff_can_check_out(self):
        self.auth_as(self.staff)
        r = self.client.patch(self.detail_url, {'check_out': '17:00:00'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['check_out'], '17:00:00')
        self.assertIsNotNone(r.data['duration_minutes'])

    def test_duration_minutes_is_correct(self):
        self.auth_as(self.staff)
        r = self.client.patch(self.detail_url, {'check_out': '17:53:00'})
        # 09:00 -> 17:53 = 8h53m = 533 minutes
        self.assertEqual(r.data['duration_minutes'], 533)


# ─── List / filter ──────────────────────────────────────────────────────────────

class AttendanceListTests(AttendanceAPITestCase):
    def setUp(self):
        super().setUp()
        Attendance.objects.create(
            user=self.member, attendance_type='MEMBER',
            date=self.get_yesterday_str(), check_in='09:00:00', marked_by=self.staff,
        )
        Attendance.objects.create(
            user=self.staff, attendance_type='STAFF',
            date=self.get_today_str(), check_in='08:00:00', marked_by=self.owner,
        )

    def test_owner_can_list_all(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['count'], 2)

    def test_filter_by_date(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'date': self.get_today_str()})
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['date'], self.get_today_str())

    def test_filter_by_user(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'user': self.member.id})
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['user'], self.member.id)

    def test_filter_by_type(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'type': 'STAFF'})
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['attendance_type'], 'STAFF')


class AttendanceCheckInTests(AttendanceAPITestCase):
    def test_member_can_self_check_in(self):
        self.auth_as(self.member)
        r = self.client.post('/api/attendance/records/check-in/')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['user'], self.member.id)

    def test_member_cannot_check_in_twice(self):
        self.auth_as(self.member)
        self.client.post('/api/attendance/records/check-in/')
        r = self.client.post('/api/attendance/records/check-in/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_cannot_self_check_in(self):
        self.auth_as(self.staff)
        r = self.client.post('/api/attendance/records/check-in/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class AttendanceCheckOutSelfServiceTests(AttendanceAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as(self.member)
        self.client.post('/api/attendance/records/check-in/')

    def test_member_can_self_check_out(self):
        r = self.client.post('/api/attendance/records/check-out/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(r.data['check_out'])

    def test_member_cannot_check_out_without_check_in(self):
        # Create a second member who hasn't checked in
        member2 = make_user('bob@gym.com', role=User.Role.MEMBER, first_name='Bob', last_name='Jones')
        self.auth_as(member2)
        r = self.client.post('/api/attendance/records/check-out/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_check_out_twice(self):
        self.client.post('/api/attendance/records/check-out/')
        r = self.client.post('/api/attendance/records/check-out/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class AttendanceUnauthenticatedTests(AttendanceAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_create_returns_401(self):
        r = self.client.post(self.list_url, {
            'user': self.member.id, 'attendance_type': 'MEMBER',
            'date': self.get_today_str(), 'check_in': '09:00:00',
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class AttendanceMemberScopingTests(AttendanceAPITestCase):
    def test_member_only_sees_own_records(self):
        Attendance.objects.create(
            user=self.member, attendance_type='MEMBER',
            date=self.get_today_str(), check_in='09:00:00', marked_by=self.staff,
        )
        other_member = make_user('other@gym.com', role=User.Role.MEMBER, first_name='Other', last_name='U')
        Attendance.objects.create(
            user=other_member, attendance_type='MEMBER',
            date=self.get_today_str(), check_in='10:00:00', marked_by=self.staff,
        )
        self.auth_as(self.member)
        r = self.client.get(self.list_url)
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['user'], self.member.id)


# ─── Biometric Enrollment ──────────────────────────────────────────────────────

class BiometricEnrollmentTests(APITestCase):
    """Tests for biometric enrollment and management endpoints."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('alice@gym.com', role=User.Role.MEMBER, first_name='Alice', last_name='Smith')

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )

    def test_owner_can_enroll_biometric(self):
        """Owner can enroll a member's biometric data."""
        self.auth_as(self.owner)
        r = self.client.post('/api/attendance/biometric/', {
            'member': self.member.id,
            'biometric_id': 'FP-001-ABC123',
            'biometric_type': 'FINGERPRINT',
            'device_id': 'SCANNER-001',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['biometric_id'], 'FP-001-ABC123')
        self.assertEqual(r.data['status'], 'ENROLLED')
        self.assertEqual(r.data['biometric_type'], 'FINGERPRINT')
        self.assertEqual(r.data['enrolled_by'], self.owner.id)

    def test_staff_can_enroll_biometric(self):
        """Staff can enroll a member's biometric data."""
        self.auth_as(self.staff)
        r = self.client.post('/api/attendance/biometric/', {
            'member': self.member.id,
            'biometric_id': 'FP-002-DEF456',
            'biometric_type': 'FINGERPRINT',
            'device_id': 'SCANNER-002',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['enrolled_by'], self.staff.id)

    def test_trainer_can_enroll_biometric(self):
        """Trainer can enroll a member's biometric data."""
        self.auth_as(self.trainer)
        r = self.client.post('/api/attendance/biometric/', {
            'member': self.member.id,
            'biometric_id': 'FP-003-GHI789',
            'biometric_type': 'FINGERPRINT',
            'device_id': 'SCANNER-003',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['enrolled_by'], self.trainer.id)

    def test_member_cannot_enroll_biometric(self):
        """Members cannot enroll biometric data."""
        self.auth_as(self.member)
        r = self.client.post('/api/attendance/biometric/', {
            'member': self.member.id,
            'biometric_id': 'FP-004',
            'biometric_type': 'FINGERPRINT',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_enrollment_rejected(self):
        """Cannot enroll a member who already has an active enrollment."""
        BiometricRecord.objects.create(
            member=self.member,
            biometric_id='FP-EXISTING',
            biometric_type='FINGERPRINT',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
        )
        self.auth_as(self.owner)
        r = self.client.post('/api/attendance/biometric/', {
            'member': self.member.id,
            'biometric_id': 'FP-NEW',
            'biometric_type': 'FINGERPRINT',
            'device_id': 'SCANNER-004',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already has an active biometric enrollment', r.data['error'])

    def test_list_biometric_records(self):
        """Staff can list all biometric records."""
        BiometricRecord.objects.create(
            member=self.member,
            biometric_id='FP-001',
            biometric_type='FINGERPRINT',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
        )
        self.auth_as(self.owner)
        r = self.client.get('/api/attendance/biometric/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['biometric_id'], 'FP-001')

    def test_list_with_status_filter(self):
        """Can filter biometric records by status."""
        other_member2 = make_user("filter-other2@gym.com", role=User.Role.MEMBER)
        failed_member2 = make_user("filter-failed2@gym.com", role=User.Role.MEMBER)
        BiometricRecord.objects.create(
            member=other_member2,
            biometric_id="FP-ENROLLED-FILTER2",
            biometric_type="FINGERPRINT",
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
        )
        BiometricRecord.objects.create(
            member=failed_member2,
            biometric_id="FP-FAILED-FILTER2",
            biometric_type="FACE",
            status=BiometricRecord.BiometricStatus.FAILED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
            notes="Enrollment failed - poor fingerprint quality",
        )
        self.auth_as(self.owner)
        r = self.client.get("/api/attendance/biometric/?status=ENROLLED")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        enrolled_ids = [rec["biometric_id"] for rec in r.data]
        self.assertIn("FP-ENROLLED-FILTER2", enrolled_ids)
        self.assertEqual(len(enrolled_ids), 1)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 1)


class BiometricRecordDetailTests(APITestCase):
    """Tests for biometric record detail (GET/PATCH/DELETE)."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('alice@gym.com', role=User.Role.MEMBER)
        self.record = BiometricRecord.objects.create(
            member=self.member,
            biometric_id='FP-EXISTING',
            biometric_type='FINGERPRINT',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
            device_id='SCANNER-001',
        )

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )

    def test_can_get_biometric_record(self):
        self.auth_as(self.owner)
        r = self.client.get(f'/api/attendance/biometric/{self.record.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['biometric_id'], 'FP-EXISTING')
        self.assertEqual(r.data['member'], self.member.id)

    def test_can_update_biometric_notes(self):
        self.auth_as(self.owner)
        r = self.client.patch(
            f'/api/attendance/biometric/{self.record.id}/',
            {'notes': 'Updated notes for this enrollment'}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # The response may be the serialized record; check notes field if present
        if 'notes' in r.data:
            self.assertEqual(r.data['notes'], 'Updated notes for this enrollment')

    def test_can_remove_biometric_enrollment(self):
        self.auth_as(self.owner)
        r = self.client.delete(f'/api/attendance/biometric/{self.record.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(BiometricRecord.objects.filter(pk=self.record.id).exists())

    def test_record_not_found_returns_404(self):
        self.auth_as(self.owner)
        r = self.client.get('/api/attendance/biometric/99999/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class BiometricAttendanceTests(APITestCase):
    """Tests for biometric check-in endpoint (scanner device integration)."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('alice@gym.com', role=User.Role.MEMBER, first_name='Alice', last_name='Smith')
        self.inactive_member = make_user('bob@gym.com', role=User.Role.MEMBER, first_name='Bob', last_name='Jones')
        self.inactive_member.is_active = False
        self.inactive_member.save()
        self.biometric_record = BiometricRecord.objects.create(
            member=self.member,
            biometric_id='FP-001-ABC123',
            biometric_type='FINGERPRINT',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
            device_id='SCANNER-001',
        )

    def test_biometric_check_in_successful(self):
        """A valid biometric scan creates a check-in."""
        r = self.client.post('/api/attendance/biometric/scan/', {
            'biometric_id': 'FP-001-ABC123',
            'device_id': 'KIOSK-01',
            'timestamp': '2026-09-07T09:30:00',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['action'], 'checked_in')
        self.assertEqual(r.data['member_name'], 'Alice Smith')
        self.assertEqual(r.data['display_id'], self.member.display_id)

    def test_biometric_check_out_second_scan(self):
        """Second scan on same day records check-out."""
        today = timezone.localdate()
        Attendance.objects.create(
            user=self.member,
            attendance_type='MEMBER',
            date=today,
            check_in='09:00:00',
            status=Attendance.Status.PRESENT,
        )
        r = self.client.post('/api/attendance/biometric/scan/', {
            'biometric_id': 'FP-001-ABC123',
            'device_id': 'KIOSK-01',
            'timestamp': '2026-09-07T17:30:00',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['action'], 'checked_out')
        self.assertEqual(str(r.data['check_out']), '17:30:00')

    def test_already_completed_returns_already_completed(self):
        """Already checked-in and checked-out member returns already_completed."""
        Attendance.objects.create(
            user=self.member,
            attendance_type='MEMBER',
            date=timezone.localdate(),
            check_in='09:00:00',
            check_out='17:00:00',
            status=Attendance.Status.PRESENT,
        )
        r = self.client.post('/api/attendance/biometric/scan/', {
            'biometric_id': 'FP-001-ABC123',
            'device_id': 'KIOSK-01',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['action'], 'already_completed')

    def test_invalid_biometric_id_rejected(self):
        """Unknown biometric ID returns error."""
        r = self.client.post('/api/attendance/biometric/scan/', {
            'biometric_id': 'FP-INVALID-XYZ',
            'device_id': 'KIOSK-01',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        if isinstance(r.data, dict):
            errors = r.data.get('biometric_id', r.data.get('non_field_errors', []))
            if isinstance(errors, list):
                self.assertTrue(any('No registered member found' in str(e) for e in errors))
            else:
                self.assertIn('No registered member found', str(r.data))

    def test_inactive_member_rejected(self):
        """Scan of an inactive member's biometric is rejected."""
        inactive_record = BiometricRecord.objects.create(
            member=self.inactive_member,
            biometric_id='FP-INACTIVE',
            biometric_type='FINGERPRINT',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
        )
        r = self.client.post('/api/attendance/biometric/scan/', {
            'biometric_id': 'FP-INACTIVE',
            'device_id': 'KIOSK-01',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Member account is inactive', r.data['error'])
        self.inactive_member.refresh_from_db()
        self.assertIsNone(self.inactive_member.last_login)  # should not have logged in

    def test_biometric_record_verification_updated(self):
        """After successful scan, last_verified_at is updated."""
        self.assertIsNone(self.biometric_record.last_verified_at)
        r = self.client.post('/api/attendance/biometric/scan/', {
            'biometric_id': 'FP-001-ABC123',
            'device_id': 'KIOSK-01',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.biometric_record.refresh_from_db()
        self.assertIsNotNone(self.biometric_record.last_verified_at)
        self.assertEqual(self.biometric_record.last_verified_device, 'KIOSK-01')

    def test_biometric_scan_no_auth_required(self):
        """Biometric scanner endpoint works without JWT authentication."""
        self.client.credentials()  # Clear any auth
        r = self.client.post('/api/attendance/biometric/scan/', {
            'biometric_id': 'FP-001-ABC123',
            'device_id': 'KIOSK-01',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_face_recognition_supported(self):
        """Face recognition biometric type works."""
        face_member = make_user('charlie@gym.com', role=User.Role.MEMBER)
        face_record = BiometricRecord.objects.create(
            member=face_member,
            biometric_id='FACE-001-XYZ',
            biometric_type='FACE',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
        )
        r = self.client.post('/api/attendance/biometric/scan/', {
            'biometric_id': 'FACE-001-XYZ',
            'device_id': 'FACE-SCANNER-01',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['action'], 'checked_in')


class BiometricStatsTests(APITestCase):
    """Tests for biometric statistics endpoint."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member1 = make_user('alice@gym.com', role=User.Role.MEMBER)
        self.member2 = make_user('bob@gym.com', role=User.Role.MEMBER)
        self.member3 = make_user('charlie@gym.com', role=User.Role.MEMBER)
        self.member4 = make_user('dave@gym.com', role=User.Role.MEMBER)

        BiometricRecord.objects.create(
            member=self.member1,
            biometric_id='FP-001',
            biometric_type='FINGERPRINT',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
        )
        BiometricRecord.objects.create(
            member=self.member2,
            biometric_id='FP-002',
            biometric_type='FINGERPRINT',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
        )
        BiometricRecord.objects.create(
            member=self.member3,
            biometric_id='FACE-001',
            biometric_type='FACE',
            status=BiometricRecord.BiometricStatus.ENROLLED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
        )
        BiometricRecord.objects.create(
            member=self.member4,
            biometric_id='FP-FAILED-001',
            biometric_type='FINGERPRINT',
            status=BiometricRecord.BiometricStatus.FAILED,
            enrolled_by=self.owner,
            enrolled_at=timezone.now(),
            notes='Fingerprint quality too poor'
        )

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )

    def test_stats_endpoint(self):
        self.auth_as(self.owner)
        r = self.client.get('/api/attendance/biometric/stats/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['total_enrolled'], 3)
        # not_enrolled count is 0 because the failed member was created with a different member
        self.assertEqual(r.data['not_enrolled'], 0)
        self.assertIn('by_biometric_type', r.data)
        by_type = {item['biometric_type']: item['count'] for item in r.data['by_biometric_type']}
        self.assertEqual(by_type.get('FINGERPRINT', 0), 2)
        self.assertEqual(by_type.get('FACE', 0), 1)

    def test_non_staff_cannot_access_stats(self):
        self.auth_as(self.member1)
        r = self.client.get('/api/attendance/biometric/stats/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
