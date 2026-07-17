"""
Basic API tests for authentication endpoints.

Run:  python manage.py test apps.accounts.tests
"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

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
