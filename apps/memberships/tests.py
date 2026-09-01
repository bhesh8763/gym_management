"""
Tests for the Memberships app API.

Run with:
    python manage.py test apps.memberships.tests

Coverage:
    - MembershipPlan CRUD (create, list, retrieve, update, soft-delete)
    - Membership assign / list / detail / cancel
    - Membership freeze / unfreeze
    - Membership renewal
    - FreezeRequest create / approve / reject flow
    - Expiring memberships endpoint
    - Search / filter / ordering on membership list
    - Role-based access (Owner/Staff, Trainer, Member)
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.memberships.models import FreezeRequest, Membership, MembershipPlan

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


def make_plan(name='Monthly Basic', price=Decimal('1000.00'), duration=30, is_active=True):
    return MembershipPlan.objects.create(
        name=name, price=price, duration_days=duration, is_active=is_active,
    )


def make_membership(member, plan, status=Membership.Status.ACTIVE, **kwargs):
    today = timezone.now().date()
    defaults = {
        'plan': plan,
        'status': status,
        'start_date': today,
        'end_date': today + timedelta(days=plan.duration_days),
        'price_paid': plan.price,
    }
    defaults.update(kwargs)
    return Membership.objects.create(member=member, **defaults)


# ─── MembershipPlan CRUD ─────────────────────────────────────────────────────

class PlanCreateTestCase(APITestCase):
    """POST /api/memberships/plans/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

    def test_owner_can_create_plan(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post('/api/memberships/plans/', {
            'name': 'Annual Premium',
            'price': '12000.00',
            'duration_days': 365,
            'billing_cycle': 'ANNUAL',
            'features': ['Gym access', 'Sauna', 'Locker'],
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MembershipPlan.objects.count(), 1)

    def test_staff_can_create_plan(self):
        self.client.credentials(**auth_headers(self.staff))
        r = self.client.post('/api/memberships/plans/', {
            'name': 'Staff Plan',
            'price': '500.00',
            'duration_days': 30,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_trainer_cannot_create_plan(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.post('/api/memberships/plans/', {
            'name': 'Trainer Plan',
            'price': '500.00',
            'duration_days': 30,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_create_plan(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/memberships/plans/', {
            'name': 'Member Plan',
            'price': '500.00',
            'duration_days': 30,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_plan_name_rejected(self):
        make_plan(name='Basic Monthly')
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post('/api/memberships/plans/', {
            'name': 'Basic Monthly',
            'price': '1500.00',
            'duration_days': 30,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class PlanListTestCase(APITestCase):
    """GET /api/memberships/plans/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan1 = make_plan(name='Basic', price=Decimal('500.00'))
        self.plan2 = make_plan(name='Premium', price=Decimal('1500.00'))
        self.plan3 = make_plan(name='Inactive', price=Decimal('800.00'), is_active=False)

    def test_any_user_can_list_plans(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/memberships/plans/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 3)

    def test_filter_active_plans(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/plans/?is_active=true')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)


class PlanDetailTestCase(APITestCase):
    """GET/PATCH/DELETE /api/memberships/plans/<id>/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.plan = make_plan(name='To Update')

    def test_owner_can_update_plan(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.patch(f'/api/memberships/plans/{self.plan.id}/', {
            'price': '2000.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.price, Decimal('2000.00'))

    def test_owner_soft_deletes_plan(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.delete(f'/api/memberships/plans/{self.plan.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_active)
        # Plan still exists in DB (not hard-deleted due to PROTECT)
        self.assertTrue(MembershipPlan.objects.filter(id=self.plan.id).exists())


# ─── Membership Assign ───────────────────────────────────────────────────────

class MembershipAssignTestCase(APITestCase):
    """POST /api/memberships/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = make_plan()

    def test_owner_can_assign_membership(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post('/api/memberships/', {
            'member': self.member.id,
            'plan': self.plan.id,
            'status': 'ACTIVE',
            'price_paid': '1000.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        m = Membership.objects.first()
        self.assertEqual(m.member, self.member)
        self.assertEqual(m.plan, self.plan)
        self.assertEqual(m.status, Membership.Status.ACTIVE)
        # end_date should be computed from plan.duration_days
        self.assertEqual(m.end_date, m.start_date + timedelta(days=30))

    def test_staff_can_assign_membership(self):
        self.client.credentials(**auth_headers(self.staff))
        r = self.client.post('/api/memberships/', {
            'member': self.member.id,
            'plan': self.plan.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_member_self_purchase_creates_pending(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/memberships/', {
            'plan': self.plan.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        m = Membership.objects.first()
        self.assertEqual(m.member, self.member)
        self.assertEqual(m.status, Membership.Status.PENDING)

    def test_cannot_assign_active_to_member_with_active_membership(self):
        make_membership(self.member, self.plan)
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post('/api/memberships/', {
            'member': self.member.id,
            'plan': self.plan.id,
            'status': 'ACTIVE',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_assign_pending_even_with_active_membership(self):
        make_membership(self.member, self.plan)
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post('/api/memberships/', {
            'member': self.member.id,
            'plan': self.plan.id,
            'status': 'PENDING',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)


# ─── Membership List + Filter ────────────────────────────────────────────────

class MembershipListFilterTestCase(APITestCase):
    """GET /api/memberships/ with search, status, plan, member filters."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member1 = make_user('alice@gym.com', role=User.Role.MEMBER,
                                 first_name='Alice', last_name='Smith')
        self.member2 = make_user('bob@gym.com', role=User.Role.MEMBER,
                                 first_name='Bob', last_name='Jones')
        self.plan1 = make_plan(name='Basic')
        self.plan2 = make_plan(name='Premium', price=Decimal('2000.00'))

        self.m1 = make_membership(self.member1, self.plan1, status=Membership.Status.ACTIVE)
        self.m2 = make_membership(self.member2, self.plan2, status=Membership.Status.EXPIRED)
        self.m3 = make_membership(self.member1, self.plan2, status=Membership.Status.CANCELLED)

    def test_owner_sees_all_memberships(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 3)

    def test_member_sees_only_own(self):
        self.client.credentials(**auth_headers(self.member1))
        r = self.client.get('/api/memberships/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_filter_by_status(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/?status=ACTIVE')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'ACTIVE')

    def test_filter_by_plan(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get(f'/api/memberships/?plan={self.plan2.id}')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_search_by_member_name(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/?search=Alice')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_search_by_email(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/?search=bob@gym.com')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)

    def test_ordering(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/?ordering=start_date')
        self.assertEqual(r.status_code, status.HTTP_200_OK)


# ─── Membership Detail / Cancel ──────────────────────────────────────────────

class MembershipDetailCancelTestCase(APITestCase):
    """GET/PATCH/DELETE /api/memberships/<id>/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = make_plan()
        self.membership = make_membership(self.member, self.plan)

    def test_member_can_view_own_membership(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get(f'/api/memberships/{self.membership.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('is_active', r.data)
        self.assertIn('days_remaining', r.data)

    def test_owner_can_update_membership(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.patch(f'/api/memberships/{self.membership.id}/', {
            'notes': 'VIP member',
            'price_paid': '1500.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.notes, 'VIP member')

    def test_owner_can_cancel_membership(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.delete(f'/api/memberships/{self.membership.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, Membership.Status.CANCELLED)

    def test_member_cannot_cancel_membership(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.delete(f'/api/memberships/{self.membership.id}/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ─── Freeze / Unfreeze ───────────────────────────────────────────────────────

class MembershipFreezeUnfreezeTestCase(APITestCase):
    """POST /api/memberships/<id>/freeze/ and /unfreeze/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = make_plan(duration=60)
        self.membership = make_membership(self.member, self.plan)
        self.today = timezone.now().date()

    def test_owner_can_freeze_membership(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(f'/api/memberships/{self.membership.id}/freeze/', {
            'freeze_start': self.today.isoformat(),
            'freeze_end': (self.today + timedelta(days=14)).isoformat(),
            'freeze_reason': 'Medical leave',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, Membership.Status.FROZEN)
        self.assertEqual(self.membership.freeze_start, self.today)
        self.assertEqual(self.membership.freeze_reason, 'Medical leave')

    def test_freeze_end_before_start_rejected(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(f'/api/memberships/{self.membership.id}/freeze/', {
            'freeze_start': (self.today + timedelta(days=14)).isoformat(),
            'freeze_end': self.today.isoformat(),
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_freeze_non_active_membership_rejected(self):
        self.membership.status = Membership.Status.EXPIRED
        self.membership.save()
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(f'/api/memberships/{self.membership.id}/freeze/', {
            'freeze_start': self.today.isoformat(),
            'freeze_end': (self.today + timedelta(days=7)).isoformat(),
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_freeze(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post(f'/api/memberships/{self.membership.id}/freeze/', {
            'freeze_start': self.today.isoformat(),
            'freeze_end': (self.today + timedelta(days=7)).isoformat(),
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_unfreeze_membership(self):
        freeze_start = self.today
        freeze_end = self.today + timedelta(days=14)
        self.membership.status = Membership.Status.FROZEN
        self.membership.freeze_start = freeze_start
        self.membership.freeze_end = freeze_end
        self.membership.save()

        original_end = self.membership.end_date
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(f'/api/memberships/{self.membership.id}/unfreeze/', {},
                             format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, Membership.Status.ACTIVE)
        self.assertIsNone(self.membership.freeze_start)
        self.assertIsNone(self.membership.freeze_end)
        # end_date should be extended by frozen days
        self.assertEqual(self.membership.end_date, original_end + timedelta(days=14))

    def test_unfreeze_non_frozen_rejected(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(f'/api/memberships/{self.membership.id}/unfreeze/', {},
                             format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ─── Renew ───────────────────────────────────────────────────────────────────

class MembershipRenewTestCase(APITestCase):
    """POST /api/memberships/<id>/renew/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = make_plan(duration=30)
        self.today = timezone.now().date()

    def test_owner_can_renew_expired_membership(self):
        membership = make_membership(
            self.member, self.plan,
            status=Membership.Status.EXPIRED,
            end_date=self.today - timedelta(days=5),
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(f'/api/memberships/{membership.id}/renew/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        new_m = Membership.objects.get(id=r.data['id'])
        self.assertEqual(new_m.renewed_from, membership)
        self.assertEqual(new_m.member, self.member)
        self.assertEqual(new_m.plan, self.plan)
        self.assertEqual(new_m.status, Membership.Status.ACTIVE)
        self.assertGreaterEqual(new_m.start_date, self.today)

    def test_owner_can_renew_active_membership(self):
        membership = make_membership(self.member, self.plan)
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(f'/api/memberships/{membership.id}/renew/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        membership.refresh_from_db()
        self.assertEqual(membership.status, Membership.Status.EXPIRED)

    def test_member_can_self_renew_expired(self):
        membership = make_membership(
            self.member, self.plan,
            status=Membership.Status.EXPIRED,
            end_date=self.today - timedelta(days=5),
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post(f'/api/memberships/{membership.id}/renew/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        new_m = Membership.objects.get(id=r.data['id'])
        self.assertEqual(new_m.status, Membership.Status.PENDING)  # self-renewal = PENDING

    def test_renew_with_custom_dates(self):
        membership = make_membership(
            self.member, self.plan,
            status=Membership.Status.EXPIRED,
            end_date=self.today - timedelta(days=5),
        )
        custom_start = self.today + timedelta(days=10)
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(f'/api/memberships/{membership.id}/renew/', {
            'start_date': custom_start.isoformat(),
            'price_paid': '1500.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        new_m = Membership.objects.get(id=r.data['id'])
        self.assertEqual(new_m.start_date, custom_start)
        self.assertEqual(new_m.end_date, custom_start + timedelta(days=30))
        self.assertEqual(new_m.price_paid, Decimal('1500.00'))


# ─── FreezeRequest Flow ──────────────────────────────────────────────────────

class FreezeRequestCreateTestCase(APITestCase):
    """POST /api/memberships/freeze-requests/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Jones')
        self.plan = make_plan()
        self.membership = make_membership(self.member, self.plan)
        self.today = timezone.now().date()

    def test_member_can_create_freeze_request(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/memberships/freeze-requests/', {
            'membership': self.membership.id,
            'freeze_start': (self.today + timedelta(days=7)).isoformat(),
            'freeze_end': (self.today + timedelta(days=21)).isoformat(),
            'reason': 'Traveling abroad',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        fr = FreezeRequest.objects.first()
        self.assertEqual(fr.requested_by, self.member)
        self.assertEqual(fr.status, FreezeRequest.Status.PENDING)

    def test_freeze_request_for_non_active_membership_rejected(self):
        self.membership.status = Membership.Status.EXPIRED
        self.membership.save()
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/memberships/freeze-requests/', {
            'membership': self.membership.id,
            'freeze_start': (self.today + timedelta(days=7)).isoformat(),
            'freeze_end': (self.today + timedelta(days=21)).isoformat(),
            'reason': 'Test',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_freeze_request_start_in_past_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/memberships/freeze-requests/', {
            'membership': self.membership.id,
            'freeze_start': (self.today - timedelta(days=1)).isoformat(),
            'freeze_end': (self.today + timedelta(days=7)).isoformat(),
            'reason': 'Test',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_pending_freeze_request_rejected(self):
        FreezeRequest.objects.create(
            membership=self.membership, requested_by=self.member,
            freeze_start=self.today + timedelta(days=7),
            freeze_end=self.today + timedelta(days=21),
            reason='Existing request',
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/memberships/freeze-requests/', {
            'membership': self.membership.id,
            'freeze_start': (self.today + timedelta(days=14)).isoformat(),
            'freeze_end': (self.today + timedelta(days=28)).isoformat(),
            'reason': 'Another request',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class FreezeRequestApproveRejectTestCase(APITestCase):
    """POST /api/memberships/freeze-requests/<id>/approve/ and /reject/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = make_plan()
        self.membership = make_membership(self.member, self.plan)
        self.today = timezone.now().date()
        self.freeze_request = FreezeRequest.objects.create(
            membership=self.membership, requested_by=self.member,
            freeze_start=self.today + timedelta(days=7),
            freeze_end=self.today + timedelta(days=21),
            reason='Vacation',
        )

    def test_owner_can_approve_freeze_request(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(
            f'/api/memberships/freeze-requests/{self.freeze_request.id}/approve/',
            {}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.freeze_request.refresh_from_db()
        self.assertEqual(self.freeze_request.status, FreezeRequest.Status.APPROVED)
        self.assertEqual(self.freeze_request.reviewed_by, self.owner)
        # Membership should be frozen
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, Membership.Status.FROZEN)
        self.assertEqual(self.membership.freeze_start, self.freeze_request.freeze_start)

    def test_staff_can_approve_freeze_request(self):
        self.client.credentials(**auth_headers(self.staff))
        r = self.client.post(
            f'/api/memberships/freeze-requests/{self.freeze_request.id}/approve/',
            {}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_member_cannot_approve_freeze_request(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post(
            f'/api/memberships/freeze-requests/{self.freeze_request.id}/approve/',
            {}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_reject_freeze_request(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(
            f'/api/memberships/freeze-requests/{self.freeze_request.id}/reject/',
            {'reason': 'Insufficient documentation'}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.freeze_request.refresh_from_db()
        self.assertEqual(self.freeze_request.status, FreezeRequest.Status.REJECTED)
        self.assertEqual(self.freeze_request.rejection_reason, 'Insufficient documentation')

    def test_approve_already_reviewed_rejected(self):
        self.freeze_request.status = FreezeRequest.Status.APPROVED
        self.freeze_request.save()
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(
            f'/api/memberships/freeze-requests/{self.freeze_request.id}/approve/',
            {}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_when_membership_no_longer_active(self):
        self.membership.status = Membership.Status.CANCELLED
        self.membership.save()
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post(
            f'/api/memberships/freeze-requests/{self.freeze_request.id}/approve/',
            {}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_freeze_request_list_owner_sees_all(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/freeze-requests/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)

    def test_freeze_request_list_member_sees_own(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/memberships/freeze-requests/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)


# ─── Expiring Memberships ────────────────────────────────────────────────────

class ExpiringMembershipsTestCase(APITestCase):
    """GET /api/memberships/expiring/?days=7"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = make_plan(duration=30)
        self.today = timezone.now().date()

        # Expiring in 3 days — should show up
        self.expiring = make_membership(
            self.member, self.plan,
            end_date=self.today + timedelta(days=3),
        )
        # Expiring in 30 days — should NOT show up with ?days=7
        make_membership(
            self.member, self.plan,
            end_date=self.today + timedelta(days=30),
        )

    def test_expiring_endpoint(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/expiring/?days=7')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.expiring.id)

    def test_expiring_with_larger_window(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/expiring/?days=35')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)


# ─── Expired Membership Auto-Sync ───────────────────────────────────────────

class ExpiredSyncTestCase(APITestCase):
    """Membership list auto-flips expired ACTIVE memberships."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.plan = make_plan()

    def test_list_view_auto_expires_old_memberships(self):
        membership = make_membership(
            self.member, self.plan,
            status=Membership.Status.ACTIVE,
            end_date=timezone.now().date() - timedelta(days=1),
        )
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/memberships/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        membership.refresh_from_db()
        self.assertEqual(membership.status, Membership.Status.EXPIRED)
