"""
Tests for owner-defined custom roles and granular permissions.

Run with:
    python manage.py test apps.gyms.test_roles

Coverage:
    - Permission catalog endpoint
    - Custom role CRUD (owner-only), validation, unique names
    - In-use roles are deactivated on delete, not destroyed
    - resolve_permissions / builtin_permissions semantics
    - RequiresPermission gating incl. fallback and misconfiguration
    - /auth/me/ exposes gym_custom_role + gym_permissions
"""
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.permissions import RequiresPermission
from apps.accounts.tokens import token_for_membership
from apps.gyms.models import CustomRole, GymMembership
from apps.gyms.role_permissions import (
    builtin_permissions,
    level_for_permissions,
    resolve_permissions,
)
from apps.gyms.services import provision_owner_gym

User = get_user_model()

ROLES_URL = '/api/gyms/roles/'
CATALOG_URL = '/api/gyms/roles/catalog/'
ME_URL = '/api/auth/me/'


class CustomRoleAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email='roles-owner@example.com', password='Pass@12345',
            first_name='Roles', last_name='Owner', role=User.Role.OWNER,
        )
        cls.gym, cls.owner_membership = provision_owner_gym(
            user=cls.owner, name='Roles Gym',
        )
        cls.staff = User.objects.create_user(
            email='roles-staff@example.com', password='Pass@12345',
            first_name='Roles', last_name='Staff', role=User.Role.STAFF,
        )
        cls.staff_membership = GymMembership.objects.create(
            user=cls.staff, gym=cls.gym,
            role=GymMembership.Role.STAFF, status=GymMembership.Status.ACTIVE,
        )
        cls.staff_membership.branch_memberships.create(
            branch=cls.gym.branches.get(is_primary=True),
        )

    def bearer(self, user, membership=None):
        token = token_for_membership(user, membership)
        return {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}

    def setUp(self):
        self.client.credentials(**self.bearer(self.owner, self.owner_membership))

    def payload(self, **overrides):
        data = {
            'name': 'Front Desk',
            'description': 'Desk duties',
            'permissions': ['members.view', 'members.manage', 'payments.manage'],
        }
        data.update(overrides)
        return data

    # ─── catalog ──────────────────────────────────────────────────────────

    def test_catalog_is_available_to_any_authenticated_user(self):
        self.client.credentials(**self.bearer(self.staff, self.staff_membership))
        response = self.client.get(CATALOG_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Members', response.data['catalog'])
        codes = [p['code'] for p in response.data['catalog']['Members']]
        self.assertIn('members.view', codes)

    def test_catalog_requires_authentication(self):
        self.client.credentials(HTTP_AUTHORIZATION='')
        response = self.client.get(CATALOG_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ─── create / list ────────────────────────────────────────────────────

    def test_owner_can_create_custom_role(self):
        response = self.client.post(ROLES_URL, self.payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['base_role'], 'STAFF')
        self.assertEqual(response.data['member_count'], 0)
        role = CustomRole.objects.get(id=response.data['id'])
        self.assertEqual(role.created_by_id, self.owner.id)
        self.assertEqual(role.gym_id, self.gym.id)

    def test_staff_cannot_create_roles(self):
        self.client.credentials(**self.bearer(self.staff, self.staff_membership))
        response = self.client.post(ROLES_URL, self.payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_name_case_insensitive_rejected(self):
        self.client.post(ROLES_URL, self.payload(), format='json')
        response = self.client.post(ROLES_URL, self.payload(name='FRONT DESK'), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

    def test_unknown_permission_codes_rejected(self):
        response = self.client.post(
            ROLES_URL, self.payload(permissions=['members.view', 'bogus.code']), format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('permissions', response.data)

    def test_blank_name_rejected(self):
        response = self.client.post(ROLES_URL, self.payload(name='   '), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_is_gym_scoped_and_hides_inactive(self):
        self.client.post(ROLES_URL, self.payload(name='Visible Role'), format='json')
        CustomRole.objects.create(gym=self.gym, name='Hidden Role', permissions=[], is_active=False)
        other_owner = User.objects.create_user(
            email='roles-other@example.com', password='Pass@12345',
            first_name='Other', last_name='Owner', role=User.Role.OWNER,
        )
        other_gym, other_membership = provision_owner_gym(user=other_owner, name='Other Roles Gym')
        CustomRole.objects.create(gym=other_gym, name='Foreign Role', permissions=[])

        response = self.client.get(ROLES_URL)
        names = [r['name'] for r in response.data]
        self.assertIn('Visible Role', names)
        self.assertNotIn('Hidden Role', names)
        self.assertNotIn('Foreign Role', names)

        response = self.client.get(ROLES_URL, {'include_inactive': 'true'})
        names = [r['name'] for r in response.data]
        self.assertIn('Hidden Role', names)
        self.assertNotIn('Foreign Role', names)

    # ─── patch / delete ───────────────────────────────────────────────────

    def test_patch_updates_permissions_and_validates(self):
        role_id = self.client.post(ROLES_URL, self.payload(), format='json').data['id']

        response = self.client.patch(
            f'{ROLES_URL}{role_id}/',
            {'permissions': ['members.view'], 'description': 'Read-only desk'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['permissions'], ['members.view'])
        self.assertEqual(response.data['base_role'], 'STAFF')

        response = self.client.patch(
            f'{ROLES_URL}{role_id}/', {'permissions': ['nope']}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_unused_role_removes_it(self):
        role_id = self.client.post(ROLES_URL, self.payload(name='Doomed'), format='json').data['id']
        response = self.client.delete(f'{ROLES_URL}{role_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], 'Role deleted.')
        self.assertFalse(CustomRole.objects.filter(id=role_id).exists())

    def test_delete_in_use_role_deactivates_instead(self):
        role_id = self.client.post(ROLES_URL, self.payload(name='In Use'), format='json').data['id']
        self.staff_membership.custom_role_id = role_id
        self.staff_membership.save(update_fields=['custom_role'])

        response = self.client.delete(f'{ROLES_URL}{role_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('deactivated', response.data['detail'])
        role = CustomRole.objects.get(id=role_id)
        self.assertFalse(role.is_active)
        # Membership still points at the role; it is simply inactive.
        self.staff_membership.refresh_from_db()
        self.assertEqual(self.staff_membership.custom_role_id, role_id)
        self.staff_membership.custom_role = None
        self.staff_membership.save(update_fields=['custom_role'])

    # ─── assignment via membership API ──────────────────────────────

    def test_owner_can_assign_custom_role_to_membership(self):
        role_id = self.client.post(ROLES_URL, self.payload(), format='json').data['id']

        response = self.client.patch(
            f'/api/gyms/{self.gym.id}/memberships/{self.staff_membership.id}/',
            {'custom_role': role_id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.staff_membership.refresh_from_db()
        self.assertEqual(self.staff_membership.custom_role_id, role_id)
        # Base role stays STAFF (derived from the role's STAFF-scoped codes).
        self.assertEqual(self.staff_membership.role, GymMembership.Role.STAFF)

        # Effective permissions in /auth/me/ now come from the custom role.
        self.client.credentials(**self.bearer(self.staff, self.staff_membership))
        me = self.client.get(ME_URL).data
        self.assertEqual(
            me['gym_permissions'],
            ['members.manage', 'members.view', 'payments.manage'],
        )
        self.staff_membership.custom_role = None
        self.staff_membership.save(update_fields=['custom_role'])

    def test_cannot_assign_custom_role_to_owner_membership(self):
        role_id = self.client.post(ROLES_URL, self.payload(), format='json').data['id']
        response = self.client.patch(
            f'/api/gyms/{self.gym.id}/memberships/{self.owner_membership.id}/',
            {'custom_role': role_id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('custom_role', response.data)

    def test_cannot_assign_foreign_gym_role(self):
        other_owner = User.objects.create_user(
            email='roles-foreign@example.com', password='Pass@12345',
            first_name='Foreign', last_name='Owner', role=User.Role.OWNER,
        )
        other_gym, _ = provision_owner_gym(user=other_owner, name='Foreign Roles Gym')
        foreign_role = CustomRole.objects.create(gym=other_gym, name='Foreign', permissions=[])

        response = self.client.patch(
            f'/api/gyms/{self.gym.id}/memberships/{self.staff_membership.id}/',
            {'custom_role': foreign_role.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_role_cannot_be_assigned(self):
        role_id = self.client.post(ROLES_URL, self.payload(name='Soon Dead'), format='json').data['id']
        self.client.patch(f'{ROLES_URL}{role_id}/', {'is_active': False}, format='json')

        response = self.client.patch(
            f'/api/gyms/{self.gym.id}/memberships/{self.staff_membership.id}/',
            {'custom_role': role_id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ─── /auth/me/ integration ────────────────────────────────────────────

    def test_me_returns_custom_role_and_permissions(self):
        role_id = self.client.post(ROLES_URL, self.payload(), format='json').data['id']
        self.staff_membership.custom_role_id = role_id
        self.staff_membership.save(update_fields=['custom_role'])

        self.client.credentials(**self.bearer(self.staff, self.staff_membership))
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['gym_custom_role'], 'Front Desk')
        self.assertEqual(
            response.data['gym_permissions'],
            ['members.manage', 'members.view', 'payments.manage'],
        )
        self.staff_membership.custom_role = None
        self.staff_membership.save(update_fields=['custom_role'])

    def test_me_falls_back_to_builtin_permissions_without_custom_role(self):
        self.client.credentials(**self.bearer(self.staff, self.staff_membership))
        response = self.client.get(ME_URL)
        self.assertIsNone(response.data['gym_custom_role'])
        expected = sorted(builtin_permissions('STAFF'))
        self.assertEqual(response.data['gym_permissions'], expected)


class PermissionResolutionTests(APITestCase):
    def test_custom_role_permissions_are_exact(self):
        codes = resolve_permissions('STAFF', ['members.view', 'payments.manage'])
        self.assertEqual(codes, {'members.view', 'payments.manage'})

    def test_builtin_owner_has_everything(self):
        from apps.gyms.role_permissions import VALID_CODES
        self.assertEqual(builtin_permissions('OWNER'), set(VALID_CODES))

    def test_builtin_staff_excludes_owner_scoped(self):
        perms = builtin_permissions('STAFF')
        self.assertIn('members.manage', perms)
        self.assertNotIn('reports.view', perms)
        self.assertNotIn('trash.manage', perms)

    def test_builtin_trainer_and_member_sets(self):
        trainer = builtin_permissions('TRAINER')
        self.assertIn('progress.manage', trainer)
        self.assertNotIn('members.view', trainer)
        member = builtin_permissions('MEMBER')
        self.assertIn('progress.view', member)
        self.assertNotIn('members.view', member)

    def test_level_for_permissions_never_owner(self):
        self.assertEqual(level_for_permissions(['trash.manage', 'impersonate']), 'STAFF')
        self.assertEqual(level_for_permissions(['diet.manage']), 'TRAINER')
        self.assertEqual(level_for_permissions([]), 'MEMBER')


class RequiresPermissionTests(APITestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request_with(self, permissions=None, gym_role='STAFF', authenticated=True):
        from types import SimpleNamespace

        request = self.factory.get('/')
        request.user = SimpleNamespace(
            email='x@example.com', is_authenticated=authenticated, role=gym_role,
        )
        request.gym_role = gym_role
        if permissions is not None:
            request.effective_permissions = set(permissions)
        return request

    class View:
        required_permissions = ['members.view']

    def test_grants_when_permission_present(self):
        request = self.request_with(permissions={'members.view', 'payments.view'})
        self.assertTrue(RequiresPermission().has_permission(request, self.View()))

    def test_denies_when_permission_missing(self):
        request = self.request_with(permissions={'members.view'})
        view = self.View()
        view.required_permissions = ['members.manage']
        self.assertFalse(RequiresPermission().has_permission(request, view))

    def test_denies_misconfigured_view(self):
        request = self.request_with(permissions={'members.view'})
        view = self.View()
        view.required_permissions = None
        self.assertFalse(RequiresPermission().has_permission(request, view))

    def test_falls_back_to_builtin_permissions_without_tenancy(self):
        # No effective_permissions attached (tenancy never ran).
        request = self.request_with(permissions=None, gym_role='STAFF')
        self.assertTrue(RequiresPermission().has_permission(request, self.View()))

        request = self.request_with(permissions=None, gym_role='MEMBER')
        self.assertFalse(RequiresPermission().has_permission(request, self.View()))

    def test_denies_unauthenticated(self):
        request = self.request_with(permissions={'members.view'}, authenticated=False)
        self.assertFalse(RequiresPermission().has_permission(request, self.View()))
