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
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
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
        self.other_member = make_user('bob@gym.com', role=User.Role.MEMBER,
                                       first_name='Bob', last_name='Jones')
        self.lockers_url = '/api/lockers/lockers/'
        self.assignments_url = '/api/lockers/assignments/'

    def get_future_date_str(self, days=1):
        return (timezone.now().date() + timedelta(days=days)).strftime('%Y-%m-%d')

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
            'locker_number': 'L-03',
            'location': 'Ground Floor',
            'monthly_fee': '500.00',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_locker_number_rejected(self):
        self.auth_as(self.staff)
        self.client.post(self.lockers_url, {
            'locker_number': 'L-DUP', 'location': 'Ground', 'monthly_fee': '500.00',
        })
        r = self.client.post(self.lockers_url, {
            'locker_number': 'L-DUP', 'location': 'First', 'monthly_fee': '600.00',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_can_create_locker(self):
        self.auth_as(self.owner)
        r = self.client.post(self.lockers_url, {
            'locker_number': 'L-02', 'location': 'First Floor', 'monthly_fee': '600.00',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)


class LockerRetrieveTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        self.locker = Locker.objects.create(
            locker_number='L-01', location='Ground Floor', monthly_fee=500,
        )

    def test_owner_can_retrieve(self):
        self.auth_as(self.owner)
        r = self.client.get(f'{self.lockers_url}{self.locker.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['locker_number'], 'L-01')

    def test_member_cannot_retrieve_locker(self):
        self.auth_as(self.member)
        r = self.client.get(f'{self.lockers_url}{self.locker.id}/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class LockerUpdateTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        self.locker = Locker.objects.create(
            locker_number='L-01', location='Ground Floor', monthly_fee=500,
        )

    def test_staff_can_update_locker(self):
        self.auth_as(self.staff)
        r = self.client.patch(f'{self.lockers_url}{self.locker.id}/', {
            'location': 'First Floor', 'monthly_fee': '700.00',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.location, 'First Floor')

    def test_member_cannot_update_locker(self):
        self.auth_as(self.member)
        r = self.client.patch(f'{self.lockers_url}{self.locker.id}/', {
            'location': 'Sneaky',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class LockerDeleteTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        self.locker = Locker.objects.create(
            locker_number='L-DEL', location='Ground Floor', monthly_fee=500,
        )

    def test_owner_can_delete_locker(self):
        self.auth_as(self.owner)
        r = self.client.delete(f'{self.lockers_url}{self.locker.id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Locker.objects.filter(id=self.locker.id).exists())

    def test_member_cannot_delete_locker(self):
        self.auth_as(self.member)
        r = self.client.delete(f'{self.lockers_url}{self.locker.id}/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class LockerAuthTests(LockerAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        r = self.client.get(self.lockers_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_create_returns_401(self):
        r = self.client.post(self.lockers_url, {
            'locker_number': 'L-UNAUTH', 'location': 'Ground', 'monthly_fee': '500.00',
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


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
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(11),
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
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(11),
            'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_self_assign_locker(self):
        self.auth_as(self.member)
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id,
            'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(11),
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

    def test_filter_by_occupied(self):
        self.auth_as(self.owner)
        r = self.client.get(self.lockers_url, {'status': 'OCCUPIED'})
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['locker_number'], 'L-02')


class LockerAssignmentValidationTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        self.locker = Locker.objects.create(
            locker_number='L-01', location='Ground Floor', monthly_fee=500,
        )

    def test_cannot_assign_non_available_locker(self):
        self.locker.status = Locker.LockerStatus.OCCUPIED
        self.locker.save(update_fields=['status'])
        self.auth_as(self.staff)
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(11), 'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_active_assignment_rejected(self):
        self.auth_as(self.staff)
        self.client.post(self.assignments_url, {
            'locker': self.locker.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(30), 'is_active': True,
        })
        locker2 = Locker.objects.create(
            locker_number='L-02', location='First', monthly_fee=600,
        )
        r = self.client.post(self.assignments_url, {
            'locker': locker2.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(30), 'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class LockerAssignmentDeactivationTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        self.locker = Locker.objects.create(
            locker_number='L-01', location='Ground Floor', monthly_fee=500,
        )
        self.auth_as(self.staff)
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(30), 'is_active': True,
        })
        self.assignment_id = r.data['id']

    def test_deactivating_assignment_frees_locker(self):
        self.auth_as(self.staff)
        r = self.client.patch(
            f'{self.assignments_url}{self.assignment_id}/',
            {'is_active': False}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.AVAILABLE)

    def test_expired_assignment_auto_released(self):
        past_locker = Locker.objects.create(
            locker_number='L-PAST', location='Ground', monthly_fee=500,
        )
        LockerAssignment.objects.create(
            locker=past_locker, member=self.other_member,
            start_date=timezone.now().date() - timedelta(days=30),
            end_date=timezone.now().date() - timedelta(days=1),
            is_active=True, assigned_by=self.staff,
        )
        self.auth_as(self.staff)
        self.client.get(self.assignments_url)
        past_locker.refresh_from_db()
        self.assertEqual(past_locker.status, Locker.LockerStatus.AVAILABLE)


class LockerAssignmentMemberAccessTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        self.locker = Locker.objects.create(
            locker_number='L-01', location='Ground Floor', monthly_fee=500,
        )
        self.auth_as(self.staff)
        self.client.post(self.assignments_url, {
            'locker': self.locker.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(30), 'is_active': True,
        })

    def test_member_can_list_own_assignments(self):
        self.auth_as(self.member)
        r = self.client.get(self.assignments_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['count'], 1)

    def test_member_cannot_see_other_assignments(self):
        self.auth_as(self.other_member)
        r = self.client.get(self.assignments_url)
        self.assertEqual(r.data['count'], 0)

    def test_member_cannot_create_assignment(self):
        self.auth_as(self.member)
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(11), 'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)