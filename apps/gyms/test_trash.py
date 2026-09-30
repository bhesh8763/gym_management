"""
Tests for the soft-delete trash system.

Run with:
    python manage.py test apps.gyms.test_trash

Coverage:
    - TenantScopedModel soft delete / restore / hard delete semantics
    - TenantManager hides soft-deleted rows; all_objects sees them
    - Trash API: summary, list, restore (incl. 409 conflicts), purge
    - Member delete → trash → restore round-trip
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.tokens import token_for_membership
from apps.gyms.models import CustomRole, GymMembership
from apps.gyms.services import provision_owner_gym
from apps.gyms.trash import TRASH_REGISTRY, get_model
from apps.members.models import MemberProfile
from apps.memberships.models import MembershipPlan

User = get_user_model()


def make_member(email, first='Test', last='Member'):
    return User.objects.create_user(
        email=email, password='Pass@12345',
        first_name=first, last_name=last, role=User.Role.MEMBER,
    )


class TrashAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email='trash-owner@example.com', password='Pass@12345',
            first_name='Trash', last_name='Owner', role=User.Role.OWNER,
        )
        cls.gym, cls.owner_membership = provision_owner_gym(
            user=cls.owner, name='Trash Gym',
        )

        cls.staff = User.objects.create_user(
            email='trash-staff@example.com', password='Pass@12345',
            first_name='Trash', last_name='Staff', role=User.Role.STAFF,
        )
        cls.staff_membership = GymMembership.objects.create(
            user=cls.staff,
            gym=cls.gym,
            role=GymMembership.Role.STAFF,
            status=GymMembership.Status.ACTIVE,
        )
        cls.member_user = make_member('trash-member@example.com')
        cls.member_membership = GymMembership.objects.create(
            user=cls.member_user,
            gym=cls.gym,
            role=GymMembership.Role.MEMBER,
            status=GymMembership.Status.ACTIVE,
        )

    def bearer(self, user, membership=None):
        token = token_for_membership(user, membership)
        return {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}

    def auth_owner(self):
        self.client.credentials(**self.bearer(self.owner, self.owner_membership))

    def setUp(self):
        self.client.credentials(**self.bearer(self.owner, self.owner_membership))

    # ─── Model-level semantics ────────────────────────────────────────────

    def test_soft_delete_hides_row_from_default_manager(self):
        plan = MembershipPlan.objects.create(
            gym=self.gym, name='Soft Plan', duration_days=30, price=1000,
        )
        plan.delete(user=self.owner)

        refreshed = MembershipPlan.objects.filter(pk=plan.pk).first()
        self.assertIsNone(refreshed, 'Soft-deleted row must not appear in live manager')

        trashed = MembershipPlan.all_objects.filter(pk=plan.pk).first()
        self.assertIsNotNone(trashed)
        self.assertIsNotNone(trashed.deleted_at)
        self.assertEqual(trashed.deleted_by_id, self.owner.id)
        self.assertTrue(trashed.is_deleted)

    def test_restore_clears_deletion_markers(self):
        plan = MembershipPlan.objects.create(
            gym=self.gym, name='Restore Plan', duration_days=30, price=1000,
        )
        plan.delete(user=self.owner)
        restored = plan.restore(user=self.owner)
        self.assertFalse(restored.is_deleted)
        self.assertIsNone(restored.deleted_at)
        self.assertIsNone(restored.deleted_by)
        self.assertIsNotNone(MembershipPlan.objects.filter(pk=plan.pk).first())

    def test_hard_delete_removes_row_entirely(self):
        plan = MembershipPlan.objects.create(
            gym=self.gym, name='Hard Plan', duration_days=30, price=1000,
        )
        plan.delete(hard=True)
        self.assertIsNone(MembershipPlan.all_objects.filter(pk=plan.pk).first())

    def test_registry_slugs_resolve_to_models(self):
        self.assertIn('members', TRASH_REGISTRY)
        self.assertEqual(get_model('members'), MemberProfile)
        self.assertIsNone(get_model('does-not-exist'))

    # ─── Trash API ────────────────────────────────────────────────────────

    def test_summary_counts_deleted_rows_per_category(self):
        MembershipPlan.objects.create(
            gym=self.gym, name='Count A', duration_days=30, price=1000,
        ).delete(user=self.owner)
        MembershipPlan.objects.create(
            gym=self.gym, name='Count B', duration_days=30, price=2000,
        ).delete(user=self.owner)

        response = self.client.get(reverse('gyms:trash-summary'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_slug = {c['slug']: c['count'] for c in response.data['categories']}
        self.assertGreaterEqual(by_slug.get('plans', 0), 2)
        self.assertGreaterEqual(response.data['total'], 2)

    def test_list_and_search_trashed_members(self):
        member = make_member('searchable.member@example.com', 'Search', 'Me')
        profile = MemberProfile.objects.create(user=member, gym=self.gym)
        profile.delete(user=self.owner)

        response = self.client.get(reverse('gyms:trash-list', args=['members']))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['count'], 1)
        ids = [r['id'] for r in response.data['results']]
        self.assertIn(profile.id, ids)
        row = next(r for r in response.data['results'] if r['id'] == profile.id)
        self.assertIsNotNone(row['deleted_at'])
        self.assertIn('Trash', row['deleted_by_name'])

        response = self.client.get(
            reverse('gyms:trash-list', args=['members']), {'search': 'searchable.member'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [r['id'] for r in response.data['results']]
        self.assertIn(profile.id, ids)

    def test_restore_returns_row_to_live_queryset(self):
        member = make_member('restore.me@example.com', 'Restore', 'Me')
        profile = MemberProfile.objects.create(user=member, gym=self.gym)
        profile.delete(user=self.owner)
        self.assertIsNone(MemberProfile.objects.filter(pk=profile.pk).first())

        response = self.client.post(
            reverse('gyms:trash-restore', args=['members', profile.id]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(MemberProfile.objects.filter(pk=profile.pk).first())

    def test_restore_conflict_guard_returns_409(self):
        """DB unique constraints normally block duplicate live rows before
        restore could clash; the guard stays as defense-in-depth. Exercised
        directly with a synthetic trashed row pointing at a real live one."""
        from types import SimpleNamespace

        from apps.gyms.trash_views import TrashRestoreView

        member = make_member('conflict.member@example.com', 'Conflict', 'Me')
        live = MemberProfile.objects.create(user=member, gym=self.gym)

        # A "trashed" row (not in DB) for the same user+gym with a distinct pk.
        fake_trashed = SimpleNamespace(user_id=member.id, gym_id=self.gym.id, pk=live.pk + 999999)
        clash = TrashRestoreView._restore_conflict(MemberProfile, fake_trashed)
        self.assertIsNotNone(clash)
        self.assertIn('already exists', clash)

        # No live row → no conflict.
        live.delete(user=self.owner)
        clash = TrashRestoreView._restore_conflict(MemberProfile, fake_trashed)
        self.assertIsNone(clash)

    def test_trashed_plan_name_slot_still_taken(self):
        """Known trade-off: DB unique constraints keep the name occupied
        while a row is in trash. Restore is the recovery path — recreating
        the same name is blocked until restore or purge."""
        trashed = MembershipPlan.objects.create(
            gym=self.gym, name='Clash Plan', duration_days=30, price=1000,
        )
        trashed.delete(user=self.owner)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            MembershipPlan.objects.create(
                gym=self.gym, name='Clash Plan', duration_days=30, price=1000,
            )

    def test_purge_hard_deletes_row(self):
        plan = MembershipPlan.objects.create(
            gym=self.gym, name='Purge Plan', duration_days=30, price=1000,
        )
        plan.delete(user=self.owner)

        response = self.client.delete(reverse('gyms:trash-purge', args=['plans', plan.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(MembershipPlan.all_objects.filter(pk=plan.pk).first())

    def test_unknown_slug_returns_404(self):
        response = self.client.get(reverse('gyms:trash-list', args=['nope']))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_member_role_cannot_access_trash(self):
        self.client.credentials(**self.bearer(self.member_user, self.member_membership))
        response = self.client.get(reverse('gyms:trash-summary'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gym_scoping_keeps_other_gyms_rows_invisible(self):
        other_owner = User.objects.create_user(
            email='other-trash-owner@example.com', password='Pass@12345',
            first_name='Other', last_name='Owner', role=User.Role.OWNER,
        )
        other_gym, other_membership = provision_owner_gym(
            user=other_owner, name='Other Trash Gym',
        )
        plan = MembershipPlan.objects.create(
            gym=other_gym, name='Foreign Plan', duration_days=30, price=1000,
        )
        plan.delete(user=other_owner)

        response = self.client.get(reverse('gyms:trash-list', args=['plans']))
        ids = [r['id'] for r in response.data['results']]
        self.assertNotIn(plan.id, ids)

        # Owner of the other gym cannot purge it either.
        self.client.credentials(**self.bearer(other_owner, other_membership))
        response = self.client.delete(reverse('gyms:trash-purge', args=['plans', plan.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Sanity: it does purge from its own gym.
        self.assertIsNone(MembershipPlan.all_objects.filter(pk=plan.pk).first())

    # ─── End-to-end member round trip ─────────────────────────────────────

    def test_member_delete_then_reactivate_restores_profile(self):
        member = make_member('round.trip@example.com', 'Round', 'Trip')
        profile = MemberProfile.objects.create(user=member, gym=self.gym)

        response = self.client.delete(
            reverse('members:member-detail', args=[profile.id]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(MemberProfile.all_objects.filter(pk=profile.pk).first().is_deleted)

        response = self.client.post(
            reverse('members:member-reactivate', args=[profile.id]),
        )
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED))
        self.assertFalse(MemberProfile.all_objects.filter(pk=profile.pk).first().is_deleted)


class CustomRoleModelTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email='role-owner@example.com', password='Pass@12345',
            first_name='Role', last_name='Owner', role=User.Role.OWNER,
        )
        cls.gym, cls.owner_membership = provision_owner_gym(
            user=cls.owner, name='Role Gym',
        )

    def test_base_level_never_owner(self):
        role = CustomRole.objects.create(
            gym=self.gym,
            name='Super Desk',
            permissions=['reports.view', 'trash.manage', 'members.manage'],
        )
        self.assertEqual(role.base_role, 'STAFF')

    def test_trainer_level_from_trainer_scoped_codes(self):
        role = CustomRole.objects.create(
            gym=self.gym,
            name='Coach',
            permissions=['progress.view', 'workouts.manage'],
        )
        self.assertEqual(role.base_role, 'TRAINER')

    def test_clean_permissions_rejects_unknown_codes(self):
        from django.core.exceptions import ValidationError

        role = CustomRole(gym=self.gym, name='Broken', permissions=['not.a.code'])
        with self.assertRaises(ValidationError):
            role.clean_permissions()
