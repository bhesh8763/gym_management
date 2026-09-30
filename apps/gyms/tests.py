from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import PlanSubscription
from apps.accounts.tokens import token_for_membership
from apps.attendance.models import Attendance
from apps.gyms.models import Branch, GymMembership
from apps.gyms.services import provision_owner_gym

User = get_user_model()


class GymTenancyAPITests(APITestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(
            email='owner-a@example.com', password='Pass@12345',
            first_name='Owner', last_name='A', role=User.Role.OWNER,
        )
        self.owner_b = User.objects.create_user(
            email='owner-b@example.com', password='Pass@12345',
            first_name='Owner', last_name='B', role=User.Role.OWNER,
        )
        self.gym_a, self.owner_a_membership = provision_owner_gym(
            user=self.owner_a, name='Gym A',
        )
        self.gym_b, self.owner_b_membership = provision_owner_gym(
            user=self.owner_b, name='Gym B',
        )
        self.member = User.objects.create_user(
            email='member@example.com', password='Pass@12345',
            first_name='Test', last_name='Member', role=User.Role.MEMBER,
        )
        self.member_membership = GymMembership.objects.create(
            user=self.member,
            gym=self.gym_a,
            role=GymMembership.Role.MEMBER,
            status=GymMembership.Status.ACTIVE,
        )
        self.member_membership.branch_memberships.create(
            branch=self.gym_a.branches.get(is_primary=True),
        )

    def bearer(self, user, membership=None):
        token = token_for_membership(user, membership)
        return {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}

    def test_registration_and_switch_tokens_carry_tenant_claims(self):
        response = self.client.post(
            reverse('auth-register'),
            {
                'email': 'new-owner@example.com',
                'first_name': 'New',
                'last_name': 'Owner',
                'password': 'Pass@12345',
                'password2': 'Pass@12345',
                'gym_name': 'New Gym',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(response.data['user']['gym_id'])
        self.assertEqual(response.data['user']['gym_role'], GymMembership.Role.OWNER)

        user = User.objects.get(email='owner-b@example.com')
        response = self.client.post(
            reverse('gyms:gym-switch'),
            {'gym_id': self.gym_b.id},
            **self.bearer(user),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['gym']['id'], self.gym_b.id)
        self.assertEqual(response.data['role'], GymMembership.Role.OWNER)

    def test_membership_api_keeps_gym_data_separate(self):
        url = reverse('gyms:gym-memberships', args=[self.gym_a.id])
        response = self.client.post(
            url,
            {
                'email': 'member@example.com',
                'first_name': 'Test',
                'last_name': 'Member',
                'role': GymMembership.Role.MEMBER,
            },
            **self.bearer(self.owner_a, self.owner_a_membership),
            format='json',
        )
        # Existing member is already in Gym A, so the request is rejected.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(
            reverse('gyms:gym-memberships', args=[self.gym_b.id]),
            **self.bearer(self.owner_a, self.owner_a_membership),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invitation_accepts_new_user_and_never_resets_existing_password(self):
        response = self.client.post(
            reverse('gyms:gym-invitations', args=[self.gym_a.id]),
            {'email': 'invited@example.com', 'role': GymMembership.Role.MEMBER},
            **self.bearer(self.owner_a, self.owner_a_membership),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        token = response.data['invitation_url'].split('token=')[-1]

        response = self.client.post(
            reverse('gyms:gym-invitation-accept'),
            {
                'token': token,
                'password': 'NewPass@123',
                'first_name': 'Invited',
                'last_name': 'User',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        invited = User.objects.get(email='invited@example.com')
        self.assertTrue(invited.check_password('NewPass@123'))
        self.assertTrue(
            GymMembership.objects.filter(
                user=invited, gym=self.gym_a, role=GymMembership.Role.MEMBER,
                status=GymMembership.Status.ACTIVE,
            ).exists()
        )

    def test_branch_header_scopes_tenant_manager(self):
        branch = Branch.objects.create(
            gym=self.gym_a, name='North Branch', code='NORTH',
        )
        self.assertEqual(
            self.client.get(
                reverse('gyms:gym-current'),
                **self.bearer(self.member, self.member_membership),
                HTTP_X_BRANCH_ID=str(branch.id),
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.member_membership.branch_memberships.create(branch=branch)
        response = self.client.get(
            reverse('gyms:gym-current'),
            **self.bearer(self.member, self.member_membership),
            HTTP_X_BRANCH_ID=str(branch.id),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_impersonation_is_time_bound_and_audited(self):
        response = self.client.post(
            reverse('gyms:gym-impersonate-start', args=[self.gym_a.id]),
            {'user_id': self.member.id, 'reason': 'Support investigation'},
            **self.bearer(self.owner_a, self.owner_a_membership),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        session_id = response.data['session_id']
        impersonation_refresh = response.data['refresh']
        self.assertTrue(
            self.gym_a.audit_logs.filter(action='impersonation.started').exists()
        )

        response = self.client.post(
            reverse('gyms:gym-impersonate-end', args=[session_id]),
            **self.bearer(self.owner_a, self.owner_a_membership),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            self.gym_a.audit_logs.filter(action='impersonation.ended').exists()
        )
        response = self.client.post(
            '/api/auth/token/refresh/',
            {'refresh': impersonation_refresh},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_existing_invitation_never_resets_password(self):
        response = self.client.post(
            reverse('gyms:gym-invitations', args=[self.gym_a.id]),
            {'email': self.member.email, 'role': GymMembership.Role.MEMBER},
            **self.bearer(self.owner_a, self.owner_a_membership),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        token = response.data['invitation_url'].split('token=')[-1]

        response = self.client.post(
            reverse('gyms:gym-invitation-accept'),
            {'token': token, 'current_password': 'wrong-password'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('Pass@12345'))

        response = self.client.post(
            reverse('gyms:gym-invitation-accept'),
            {'token': token, 'current_password': 'Pass@12345'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password('Pass@12345'))

    @override_settings(REQUIRE_OWNER_SUBSCRIPTION=True)
    def test_owner_subscription_is_enforced_server_side(self):
        response = self.client.post(
            reverse('gyms:gym-memberships', args=[self.gym_a.id]),
            {
                'email': 'new-paid-member@example.com',
                'first_name': 'Paid',
                'last_name': 'Member',
                'password': 'Pass@12345',
                'role': GymMembership.Role.MEMBER,
            },
            **self.bearer(self.owner_a, self.owner_a_membership),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)

        PlanSubscription.objects.create(
            user=self.owner_a,
            gym=self.gym_a,
            plan='gold',
            price=9999,
            method='card',
            reference='TEST-SUB-001',
            status='paid',
        )
        response = self.client.post(
            reverse('gyms:gym-memberships', args=[self.gym_a.id]),
            {
                'email': 'new-paid-member@example.com',
                'first_name': 'Paid',
                'last_name': 'Member',
                'password': 'Pass@12345',
                'role': GymMembership.Role.MEMBER,
            },
            **self.bearer(self.owner_a, self.owner_a_membership),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_user_can_hold_memberships_in_two_gyms_and_switch(self):
        response = self.client.post(
            reverse('gyms:gym-memberships', args=[self.gym_b.id]),
            {
                'email': self.member.email,
                'first_name': self.member.first_name,
                'last_name': self.member.last_name,
                'role': GymMembership.Role.MEMBER,
            },
            **self.bearer(self.owner_b, self.owner_b_membership),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        membership_b = GymMembership.objects.get(user=self.member, gym=self.gym_b)

        response = self.client.get(
            reverse('gyms:gym-current'),
            **self.bearer(self.member, membership_b),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.gym_b.id)

    def test_branch_header_scopes_member_attendance(self):
        second_branch = Branch.objects.create(
            gym=self.gym_a,
            name='Second Branch',
            code='SECOND',
        )
        self.member_membership.branch_memberships.create(branch=second_branch)
        primary_branch = self.gym_a.branches.get(is_primary=True)
        today = timezone.localdate()
        primary_attendance = Attendance.objects.create(
            gym=self.gym_a,
            branch=primary_branch,
            user=self.member,
            attendance_type=Attendance.AttendanceType.MEMBER,
            date=today,
        )
        second_attendance = Attendance.objects.create(
            gym=self.gym_a,
            branch=second_branch,
            user=self.member,
            attendance_type=Attendance.AttendanceType.MEMBER,
            date=today - timedelta(days=1),
        )

        response = self.client.get(
            '/api/attendance/records/',
            **{
                **self.bearer(self.member, self.member_membership),
                'HTTP_X_BRANCH_ID': str(primary_branch.id),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        primary_results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        self.assertIn(primary_attendance.id, [row['id'] for row in primary_results])
        self.assertNotIn(second_attendance.id, [row['id'] for row in primary_results])

        response = self.client.get(
            '/api/attendance/records/',
            **{
                **self.bearer(self.member, self.member_membership),
                'HTTP_X_BRANCH_ID': str(second_branch.id),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        second_results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        self.assertIn(second_attendance.id, [row['id'] for row in second_results])
        self.assertNotIn(primary_attendance.id, [row['id'] for row in second_results])
