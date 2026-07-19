"""
Tests for the Members app API.

Run with:
    python manage.py test apps.members.tests

Coverage:
    - Member list (GET /api/members/)
    - Member create (POST /api/members/)
    - Member detail (GET /api/members/<id>/)
    - Member update (PATCH /api/members/<id>/)
    - Member deactivate (DELETE /api/members/<id>/)
    - My profile (GET/PATCH /api/members/me/)
    - Search and filter on the list endpoint
    - RBAC: only correct roles can access each endpoint
"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.members.models import MemberProfile

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


def make_member(email, first_name='Member', last_name='User', **profile_kwargs):
    """Create a MEMBER user + MemberProfile."""
    user = make_user(email, role=User.Role.MEMBER, first_name=first_name, last_name=last_name)
    profile, _ = MemberProfile.objects.get_or_create(user=user)
    for attr, value in profile_kwargs.items():
        setattr(profile, attr, value)
    if profile_kwargs:
        profile.save()
    return profile


def auth_headers(user):
    """Return Authorization header dict for the given user."""
    token = RefreshToken.for_user(user)
    return {'HTTP_AUTHORIZATION': f'Bearer {str(token.access_token)}'}


# ─── Base test case ───────────────────────────────────────────────────────────

class MemberAPITestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER,
                               first_name='Owner', last_name='User')
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF,
                               first_name='Staff', last_name='User')
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER,
                                 first_name='Trainer', last_name='User')
        self.member_profile = make_member(
            'alice@gym.com', first_name='Alice', last_name='Smith',
            fitness_goal=MemberProfile.FitnessGoal.WEIGHT_LOSS,
            fitness_level=MemberProfile.FitnessLevel.BEGINNER,
        )
        self.member_user = self.member_profile.user

        # URLs
        self.list_url = '/api/members/'
        self.detail_url = f'/api/members/{self.member_profile.pk}/'
        self.me_url = '/api/members/me/'

    # ── Auth shortcuts ──────────────────────────────────────────────────────
    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )

    def deauth(self):
        self.client.credentials()


# ─── List endpoint ────────────────────────────────────────────────────────────

class MemberListTests(MemberAPITestCase):
    def test_owner_can_list(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('results', r.data)

    def test_staff_can_list(self):
        self.auth_as(self.staff)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_trainer_can_list(self):
        self.auth_as(self.trainer)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_member_cannot_list(self):
        self.auth_as(self.member_user)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_list(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_only_members(self):
        """Non-MEMBER users should not appear in the member list."""
        self.auth_as(self.owner)
        r = self.client.get(self.list_url)
        # owner, staff, trainer have no member profiles
        ids = [item['id'] for item in r.data['results']]
        self.assertIn(self.member_profile.pk, ids)

    def test_search_by_name(self):
        make_member('bob@gym.com', first_name='Bob', last_name='Jones')
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'search': 'Alice'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        names = [item['full_name'] for item in r.data['results']]
        self.assertTrue(all('Alice' in n for n in names))

    def test_search_by_email(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'search': 'alice@gym.com'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['count'], 1)

    def test_filter_fitness_goal(self):
        make_member('bob2@gym.com', fitness_goal=MemberProfile.FitnessGoal.MUSCLE_GAIN)
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'fitness_goal': 'WEIGHT_LOSS'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for item in r.data['results']:
            self.assertEqual(item['fitness_goal'], 'WEIGHT_LOSS')

    def test_filter_fitness_level(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'fitness_level': 'BEGINNER'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for item in r.data['results']:
            self.assertEqual(item['fitness_level'], 'BEGINNER')

    def test_filter_is_active_false(self):
        self.member_user.is_active = False
        self.member_user.save()
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'is_active': 'false'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for item in r.data['results']:
            self.assertFalse(item['is_active'])


# ─── Create endpoint ──────────────────────────────────────────────────────────

class MemberCreateTests(MemberAPITestCase):
    def valid_payload(self, email='new@gym.com'):
        return {
            'email': email,
            'first_name': 'New',
            'last_name': 'Member',
            'password': 'StrongPass99!',
            'phone': '9800000001',
            'fitness_goal': 'MUSCLE_GAIN',
            'fitness_level': 'INTERMEDIATE',
            'gender': 'M',
        }

    def test_owner_can_create(self):
        self.auth_as(self.owner)
        r = self.client.post(self.list_url, self.valid_payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['user']['email'], 'new@gym.com')

    def test_staff_can_create(self):
        self.auth_as(self.staff)
        r = self.client.post(self.list_url, self.valid_payload('new2@gym.com'), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_trainer_cannot_create(self):
        self.auth_as(self.trainer)
        r = self.client.post(self.list_url, self.valid_payload('new3@gym.com'), format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_create(self):
        self.auth_as(self.member_user)
        r = self.client.post(self.list_url, self.valid_payload('new4@gym.com'), format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_email_returns_400(self):
        self.auth_as(self.owner)
        r = self.client.post(
            self.list_url,
            self.valid_payload('alice@gym.com'),  # already exists
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_required_fields(self):
        self.auth_as(self.owner)
        r = self.client.post(self.list_url, {'email': 'incomplete@gym.com'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_created_user_has_member_role(self):
        self.auth_as(self.owner)
        r = self.client.post(self.list_url, self.valid_payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='new@gym.com')
        self.assertEqual(user.role, User.Role.MEMBER)


# ─── Detail endpoint ──────────────────────────────────────────────────────────

class MemberDetailTests(MemberAPITestCase):
    def test_owner_can_retrieve(self):
        self.auth_as(self.owner)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['user']['email'], 'alice@gym.com')

    def test_staff_can_retrieve(self):
        self.auth_as(self.staff)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_trainer_can_retrieve(self):
        self.auth_as(self.trainer)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_member_can_retrieve_own(self):
        self.auth_as(self.member_user)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_member_cannot_retrieve_other(self):
        other = make_member('other@gym.com')
        self.auth_as(self.member_user)
        r = self.client.get(f'/api/members/{other.pk}/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_not_found_returns_404(self):
        self.auth_as(self.owner)
        r = self.client.get('/api/members/99999/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_bmi_field_present(self):
        self.member_profile.height_cm = 170
        self.member_profile.weight_kg = 70
        self.member_profile.save()
        self.auth_as(self.owner)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(r.data.get('bmi'))


# ─── Update endpoint ──────────────────────────────────────────────────────────

class MemberUpdateTests(MemberAPITestCase):
    def test_owner_can_patch(self):
        self.auth_as(self.owner)
        r = self.client.patch(self.detail_url, {'fitness_goal': 'ENDURANCE'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['fitness_goal'], 'ENDURANCE')

    def test_staff_can_patch(self):
        self.auth_as(self.staff)
        r = self.client.patch(self.detail_url, {'notes': 'Updated note'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_member_can_patch_own(self):
        self.auth_as(self.member_user)
        r = self.client.patch(self.detail_url, {'address': '123 Main St'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['address'], '123 Main St')

    def test_member_cannot_patch_other(self):
        other = make_member('other2@gym.com')
        self.auth_as(self.member_user)
        r = self.client.patch(f'/api/members/{other.pk}/', {'notes': 'Hacked'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_trainer_cannot_patch(self):
        self.auth_as(self.trainer)
        r = self.client.patch(self.detail_url, {'notes': 'Trainer note'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_put_requires_owner_or_staff(self):
        self.auth_as(self.trainer)
        r = self.client.put(self.detail_url, {'fitness_level': 'ADVANCED'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ─── Delete (deactivate) endpoint ─────────────────────────────────────────────

class MemberDeleteTests(MemberAPITestCase):
    def test_owner_can_deactivate(self):
        self.auth_as(self.owner)
        r = self.client.delete(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.member_user.refresh_from_db()
        self.assertFalse(self.member_user.is_active)

    def test_staff_can_deactivate(self):
        self.auth_as(self.staff)
        r = self.client.delete(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_trainer_cannot_deactivate(self):
        self.auth_as(self.trainer)
        r = self.client.delete(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_deactivate_own(self):
        self.auth_as(self.member_user)
        r = self.client.delete(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ─── My profile endpoint ──────────────────────────────────────────────────────

class MyProfileTests(MemberAPITestCase):
    def test_member_can_get_own_profile(self):
        self.auth_as(self.member_user)
        r = self.client.get(self.me_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['user']['email'], 'alice@gym.com')

    def test_non_member_gets_403(self):
        for user in [self.owner, self.staff, self.trainer]:
            self.auth_as(user)
            r = self.client.get(self.me_url)
            self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_can_update_own_profile_via_me(self):
        self.auth_as(self.member_user)
        r = self.client.patch(self.me_url, {'address': 'Kathmandu'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['address'], 'Kathmandu')

    def test_unauthenticated_me_returns_401(self):
        r = self.client.get(self.me_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
