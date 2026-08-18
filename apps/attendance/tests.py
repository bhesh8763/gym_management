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

from apps.attendance.models import Attendance

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