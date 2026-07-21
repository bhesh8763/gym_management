"""
Tests for the Lockers app API.

Run with:
    python manage.py test apps.lockers.tests

Coverage:
    - Locker create (POST /api/lockers/lockers/)
    - Locker assignment create (POST /api/lockers/assignments/)
    - assigned_by auto-populated from the authenticated user
    - Assigning a locker flips its status to OCCUPIED automatically
    - Only MEMBER-role users can be assigned a locker (limit_choices_to)
    - RBAC: members cannot manage lockers/assignments themselves
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.lockers.models import Locker, LockerAssignment

User = get_user_model()


def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


class LockerAPITestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER,
                                first_name='Owner', last_name='User')
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF,
                                first_name='Staff', last_name='User')
        self.member = make_user('alice@gym.com', role=User.Role.MEMBER,
                                 first_name='Alice', last_name='Smith')
        self.lockers_url = '/api/lockers/lockers/'
        self.assignments_url = '/api/lockers/assignments/'

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )


class LockerCreateTests(LockerAPITestCase):
    def test_staff_can_create_locker(self):
        self.auth_as(self.staff)
        r = self.client.post(self.lockers_url, {
            'locker_number': 'L-01',
            'location': 'Ground Floor',
            'monthly_fee': '500.00',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['status'], 'AVAILABLE')

    def test_member_cannot_create_locker(self):
        self.auth_as(self.member)
        r = self.client.post(self.lockers_url, {
            'locker_number': 'L-01',
            'location': 'Ground Floor',
            'monthly_fee': '500.00',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class LockerAssignmentTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        self.locker = Locker.objects.create(
            locker_number='L-01', location='Ground Floor', monthly_fee=500,
        )

    def test_assigning_locker_flips_status_to_occupied(self):
        self.auth_as(self.staff)
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id,
            'member': self.member.id,
            'start_date': '2026-07-20',
            'end_date': '2026-07-31',
            'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['assigned_by'], self.staff.id)

        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.OCCUPIED)

    def test_only_member_role_can_be_assigned(self):
        """Assigning a locker to a STAFF/OWNER user should be rejected (limit_choices_to)."""
        self.auth_as(self.staff)
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id,
            'member': self.owner.id,  # not a MEMBER
            'start_date': '2026-07-20',
            'end_date': '2026-07-31',
            'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_self_assign_locker(self):
        self.auth_as(self.member)
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id,
            'member': self.member.id,
            'start_date': '2026-07-20',
            'end_date': '2026-07-31',
            'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class LockerListFilterTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        Locker.objects.create(locker_number='L-01', location='Ground', monthly_fee=500)
        Locker.objects.create(
            locker_number='L-02', location='First Floor', monthly_fee=600,
            status=Locker.LockerStatus.OCCUPIED,
        )

    def test_filter_by_status(self):
        self.auth_as(self.owner)
        r = self.client.get(self.lockers_url, {'status': 'AVAILABLE'})
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['locker_number'], 'L-01')