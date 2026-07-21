"""
Tests for the Payments app API.

Run with:
    python manage.py test apps.payments.tests

Coverage:
    - Payment create (POST /api/payments/)
    - amount_paid auto-calculation (amount - discount)
    - collected_by auto-populated from the authenticated user
    - Filtering by member/status/payment_for
    - RBAC: members cannot record payments, staff-side roles can
    - Duplicate receipt_number is rejected (unique constraint)
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.payments.models import Payment

User = get_user_model()


def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


class PaymentAPITestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER,
                                first_name='Owner', last_name='User')
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF,
                                first_name='Staff', last_name='User')
        self.member = make_user('alice@gym.com', role=User.Role.MEMBER,
                                 first_name='Alice', last_name='Smith')
        self.list_url = '/api/payments/'

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )


class PaymentCreateTests(PaymentAPITestCase):
    def test_staff_can_record_payment(self):
        self.auth_as(self.staff)
        r = self.client.post(self.list_url, {
            'member': self.member.id,
            'payment_for': 'MEMBERSHIP',
            'amount': '3000.00',
            'discount': '0.00',
            'payment_method': 'CASH',
            'status': 'PAID',
            'receipt_number': 'RCPT-TEST-001',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['collected_by'], self.staff.id)

    def test_amount_paid_is_amount_minus_discount(self):
        self.auth_as(self.staff)
        r = self.client.post(self.list_url, {
            'member': self.member.id,
            'payment_for': 'MEMBERSHIP',
            'amount': '3000.00',
            'discount': '500.00',
            'payment_method': 'CASH',
            'status': 'PAID',
            'receipt_number': 'RCPT-TEST-002',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['amount_paid'], '2500.00')

    def test_member_cannot_record_payment(self):
        self.auth_as(self.member)
        r = self.client.post(self.list_url, {
            'member': self.member.id,
            'payment_for': 'MEMBERSHIP',
            'amount': '3000.00',
            'payment_method': 'CASH',
            'status': 'PAID',
            'receipt_number': 'RCPT-TEST-003',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_receipt_number_is_rejected(self):
        self.auth_as(self.staff)
        payload = {
            'member': self.member.id,
            'payment_for': 'MEMBERSHIP',
            'amount': '1000.00',
            'payment_method': 'CASH',
            'status': 'PAID',
            'receipt_number': 'RCPT-DUP',
        }
        first = self.client.post(self.list_url, payload)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        payload['member'] = self.member.id  # same receipt, different amount below
        payload['amount'] = '2000.00'
        second = self.client.post(self.list_url, payload)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)


class PaymentListTests(PaymentAPITestCase):
    def setUp(self):
        super().setUp()
        Payment.objects.create(
            member=self.member, payment_for='MEMBERSHIP', amount=3000, discount=0,
            payment_method='CASH', status='PAID', receipt_number='RCPT-A',
            collected_by=self.staff,
        )
        Payment.objects.create(
            member=self.member, payment_for='LOCKER', amount=500, discount=0,
            payment_method='ESEWA', status='PENDING', receipt_number='RCPT-B',
            collected_by=self.staff,
        )

    def test_owner_can_list_all(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url)
        self.assertEqual(r.data['count'], 2)

    def test_filter_by_status(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'status': 'PENDING'})
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['receipt_number'], 'RCPT-B')

    def test_filter_by_member(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'member': self.member.id})
        self.assertEqual(r.data['count'], 2)

    def test_filter_by_payment_for(self):
        self.auth_as(self.owner)
        r = self.client.get(self.list_url, {'payment_for': 'LOCKER'})
        self.assertEqual(r.data['count'], 1)