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

    def test_cannot_set_occupied_manually(self):
        self.auth_as(self.staff)
        r = self.client.patch(f'{self.lockers_url}{self.locker.id}/', {
            'status': 'OCCUPIED',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.AVAILABLE)


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
        """Assigning a locker that already has an active assignment returns 400."""
        self.auth_as(self.staff)
        self.client.post(self.assignments_url, {
            'locker': self.locker.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(30), 'is_active': True,
        })
        other_member = make_user('bob_v2@gym.com', role=User.Role.MEMBER,
                                  first_name='BobV2', last_name='Jones')
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id, 'member': other_member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(11), 'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_assign_maintenance_locker(self):
        self.locker.status = Locker.LockerStatus.MAINTENANCE
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


class LockerBulkCreateTests(LockerAPITestCase):
    def setUp(self):
        super().setUp()
        self.bulk_url = f'{self.lockers_url}bulk-create/'

    def test_bulk_create_happy_path(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, {
            'prefix': 'A-', 'start': 1, 'end': 10,
            'location': 'Block A', 'monthly_fee': '500.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['created'], 10)
        self.assertEqual(r.data['total_requested'], 10)
        self.assertEqual(r.data['skipped'], [])
        self.assertEqual(Locker.objects.count(), 10)
        self.assertTrue(Locker.objects.filter(locker_number='A-01').exists())
        self.assertTrue(Locker.objects.filter(locker_number='A-10').exists())

    def test_bulk_create_no_prefix(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, {
            'prefix': '', 'start': 1, 'end': 5,
            'location': 'Ground', 'monthly_fee': '300.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['created'], 5)
        self.assertTrue(Locker.objects.filter(locker_number='01').exists())
        self.assertTrue(Locker.objects.filter(locker_number='05').exists())

    def test_bulk_create_skips_duplicates(self):
        self.auth_as(self.owner)
        # Create first batch
        self.client.post(self.bulk_url, {
            'prefix': 'B-', 'start': 1, 'end': 5,
            'location': 'Block B', 'monthly_fee': '400.00',
        }, format='json')
        self.assertEqual(Locker.objects.count(), 5)
        # Run same range again — should skip all
        r = self.client.post(self.bulk_url, {
            'prefix': 'B-', 'start': 1, 'end': 5,
            'location': 'Block B', 'monthly_fee': '400.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['created'], 0)
        self.assertEqual(len(r.data['skipped']), 5)
        self.assertEqual(Locker.objects.count(), 5)

    def test_bulk_create_partial_overlap(self):
        self.auth_as(self.owner)
        # Create B-01 .. B-03
        self.client.post(self.bulk_url, {
            'prefix': 'B-', 'start': 1, 'end': 3,
            'location': 'Block B', 'monthly_fee': '400.00',
        }, format='json')
        # Request B-02 .. B-05 — should create 04, 05 only
        r = self.client.post(self.bulk_url, {
            'prefix': 'B-', 'start': 2, 'end': 5,
            'location': 'Block B', 'monthly_fee': '400.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['created'], 2)
        self.assertEqual(sorted(r.data['skipped']), ['B-02', 'B-03'])
        self.assertEqual(Locker.objects.count(), 5)

    def test_bulk_create_end_before_start_rejected(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, {
            'prefix': '', 'start': 10, 'end': 5,
            'location': 'X', 'monthly_fee': '100.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_create_over_200_rejected(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, {
            'prefix': '', 'start': 1, 'end': 201,
            'location': 'X', 'monthly_fee': '100.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_create_member_forbidden(self):
        self.auth_as(self.member)
        r = self.client.post(self.bulk_url, {
            'prefix': '', 'start': 1, 'end': 5,
            'location': 'X', 'monthly_fee': '100.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_bulk_create_single_number_range(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, {
            'prefix': '', 'start': 5, 'end': 5,
            'location': 'Z', 'monthly_fee': '0.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['created'], 1)
        self.assertTrue(Locker.objects.filter(locker_number='05').exists())

    def test_bulk_create_pad_width(self):
        self.auth_as(self.owner)
        # 1..100 → pad width 3
        r = self.client.post(self.bulk_url, {
            'prefix': 'L', 'start': 1, 'end': 100,
            'location': 'Main', 'monthly_fee': '200.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['created'], 100)
        self.assertTrue(Locker.objects.filter(locker_number='L001').exists())
        self.assertTrue(Locker.objects.filter(locker_number='L100').exists())

    def test_bulk_create_invalid_monthly_fee_rejected(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, {
            'prefix': '', 'start': 1, 'end': 2,
            'location': 'X', 'monthly_fee': '-50.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Locker.objects.count(), 0)

    def test_bulk_create_missing_location_accepted(self):
        """Location is blank=True on the model, so omitting it is valid."""
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, {
            'prefix': '', 'start': 1, 'end': 2,
            'monthly_fee': '100.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['created'], 2)
        self.assertTrue(Locker.objects.filter(locker_number='01', location='').exists())

    def test_bulk_create_invalid_status_rejected(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, {
            'prefix': '', 'start': 1, 'end': 2,
            'location': 'X', 'monthly_fee': '100.00',
            'status': 'BOGUS',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Locker.objects.count(), 0)


class LockerStatusSyncTests(LockerAPITestCase):
    """Ensure Locker.status stays in sync with assignments."""

    def setUp(self):
        super().setUp()
        self.locker = Locker.objects.create(
            locker_number='L-01', location='Ground Floor', monthly_fee=500,
        )

    def _assign(self, locker=None, member=None):
        """Create an active assignment and return (assignment_id, locker)."""
        locker = locker or self.locker
        member = member or self.member
        self.auth_as(self.staff)
        r = self.client.post(self.assignments_url, {
            'locker': locker.id, 'member': member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(30), 'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        return r.data['id'], locker

    def test_deactivating_via_update_frees_locker(self):
        assignment_id, _ = self._assign()
        self.auth_as(self.staff)
        r = self.client.patch(
            f'{self.assignments_url}{assignment_id}/',
            {'is_active': False},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.AVAILABLE)

    def test_deleting_assignment_frees_locker(self):
        assignment_id, _ = self._assign()
        self.auth_as(self.staff)
        r = self.client.delete(f'{self.assignments_url}{assignment_id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.AVAILABLE)

    def test_second_active_assignment_keeps_occupied(self):
        """Two active assignments on the same locker, release one → stays OCCUPIED."""
        other_member = make_user('bob4@gym.com', role=User.Role.MEMBER,
                                  first_name='Bob4', last_name='Jones')
        a1 = LockerAssignment.objects.create(
            locker=self.locker, member=self.member,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=30),
            is_active=True, assigned_by=self.staff,
        )
        a2 = LockerAssignment.objects.create(
            locker=self.locker, member=other_member,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=30),
            is_active=True, assigned_by=self.staff,
        )
        self.locker.status = Locker.LockerStatus.OCCUPIED
        self.locker.save(update_fields=['status'])
        # Release a1
        self.auth_as(self.staff)
        r = self.client.patch(
            f'{self.assignments_url}{a1.id}/',
            {'is_active': False},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.OCCUPIED)

    def test_changing_locker_on_update_frees_old_occupies_new(self):
        assignment_id, _ = self._assign()
        locker2 = Locker.objects.create(
            locker_number='L-02', location='First Floor', monthly_fee=600,
        )
        self.auth_as(self.staff)
        r = self.client.patch(
            f'{self.assignments_url}{assignment_id}/',
            {'locker': locker2.id},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.locker.refresh_from_db()
        locker2.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.AVAILABLE)
        self.assertEqual(locker2.status, Locker.LockerStatus.OCCUPIED)

    def test_maintenance_locker_not_overridden_on_release(self):
        """A locker in MAINTENANCE status should not flip to AVAILABLE."""
        assignment_id, _ = self._assign()
        # Simulate locker moved to MAINTENANCE after assignment
        self.locker.status = Locker.LockerStatus.MAINTENANCE
        self.locker.save(update_fields=['status'])
        self.auth_as(self.staff)
        r = self.client.patch(
            f'{self.assignments_url}{assignment_id}/',
            {'is_active': False},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.MAINTENANCE)

    def test_deleting_last_assignment_frees_locker(self):
        """Deleting the only active assignment on a locker frees it."""
        assignment_id, _ = self._assign()
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.OCCUPIED)
        self.auth_as(self.staff)
        r = self.client.delete(f'{self.assignments_url}{assignment_id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.AVAILABLE)

    def test_stale_occupied_locker_can_be_assigned(self):
        """A locker stuck OCCUPIED with no active assignments is healed and assignable."""
        self.locker.status = Locker.LockerStatus.OCCUPIED
        self.locker.save(update_fields=['status'])
        self.auth_as(self.staff)
        r = self.client.post(self.assignments_url, {
            'locker': self.locker.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(0),
            'end_date': self.get_future_date_str(30), 'is_active': True,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.status, Locker.LockerStatus.OCCUPIED)

    def test_patch_occupied_locker_with_status_occupied_returns_200(self):
        """PATCH on an OCCUPIED locker with status=OCCUPIED in payload returns 200."""
        self.locker.status = Locker.LockerStatus.OCCUPIED
        self.locker.save(update_fields=['status'])
        self.auth_as(self.staff)
        r = self.client.patch(f'{self.lockers_url}{self.locker.id}/', {
            'monthly_fee': '999.00',
            'status': 'OCCUPIED',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.locker.refresh_from_db()
        self.assertEqual(self.locker.monthly_fee, 999)
        self.assertEqual(self.locker.status, Locker.LockerStatus.OCCUPIED)