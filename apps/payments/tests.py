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
from decimal import Decimal

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
        self.other_member = make_user('bob@gym.com', role=User.Role.MEMBER,
                                       first_name='Bob', last_name='Jones')
        self.list_url = '/api/payments/'

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )

    def _create_payment(self, **overrides):
        defaults = {
            'member': self.member,
            'payment_for': 'MEMBERSHIP',
            'amount': 3000,
            'discount': 0,
            'payment_method': 'CASH',
            'status': 'PAID',
            'receipt_number': 'RCPT-DEFAULT',
            'collected_by': self.staff,
        }
        defaults.update(overrides)
        return Payment.objects.create(**defaults)


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

    def test_member_sees_only_own_payments(self):
        self.auth_as(self.member)
        r = self.client.get(self.list_url)
        self.assertEqual(r.data['count'], 2)  # both belong to self.member

        # Other member's payment should not appear
        self._create_payment(member=self.other_member, receipt_number='RCPT-C')
        r = self.client.get(self.list_url)
        self.assertEqual(r.data['count'], 2)  # still only own


class PaymentAuthTests(PaymentAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_create_returns_401(self):
        r = self.client.post(self.list_url, {
            'member': self.member.id,
            'payment_for': 'MEMBERSHIP',
            'amount': '3000.00',
            'receipt_number': 'RCPT-UNAUTH',
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class PaymentDetailTests(PaymentAPITestCase):
    def setUp(self):
        super().setUp()
        self.payment = self._create_payment(receipt_number='RCPT-DETAIL')

    def test_owner_can_retrieve(self):
        self.auth_as(self.owner)
        r = self.client.get(f'{self.list_url}{self.payment.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['receipt_number'], 'RCPT-DETAIL')

    def test_member_can_retrieve_own(self):
        self.auth_as(self.member)
        r = self.client.get(f'{self.list_url}{self.payment.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_member_cannot_retrieve_other_payment(self):
        other_payment = self._create_payment(
            member=self.other_member, receipt_number='RCPT-OTHER'
        )
        self.auth_as(self.member)
        r = self.client.get(f'{self.list_url}{other_payment.id}/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class PaymentSummaryTests(PaymentAPITestCase):
    def setUp(self):
        super().setUp()
        self.summary_url = f'{self.list_url}summary/'
        self._create_payment(status='PAID', amount=5000, discount=500,
                              receipt_number='RCPT-S1')
        self._create_payment(status='PENDING', amount=2000, discount=0,
                              receipt_number='RCPT-S2')

    def test_owner_can_access_summary(self):
        self.auth_as(self.owner)
        r = self.client.get(self.summary_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('total_collected', r.data)
        self.assertIn('total_pending', r.data)
        self.assertIn('by_method', r.data)
        self.assertIn('by_status', r.data)

    def test_staff_can_access_summary(self):
        self.auth_as(self.staff)
        r = self.client.get(self.summary_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_member_cannot_access_summary(self):
        self.auth_as(self.member)
        r = self.client.get(self.summary_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_summary_collects_only_paid(self):
        self.auth_as(self.owner)
        r = self.client.get(self.summary_url)
        # PAID payment: amount=5000, discount=500, amount_paid=4500
        self.assertEqual(r.data['total_collected'], 4500.0)
        self.assertEqual(r.data['total_pending'], 2000.0)


class PaymentDiscountValidationTests(PaymentAPITestCase):
    def test_discount_cannot_exceed_amount(self):
        self.auth_as(self.staff)
        r = self.client.post(self.list_url, {
            'member': self.member.id,
            'payment_for': 'MEMBERSHIP',
            'amount': '1000.00',
            'discount': '1500.00',
            'payment_method': 'CASH',
            'status': 'PAID',
            'receipt_number': 'RCPT-BAD-DISC',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('discount', str(r.data))


class PaymentCreateRBACTests(PaymentAPITestCase):
    def test_owner_can_record_payment(self):
        self.auth_as(self.owner)
        r = self.client.post(self.list_url, {
            'member': self.member.id,
            'payment_for': 'MEMBERSHIP',
            'amount': '3000.00',
            'discount': '0.00',
            'payment_method': 'CASH',
            'status': 'PAID',
            'receipt_number': 'RCPT-OWNER',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)