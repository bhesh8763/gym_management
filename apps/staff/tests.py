"""
Tests for the Staff app API.

Run with:
    python manage.py test apps.staff.tests

Coverage:
    - Staff profile create (POST /api/staff/profiles/)
    - One profile per user (OneToOneField) is enforced
    - Leave request create (POST /api/staff/leave-requests/)
    - requester is auto-set to the authenticated user, not client-supplied
    - Non-owner/staff only see their own leave requests
    - Review action (approve/reject) restricted to owner/staff
"""
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.staff.models import StaffProfile, LeaveRequest

User = get_user_model()


def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


class StaffAPITestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER,
                                first_name='Owner', last_name='User')
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF,
                                first_name='Staff', last_name='User')
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER,
                                  first_name='Trainer', last_name='User')
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                 first_name='Member', last_name='User')
        self.profiles_url = '/api/staff/profiles/'
        self.leaves_url = '/api/staff/leave-requests/'

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )
    
    def get_future_dates(self):
        start = timezone.now().date() + timedelta(days=1)
        end = start + timedelta(days=2)
        return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


class StaffProfileTests(StaffAPITestCase):
    def test_owner_can_create_profile(self):
        self.auth_as(self.owner)
        r = self.client.post(self.profiles_url, {
            'user': self.trainer.id,
            'role': 'RECEPTIONIST',
            'joined_date': '2026-01-01',
            'salary': '25000.00',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_duplicate_profile_for_same_user_is_rejected(self):
        self.auth_as(self.owner)
        payload = {
            'user': self.trainer.id,
            'role': 'RECEPTIONIST',
            'joined_date': '2026-01-01',
            'salary': '25000.00',
        }
        first = self.client.post(self.profiles_url, payload)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(self.profiles_url, payload)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_create_profile(self):
        self.auth_as(self.member)
        r = self.client.post(self.profiles_url, {
            'user': self.member.id, 'role': 'RECEPTIONIST',
            'joined_date': '2026-01-01',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_staff_or_trainer_role_can_have_profile(self):
        self.auth_as(self.owner)
        r = self.client.post(self.profiles_url, {
            'user': self.member.id, 'role': 'RECEPTIONIST',
            'joined_date': '2026-01-01',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class StaffCreateSerializerTests(StaffAPITestCase):
    def test_owner_can_create_staff_user_and_profile(self):
        self.auth_as(self.owner)
        r = self.client.post(self.profiles_url, {
            'email': 'newstaff@gym.com', 'first_name': 'New', 'last_name': 'Staff',
            'password': 'StrongPass123!', 'role': 'GYM_KEEPER',
            'joined_date': '2026-06-01',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newstaff@gym.com')
        self.assertEqual(user.role, User.Role.STAFF)
        self.assertTrue(user.check_password('StrongPass123!'))
        self.assertTrue(StaffProfile.objects.filter(user=user).exists())

    def test_duplicate_email_rejected(self):
        self.auth_as(self.owner)
        payload = {'email': 'dup@gym.com', 'first_name': 'Dup', 'last_name': 'User', 'password': 'StrongPass123!'}
        self.client.post(self.profiles_url, payload)
        r = self.client.post(self.profiles_url, payload)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class StaffProfileActionTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as(self.owner)
        r = self.client.post(self.profiles_url, {
            'email': 'actionstaff@gym.com', 'first_name': 'Action',
            'last_name': 'Staff', 'password': 'StrongPass123!', 'role': 'RECEPTIONIST',
        })
        self.profile_id = r.data['id']

    def test_owner_can_deactivate_staff(self):
        self.auth_as(self.owner)
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/deactivate/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        user = User.objects.get(email='actionstaff@gym.com')
        self.assertFalse(user.is_active)

    def test_owner_can_activate_staff(self):
        self.auth_as(self.owner)
        self.client.post(f'{self.profiles_url}{self.profile_id}/deactivate/')
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/activate/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        user = User.objects.get(email='actionstaff@gym.com')
        self.assertTrue(user.is_active)

    def test_owner_can_reset_password(self):
        self.auth_as(self.owner)
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/reset-password/', {
            'new_password': 'NewStrongPass456!',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        user = User.objects.get(email='actionstaff@gym.com')
        self.assertTrue(user.check_password('NewStrongPass456!'))

    def test_reset_password_requires_new_password(self):
        self.auth_as(self.owner)
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/reset-password/', {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_deactivate_staff(self):
        self.auth_as(self.member)
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/deactivate/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class StaffAuthTests(APITestCase):
    def test_unauthenticated_profiles_returns_401(self):
        r = self.client.get('/api/staff/profiles/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_leaves_returns_401(self):
        r = self.client.get('/api/staff/leave-requests/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class LeaveRequestTests(StaffAPITestCase):
    def test_trainer_can_submit_own_leave_request(self):
        self.auth_as(self.trainer)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'leave_type': 'SICK',
            'start_date': start,
            'end_date': end,
            'reason': 'Fever',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['requester'], self.trainer.id)
        self.assertEqual(r.data['status'], 'PENDING')

    def test_requester_field_cannot_be_spoofed(self):
        self.auth_as(self.trainer)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'requester': self.owner.id,
            'leave_type': 'SICK',
            'start_date': start,
            'end_date': end,
            'reason': 'Fever',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['requester'], self.trainer.id)

    def test_member_cannot_submit_leave_request(self):
        self.auth_as(self.member)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'leave_type': 'SICK', 'start_date': start, 'end_date': end, 'reason': 'Fever',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_submit_own_leave_request(self):
        self.auth_as(self.staff)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'leave_type': 'CASUAL', 'start_date': start, 'end_date': end, 'reason': 'Personal',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_non_staff_only_sees_own_requests(self):
        LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date='2026-07-20', end_date='2026-07-21', reason='Test',
        )
        LeaveRequest.objects.create(
            requester=self.staff, leave_type='CASUAL',
            start_date='2026-07-22', end_date='2026-07-22', reason='Test',
        )
        self.auth_as(self.trainer)
        r = self.client.get(self.leaves_url)
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['requester'], self.trainer.id)

    def test_owner_sees_all_requests(self):
        LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date='2026-07-20', end_date='2026-07-21', reason='Test',
        )
        LeaveRequest.objects.create(
            requester=self.staff, leave_type='CASUAL',
            start_date='2026-07-22', end_date='2026-07-22', reason='Test',
        )
        self.auth_as(self.owner)
        r = self.client.get(self.leaves_url)
        self.assertEqual(r.data['count'], 2)


class LeaveReviewTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.leave = LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date='2026-07-20', end_date='2026-07-21', reason='Test',
        )
        self.review_url = f'/api/staff/leave-requests/{self.leave.id}/review/'

    def test_owner_can_approve(self):
        self.auth_as(self.owner)
        r = self.client.post(self.review_url, {'status': 'APPROVED'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], 'APPROVED')
        self.assertEqual(r.data['reviewed_by'], self.owner.id)

    def test_trainer_cannot_approve_own_request(self):
        self.auth_as(self.trainer)
        r = self.client.post(self.review_url, {'status': 'APPROVED'})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_status_value_rejected(self):
        self.auth_as(self.owner)
        r = self.client.post(self.review_url, {'status': 'MAYBE'})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_can_reject(self):
        self.auth_as(self.owner)
        r = self.client.post(self.review_url, {
            'status': 'REJECTED', 'review_note': 'Not enough notice',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], 'REJECTED')
        self.assertEqual(r.data['review_note'], 'Not enough notice')

    def test_member_cannot_review(self):
        self.auth_as(self.member)
        r = self.client.post(self.review_url, {'status': 'APPROVED'})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class LeaveDateValidationTests(StaffAPITestCase):
    def test_end_date_before_start_date_rejected(self):
        self.auth_as(self.trainer)
        start = (timezone.now().date() + timedelta(days=5)).strftime('%Y-%m-%d')
        end = (timezone.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        r = self.client.post(self.leaves_url, {
            'leave_type': 'SICK', 'start_date': start, 'end_date': end, 'reason': 'Wrong',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_overlapping_dates_rejected(self):
        self.auth_as(self.trainer)
        self.client.post(self.leaves_url, {
            'leave_type': 'SICK',
            'start_date': (timezone.now().date() + timedelta(days=10)).strftime('%Y-%m-%d'),
            'end_date': (timezone.now().date() + timedelta(days=12)).strftime('%Y-%m-%d'),
            'reason': 'First leave',
        })
        r = self.client.post(self.leaves_url, {
            'leave_type': 'CASUAL',
            'start_date': (timezone.now().date() + timedelta(days=11)).strftime('%Y-%m-%d'),
            'end_date': (timezone.now().date() + timedelta(days=13)).strftime('%Y-%m-%d'),
            'reason': 'Second leave',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class LeaveCancelTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.leave = LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date='2026-07-20', end_date='2026-07-21', reason='Test',
        )
        self.cancel_url = f'/api/staff/leave-requests/{self.leave.id}/cancel/'

    def test_requester_can_cancel_own_pending(self):
        self.auth_as(self.trainer)
        r = self.client.post(self.cancel_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, 'CANCELLED')

    def test_cannot_cancel_other_users_leave(self):
        self.auth_as(self.staff)
        r = self.client.post(self.cancel_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_cancel_approved_leave(self):
        self.leave.status = 'APPROVED'
        self.leave.save(update_fields=['status'])
        self.auth_as(self.trainer)
        r = self.client.post(self.cancel_url)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)