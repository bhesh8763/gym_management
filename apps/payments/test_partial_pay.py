"""
Tests for member self-service partial payments.

Run with:
    python manage.py test apps.payments.test_partial_pay

Coverage:
    - /api/payments/pay/ with optional `amount` (partial instalments)
    - amount validation: below minimum rejected, >= outstanding clamped to full
    - PARTIAL status + amount_paid semantics on the Payment record
    - signal-driven accumulation into Membership.price_paid
    - membership activates only when the plan price is fully covered
    - my-dues reflects the remaining balance after instalments
    - due_remaining on the serializer
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.tokens import token_for_membership
from apps.gyms.models import GymMembership
from apps.gyms.services import provision_owner_gym
from apps.lockers.models import Locker, LockerAssignment
from apps.memberships.models import Membership, MembershipPlan
from apps.payments.models import Payment

User = get_user_model()

PAY_URL = '/api/payments/pay/'
DUES_URL = '/api/payments/my-dues/'


class PartialPayTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email='pay-owner@example.com', password='Pass@12345',
            first_name='Pay', last_name='Owner', role=User.Role.OWNER,
        )
        cls.gym, cls.owner_membership = provision_owner_gym(
            user=cls.owner, name='Partial Pay Gym',
        )
        cls.member = User.objects.create_user(
            email='pay-member@example.com', password='Pass@12345',
            first_name='Paying', last_name='Member', role=User.Role.MEMBER,
        )
        cls.member_membership = GymMembership.objects.create(
            user=cls.member,
            gym=cls.gym,
            role=GymMembership.Role.MEMBER,
            status=GymMembership.Status.ACTIVE,
        )
        # Non-owner roles must have exactly one branch membership for the
        # request tenancy to resolve (see resolve_request_tenant).
        cls.member_membership.branch_memberships.create(
            branch=cls.gym.branches.get(is_primary=True),
        )
        cls.plan = MembershipPlan.objects.create(
            gym=cls.gym, name='Instalment Plan', duration_days=30, price=Decimal('3000.00'),
        )

    def setUp(self):
        token = token_for_membership(self.member, self.member_membership)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        self.membership = Membership.objects.create(
            gym=self.gym,
            member=self.member,
            plan=self.plan,
            status=Membership.Status.PENDING,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timezone.timedelta(days=30),
            price_paid=Decimal('0'),
        )

    def tearDown(self):
        Payment.all_objects.all().delete()
        self.membership.refresh_from_db()
        self.membership.delete(hard=True)

    # ─── helpers ──────────────────────────────────────────────────────────

    def pay(self, **payload):
        defaults = {
            'payment_for': 'MEMBERSHIP',
            'reference_id': self.membership.id,
            'payment_method': 'CASH',
        }
        defaults.update(payload)
        return self.client.post(PAY_URL, defaults, format='json')

    # ─── partial payment creation ─────────────────────────────────────────

    def test_partial_payment_creates_partial_record(self):
        response = self.pay(amount='1000')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['status'], 'PARTIAL')
        self.assertEqual(Decimal(str(response.data['amount_paid'])), Decimal('1000.00'))
        # Record-level remainder: this instalment was fully collected.
        self.assertEqual(Decimal(str(response.data['due_remaining'])), Decimal('0.00'))
        self.assertIn('Partial payment', response.data['notes'])

    def test_partial_accumulates_price_paid_and_stays_pending(self):
        self.pay(amount='1000')
        self.pay(amount='1000')
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.price_paid, Decimal('2000.00'))
        self.assertEqual(self.membership.status, Membership.Status.PENDING)

        # my-dues now shows only the remainder
        response = self.client.get(DUES_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dues = [d for d in response.data['dues'] if d['reference_id'] == self.membership.id]
        self.assertEqual(len(dues), 1)
        self.assertEqual(Decimal(str(dues[0]['amount'])), Decimal('1000.00'))

    def test_final_instalment_activates_membership(self):
        self.pay(amount='1000')
        self.pay(amount='1000')
        response = self.pay(amount='1000')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Non-gateway FULL payments land PENDING until staff confirm them
        # at the desk (existing design); only partials confirm immediately.
        self.assertEqual(response.data['status'], 'PENDING')

        # Staff confirms the final instalment → signal activates membership.
        final = Payment.objects.get(pk=response.data['id'])
        final.status = Payment.PaymentStatus.PAID
        final.save()

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.price_paid, Decimal('3000.00'))
        self.assertEqual(self.membership.status, Membership.Status.ACTIVE)

    def test_amount_at_or_above_outstanding_pays_full_balance(self):
        response = self.pay(amount='9999')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Clamped to the outstanding balance and lands PENDING (cash flow).
        self.assertEqual(Decimal(str(response.data['amount'])), Decimal('3000.00'))
        self.assertEqual(response.data['status'], 'PENDING')

    def test_omitted_amount_pays_full_outstanding(self):
        response = self.pay()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(response.data['amount'])), Decimal('3000.00'))
        self.assertEqual(response.data['status'], 'PENDING')

    # ─── validation ───────────────────────────────────────────────────────

    def test_amount_below_minimum_rejected(self):
        response = self.pay(amount='0.50')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', response.data)

    def test_zero_or_negative_amount_rejected(self):
        response = self.pay(amount='0')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.pay(amount='-5')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_numeric_amount_rejected(self):
        response = self.pay(amount='abc')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', response.data)

    def test_string_full_amount_is_accepted(self):
        response = self.pay(amount='full')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(response.data['amount'])), Decimal('3000.00'))
        self.assertEqual(response.data['status'], 'PENDING')

    def test_paid_due_blocks_new_payment(self):
        response = self.pay()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Staff confirms the payment at the desk.
        payment = Payment.objects.get(pk=response.data['id'])
        payment.status = Payment.PaymentStatus.PAID
        payment.save()

        response = self.pay(amount='500')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already paid', str(response.data))

    # ─── locker partial payments ──────────────────────────────────────────

    def test_locker_partial_payment(self):
        locker = Locker.objects.create(
            gym=self.gym, locker_number='P1', monthly_fee=Decimal('300.00'),
        )
        LockerAssignment.objects.create(
            gym=self.gym, locker=locker, member=self.member,
            start_date=timezone.localdate(),
        )
        response = self.pay(
            payment_for='LOCKER', reference_id=locker.assignments.first().id, amount='100',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'PARTIAL')
        self.assertEqual(Decimal(str(response.data['amount_paid'])), Decimal('100.00'))
        # Locker dues are one-shot per record: nothing left on this record.
        self.assertEqual(Decimal(str(response.data['due_remaining'])), Decimal('0.00'))

    # ─── signals / accumulation semantics ─────────────────────────────────

    def test_refunded_partial_releases_accumulated_total(self):
        self.pay(amount='1000')
        self.pay(amount='1000')
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.price_paid, Decimal('2000.00'))

        # Refund the second instalment (edit flow a staff member might use).
        second = Payment.objects.filter(status=Payment.PaymentStatus.PARTIAL).order_by('id').last()
        second.status = Payment.PaymentStatus.REFUNDED
        second.save()

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.price_paid, Decimal('1000.00'))
