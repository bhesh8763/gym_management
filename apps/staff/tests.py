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
            'department': 'FRONT_DESK',
            'designation': 'Trainer',
            'joined_date': '2026-01-01',
            'salary': '25000.00',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_duplicate_profile_for_same_user_is_rejected(self):
        self.auth_as(self.owner)
        payload = {
            'user': self.trainer.id,
            'department': 'FRONT_DESK',
            'designation': 'Trainer',
            'joined_date': '2026-01-01',
            'salary': '25000.00',
        }
        first = self.client.post(self.profiles_url, payload)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(self.profiles_url, payload)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)


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
        """Even if a client tries to set 'requester' to someone else, it should be ignored."""
        self.auth_as(self.trainer)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'requester': self.owner.id,  # attempt to spoof
            'leave_type': 'SICK',
            'start_date': start,
            'end_date': end,
            'reason': 'Fever',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['requester'], self.trainer.id)  # not owner.id


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