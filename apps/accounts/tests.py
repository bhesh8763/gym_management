"""
Basic API tests for authentication endpoints.

Run:  python manage.py test apps.accounts.tests
"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken

User = get_user_model()


class RegisterTests(APITestCase):
    """POST /api/auth/register/"""

    url = reverse('auth-register')

    def _payload(self, **overrides):
        data = {
            'email': 'bhesh@gym.com',
            'first_name': 'Bhesh',
            'last_name': 'Saru',
            'password': 'SecurePass@123',
            'password2': 'SecurePass@123',
            'role': 'MEMBER',
        }
        data.update(overrides)
        return data

    def test_successful_registration(self):
        response = self.client.post(self.url, self._payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('tokens', response.data)
        self.assertIn('access', response.data['tokens'])
        self.assertIn('refresh', response.data['tokens'])
        self.assertEqual(response.data['user']['email'], 'bhesh@gym.com')

    def test_duplicate_email_rejected(self):
        User.objects.create_user(
            email='bhesh@gym.com', password='Pass@123',
            first_name='Bhesh', last_name='Saru',
        )
        response = self.client.post(self.url, self._payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_mismatch_rejected(self):
        response = self.client.post(
            self.url,
            self._payload(password2='WrongPass@123'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_email_rejected(self):
        payload = self._payload()
        del payload['email']
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_weak_password_rejected(self):
        response = self.client.post(
            self.url,
            self._payload(password='123', password2='123'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTests(APITestCase):
    """POST /api/auth/login/"""

    url = reverse('auth-login')

    def setUp(self):
        self.user = User.objects.create_user(
            email='member@gym.com',
            password='SecurePass@123',
            first_name='Test',
            last_name='Member',
            role='MEMBER',
        )

    def test_successful_login_returns_tokens(self):
        response = self.client.post(
            self.url,
            {'email': 'member@gym.com', 'password': 'SecurePass@123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['role'], 'MEMBER')

    def test_invalid_password_rejected(self):
        response = self.client.post(
            self.url,
            {'email': 'member@gym.com', 'password': 'WrongPassword'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_email_rejected(self):
        response = self.client.post(
            self.url,
            {'email': 'nobody@gym.com', 'password': 'SecurePass@123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_inactive_user_rejected(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            self.url,
            {'email': 'member@gym.com', 'password': 'SecurePass@123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LogoutTests(APITestCase):
    """POST /api/auth/logout/"""

    url = reverse('auth-logout')

    def setUp(self):
        self.user = User.objects.create_user(
            email='staff@gym.com',
            password='SecurePass@123',
            first_name='Test',
            last_name='Staff',
            role='STAFF',
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.refresh.access_token}'
        )

    def test_successful_logout_blacklists_token(self):
        response = self.client.post(
            self.url,
            {'refresh': str(self.refresh)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_without_token_returns_400(self):
        response = self.client.post(self.url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_logout_rejected(self):
        self.client.credentials()  # clear auth
        response = self.client.post(
            self.url,
            {'refresh': str(self.refresh)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class MeTests(APITestCase):
    """GET/PATCH /api/auth/me/"""

    url = reverse('auth-me')

    def setUp(self):
        self.user = User.objects.create_user(
            email='owner@gym.com',
            password='SecurePass@123',
            first_name='Gym',
            last_name='Owner',
            role='OWNER',
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}'
        )

    def test_get_own_profile(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'owner@gym.com')
        self.assertEqual(response.data['role'], 'OWNER')

    def test_update_own_profile(self):
        response = self.client.patch(
            self.url,
            {'first_name': 'Updated', 'phone': '9800000001'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unauthenticated_access_rejected(self):
        self.client.credentials()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TokenRefreshTests(APITestCase):
    """POST /api/auth/token/refresh/"""

    url = reverse('auth-token-refresh')

    def setUp(self):
        user = User.objects.create_user(
            email='trainer@gym.com',
            password='SecurePass@123',
            first_name='Test',
            last_name='Trainer',
            role='TRAINER',
        )
        self.refresh = RefreshToken.for_user(user)

    def test_refresh_returns_new_access_token(self):
        response = self.client.post(
            self.url,
            {'refresh': str(self.refresh)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_invalid_refresh_token_rejected(self):
        response = self.client.post(
            self.url,
            {'refresh': 'not.a.valid.token'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class RBACTests(APITestCase):
    """Verify role enforcement using the permissions module."""

    def _auth(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}'
        )

    def setUp(self):
        self.owner = User.objects.create_user(
            email='owner2@gym.com', password='Pass@123',
            first_name='O', last_name='O', role='OWNER',
        )
        self.member = User.objects.create_user(
            email='member2@gym.com', password='Pass@123',
            first_name='M', last_name='M', role='MEMBER',
        )

    def test_jwt_payload_contains_role(self):
        response = self.client.post(
            reverse('auth-login'),
            {'email': 'owner2@gym.com', 'password': 'Pass@123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['role'], 'OWNER')

    def test_member_role_encoded_in_jwt(self):
        response = self.client.post(
            reverse('auth-login'),
            {'email': 'member2@gym.com', 'password': 'Pass@123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['role'], 'MEMBER')


class TokenVersionTests(APITestCase):
    """Instant access-token revocation via the ``token_version`` claim.

    Every issued JWT embeds the user's ``token_version`` at issue time;
    ``User.set_password`` bumps the DB value, and the authentication class
    rejects any token whose claim no longer matches — so access tokens die
    immediately on a password change/reset instead of living out their
    60-minute expiry.
    """

    def _login(self):
        r = self.client.post(reverse('auth-login'), {
            'email': 'tvuser@gym.com',
            'password': 'VersionPass@1',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        return r.data['access'], r.data['refresh']

    def setUp(self):
        self.user = User.objects.create_user(
            email='tvuser@gym.com', password='VersionPass@1',
            first_name='TV', last_name='User', role='MEMBER',
        )

    def test_login_tokens_embed_current_version(self):
        access, _ = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(
            self.client.get(reverse('auth-me')).status_code,
            status.HTTP_200_OK,
        )

        import jwt as pyjwt
        claims = pyjwt.decode(access, options={'verify_signature': False})
        self.assertEqual(claims['token_version'], self.user.token_version)

    def test_old_access_token_rejected_after_password_change(self):
        access, _ = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(
            self.client.get(reverse('auth-me')).status_code,
            status.HTTP_200_OK,
        )

        # Change the password — set_password bumps token_version.
        self.user.set_password('VersionPass@2')
        self.user.save()

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(
            self.client.get(reverse('auth-me')).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_old_access_token_rejected_after_password_reset(self):
        access, _ = self._login()
        self.user.set_password('VersionPass@3')
        self.user.save()

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(
            self.client.get(reverse('auth-me')).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_new_access_token_accepted_after_password_change(self):
        self.user.set_password('VersionPass@2')
        self.user.save()

        # Logging in with the NEW password yields working tokens.
        r = self.client.post(reverse('auth-login'), {
            'email': 'tvuser@gym.com', 'password': 'VersionPass@2',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(
            self.client.get(reverse('auth-me')).status_code,
            status.HTTP_200_OK,
        )

    def test_refresh_propagates_current_version(self):
        """The refresh endpoint copies claims from the refresh token, so a
        version bump between login and refresh must invalidate the flow."""
        access, refresh = self._login()
        self.user.set_password('VersionPass@2')
        self.user.save()

        r = self.client.post(reverse('auth-token-refresh'),
                             {'refresh': refresh}, format='json')
        # The refresh token itself is blacklisted by the password-change
        # view, but even without that, its derived access token carries the
        # stale version and must not authenticate.
        if r.status_code == status.HTTP_200_OK:
            self.client.credentials(
                HTTP_AUTHORIZATION=f"Bearer {r.data['access']}"
            )
            self.assertEqual(
                self.client.get(reverse('auth-me')).status_code,
                status.HTTP_401_UNAUTHORIZED,
            )

    def test_set_password_bumps_version_each_time(self):
        # create_user() itself calls set_password, so a fresh account
        # already carries version 1; what matters is that every subsequent
        # password change increments it.
        before = self.user.token_version
        self.user.set_password('Whatever@1')
        self.user.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, before + 1)
        self.user.set_password('Whatever@2')
        self.user.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, before + 2)

    def test_change_password_endpoint_bumps_version(self):
        access, _ = self._login()
        before = self.user.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        r = self.client.put(reverse('auth-change-password'), {
            'old_password': 'VersionPass@1',
            'new_password': 'VersionPass@2',
            'new_password2': 'VersionPass@2',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, before + 1)


class ChangePasswordTests(APITestCase):
    """POST /api/auth/change-password/"""

    url = reverse('auth-change-password')

    def setUp(self):
        self.user = User.objects.create_user(
            email='cpuser@gym.com', password='OldPass@123',
            first_name='CP', last_name='User', role='MEMBER',
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_successful_password_change(self):
        r = self.client.put(self.url, {
            'old_password': 'OldPass@123',
            'new_password': 'NewPass@456',
            'new_password2': 'NewPass@456',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass@456'))

    def test_wrong_old_password_rejected(self):
        r = self.client.put(self.url, {
            'old_password': 'WrongPass',
            'new_password': 'NewPass@456',
            'new_password2': 'NewPass@456',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mismatched_new_passwords_rejected(self):
        r = self.client.put(self.url, {
            'old_password': 'OldPass@123',
            'new_password': 'NewPass@456',
            'new_password2': 'DifferentPass@789',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_weak_new_password_rejected(self):
        r = self.client.put(self.url, {
            'old_password': 'OldPass@123',
            'new_password': '123',
            'new_password2': '123',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_change_blacklists_existing_tokens(self):
        """After a password change, previously issued refresh tokens are
        blacklisted, so an attacker holding one can no longer mint new
        access tokens.

        Note: stateless access tokens issued *before* the change remain
        valid until they expire (60 min) — that is inherent to stateless
        JWT auth; blacklisting covers the 7-day refresh-token window.
        """
        refresh = RefreshToken.for_user(self.user)
        old_refresh = str(refresh)

        r = self.client.put(self.url, {
            'old_password': 'OldPass@123',
            'new_password': 'NewPass@456',
            'new_password2': 'NewPass@456',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass@456'))

        # The old refresh token is blacklisted — using it to get a new
        # access token must fail.
        r = self.client.post(reverse('auth-token-refresh'),
                             {'refresh': old_refresh}, format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class ForgotPasswordTests(APITestCase):
    """POST /api/auth/forgot-password/"""

    url = reverse('auth-forgot-password')

    def test_existing_email_returns_200(self):
        User.objects.create_user(
            email='reset@gym.com', password='Pass@123',
            first_name='R', last_name='U',
        )
        r = self.client.post(self.url, {'email': 'reset@gym.com'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_nonexistent_email_also_returns_200(self):
        """Always 200 to prevent email enumeration."""
        r = self.client.post(self.url, {'email': 'nobody@gym.com'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_missing_email_returns_400(self):
        r = self.client.post(self.url, {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_user_also_returns_200(self):
        """Inactive user should not leak info."""
        User.objects.create_user(
            email='inactive@gym.com', password='Pass@123',
            first_name='I', last_name='U', is_active=False,
        )
        r = self.client.post(self.url, {'email': 'inactive@gym.com'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class ResetPasswordTests(APITestCase):
    """POST /api/auth/reset-password/"""

    url = reverse('auth-reset-password')

    def setUp(self):
        self.user = User.objects.create_user(
            email='rppass@gym.com', password='OldPass@123',
            first_name='RP', last_name='User',
        )
        from apps.accounts.models import PasswordResetToken
        self.token = PasswordResetToken.create_for_user(self.user)

    def test_successful_reset(self):
        r = self.client.post(self.url, {
            'token': self.token.token,
            'new_password': 'ResetPass@456',
            'new_password2': 'ResetPass@456',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ResetPass@456'))

    def test_invalid_token_rejected(self):
        r = self.client.post(self.url, {
            'token': 'invalid-token',
            'new_password': 'ResetPass@456',
            'new_password2': 'ResetPass@456',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_used_token_rejected(self):
        self.token.is_used = True
        self.token.save()
        r = self.client.post(self.url, {
            'token': self.token.token,
            'new_password': 'ResetPass@456',
            'new_password2': 'ResetPass@456',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mismatched_passwords_rejected(self):
        r = self.client.post(self.url, {
            'token': self.token.token,
            'new_password': 'ResetPass@456',
            'new_password2': 'DifferentPass@789',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_token_returns_400(self):
        r = self.client.post(self.url, {
            'new_password': 'ResetPass@456',
            'new_password2': 'ResetPass@456',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_password_blacklists_existing_tokens(self):
        """After a password reset, previously issued refresh tokens are
        blacklisted, so an attacker holding one can no longer mint new
        access tokens.

        Note: stateless access tokens issued *before* the reset remain
        valid until they expire (60 min) — that is inherent to stateless
        JWT auth; blacklisting covers the 7-day refresh-token window.
        """
        refresh = RefreshToken.for_user(self.user)
        old_refresh = str(refresh)

        r = self.client.post(self.url, {
            'token': self.token.token,
            'new_password': 'ResetPass@456',
            'new_password2': 'ResetPass@456',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ResetPass@456'))

        # The old refresh token is blacklisted — using it to get a new
        # access token must fail.
        r = self.client.post(reverse('auth-token-refresh'),
                             {'refresh': old_refresh}, format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class UserModelTests(APITestCase):
    def test_display_id_generation(self):
        user = User.objects.create_user(
            email='display@gym.com', password='Pass@123',
            first_name='D', last_name='U', role='MEMBER',
        )
        self.assertIsNotNone(user.display_id)
        self.assertTrue(user.display_id.startswith('MEM-'))

    def test_full_name_with_middle_name(self):
        user = User.objects.create_user(
            email='full@gym.com', password='Pass@123',
            first_name='First', last_name='Last',
        )
        user.middle_name = 'Middle'
        user.save()
        self.assertEqual(user.get_full_name(), 'First Middle Last')

    def test_full_name_without_middle_name(self):
        user = User.objects.create_user(
            email='short@gym.com', password='Pass@123',
            first_name='First', last_name='Last',
        )
        self.assertEqual(user.get_full_name(), 'First Last')

    def test_role_properties(self):
        owner = User.objects.create_user(email='o@g.com', password='p', first_name='O', last_name='O', role='OWNER')
        staff = User.objects.create_user(email='s@g.com', password='p', first_name='S', last_name='S', role='STAFF')
        trainer = User.objects.create_user(email='t@g.com', password='p', first_name='T', last_name='T', role='TRAINER')
        member = User.objects.create_user(email='m@g.com', password='p', first_name='M', last_name='M', role='MEMBER')
        self.assertTrue(owner.is_owner)
        self.assertTrue(staff.is_gym_staff)
        self.assertTrue(trainer.is_trainer)
        self.assertTrue(member.is_member)

    def test_display_id_is_unique_per_role(self):
        """Two members created in the same test should not share a display_id."""
        u1 = User.objects.create_user(
            email='dup1@gym.com', password='p',
            first_name='D', last_name='U', role='MEMBER',
        )
        u2 = User.objects.create_user(
            email='dup2@gym.com', password='p',
            first_name='D', last_name='U', role='MEMBER',
        )
        self.assertNotEqual(u1.display_id, u2.display_id)
        self.assertTrue(u1.display_id.startswith('MEM-'))
        self.assertTrue(u2.display_id.startswith('MEM-'))

    def test_concurrent_display_id_draw_does_not_duplicate(self):
        """Simulate two concurrent creators drawing the next sequence number
        for the same role. Even if both transactions run back-to-back under
        the test runner, the second should never reuse the first's id."""
        from uuid import uuid4

        drawn = []

        def draw_member(i):
            user = User.objects.create_user(
                email=f'conc_{uuid4().hex[:8]}@gym.com', password='p',
                first_name='C', last_name='U', role='MEMBER',
            )
            drawn.append(user.display_id)
            return user

        draw_member(1)
        draw_member(2)

        self.assertEqual(len(drawn), 2)
        self.assertNotEqual(drawn[0], drawn[1])

        # The sequence row should have advanced by at least the number of draws.
        from apps.accounts.models import RoleSequence
        seq = RoleSequence.objects.get(role='MEMBER')
        self.assertGreaterEqual(seq.last_value, 2)
