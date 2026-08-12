"""
Tests for the Notifications app.

Coverage:
  - Notification model (mark_read, __str__)
  - PAYMENT_RECEIVED signal (fires on PAID/PARTIAL, skips other statuses,
    idempotency guard)
  - send_reminders management command
      * _send_membership_renewal_reminders
      * _send_payment_due_reminders
      * _send_inactivity_alerts
      * _send_workout_reminders
      * idempotency (no duplicates when run twice on the same day)
  - Notification API views
      * GET  /api/notifications/                (list, filters)
      * POST /api/notifications/               (create, permission)
      * GET  /api/notifications/unread-count/
      * PATCH /api/notifications/<id>/read/
      * POST /api/notifications/mark-all-read/
      * DELETE /api/notifications/<id>/
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.attendance.models import Attendance
from apps.memberships.models import Membership, MembershipPlan
from apps.notifications.models import Notification
from apps.payments.models import Payment
from apps.workouts.models import (
    WorkoutAssignment,
    WorkoutCompletionLog,
    WorkoutDay,
    WorkoutTemplate,
)

User = get_user_model()

# ─── Helpers ──────────────────────────────────────────────────────────────────


def unique_email(prefix='user'):
    """Return an email that is guaranteed unique within this test run."""
    return f'{prefix}_{uuid.uuid4().hex[:8]}@test.com'


def make_user(role=User.Role.MEMBER, email=None, **kw):
    return User.objects.create_user(
        email=email or unique_email(role.lower()),
        password='testpass123',
        first_name=kw.pop('first_name', 'Test'),
        last_name=kw.pop('last_name', 'User'),
        role=role,
        **kw,
    )


def make_payment(member, staff, status_=Payment.PaymentStatus.PAID, amount=1000):
    """Create a minimal Payment with a guaranteed-unique receipt number."""
    return Payment.objects.create(
        member=member,
        payment_for=Payment.PaymentFor.MEMBERSHIP,
        amount=Decimal(str(amount)),
        discount=Decimal('0'),
        amount_paid=Decimal(str(amount)),  # recomputed by save()
        payment_method=Payment.PaymentMethod.CASH,
        status=status_,
        receipt_number=f'RCP-{uuid.uuid4().hex[:8].upper()}',
        collected_by=staff,
    )


def make_membership_plan(name=None, days=30):
    name = name or f'Plan-{uuid.uuid4().hex[:6]}'
    return MembershipPlan.objects.create(
        name=name,
        billing_cycle=MembershipPlan.BillingCycle.MONTHLY,
        duration_days=days,
        price=Decimal('500'),
    )


def make_membership(member, plan, start, end, status_=Membership.Status.ACTIVE):
    return Membership.objects.create(
        member=member,
        plan=plan,
        status=status_,
        start_date=start,
        end_date=end,
        price_paid=plan.price,
    )


def make_workout_assignment(member, trainer, status_=WorkoutAssignment.Status.ACTIVE):
    template = WorkoutTemplate.objects.create(
        trainer=trainer,
        name=f'Plan-{uuid.uuid4().hex[:6]}',
        difficulty='BEGINNER',
    )
    return WorkoutAssignment.objects.create(
        template=template,
        member=member,
        assigned_by=trainer,
        status=status_,
        start_date=date.today(),
    )


def auth_header(user):
    """Return Bearer token header dict for DRF APITestCase."""
    token = RefreshToken.for_user(user)
    return {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}


# ─── Notification model tests ─────────────────────────────────────────────────


class NotificationModelTest(TestCase):

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)

    def _make(self, **kw):
        defaults = dict(
            recipient=self.member,
            notification_type=Notification.NotificationType.GENERAL,
            title='Hello',
            message='Test message',
        )
        defaults.update(kw)
        return Notification.objects.create(**defaults)

    def test_str(self):
        n = self._make(title='Greetings')
        self.assertIn('Greetings', str(n))

    def test_mark_read_sets_fields(self):
        n = self._make()
        self.assertFalse(n.is_read)
        self.assertIsNone(n.read_at)
        n.mark_read()
        n.refresh_from_db()
        self.assertTrue(n.is_read)
        self.assertIsNotNone(n.read_at)

    def test_mark_read_idempotent(self):
        """Calling mark_read twice should not raise or change read_at."""
        n = self._make()
        n.mark_read()
        first_read_at = n.read_at
        n.mark_read()
        self.assertEqual(n.read_at, first_read_at)

    def test_default_is_read_false(self):
        n = self._make()
        self.assertFalse(n.is_read)


# ─── PAYMENT_RECEIVED signal tests ────────────────────────────────────────────


class PaymentReceivedSignalTest(TestCase):

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.staff = make_user(role=User.Role.STAFF)

    def _notification_count(self):
        return Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.PAYMENT_RECEIVED,
        ).count()

    def test_paid_payment_creates_notification(self):
        make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PAID)
        self.assertEqual(self._notification_count(), 1)

    def test_partial_payment_creates_notification(self):
        make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PARTIAL)
        self.assertEqual(self._notification_count(), 1)

    def test_pending_payment_does_not_create_notification(self):
        make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PENDING)
        self.assertEqual(self._notification_count(), 0)

    def test_failed_payment_does_not_create_notification(self):
        make_payment(self.member, self.staff, status_=Payment.PaymentStatus.FAILED)
        self.assertEqual(self._notification_count(), 0)

    def test_notification_message_contains_receipt(self):
        p = make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PAID)
        n = Notification.objects.get(
            recipient=self.member,
            notification_type=Notification.NotificationType.PAYMENT_RECEIVED,
        )
        self.assertIn(p.receipt_number, n.message)

    def test_idempotent_same_payment_saved_twice_today(self):
        """Re-saving the same PAID payment on the same day must not duplicate the notification."""
        p = make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PAID)
        # Re-save triggers the signal again
        p.notes = 'updated'
        p.save()
        self.assertEqual(self._notification_count(), 1)

    def test_status_change_to_paid_creates_notification(self):
        """Changing status from PENDING → PAID should trigger the notification."""
        p = make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PENDING)
        self.assertEqual(self._notification_count(), 0)
        p.status = Payment.PaymentStatus.PAID
        p.save()
        self.assertEqual(self._notification_count(), 1)


# ─── send_reminders command tests ─────────────────────────────────────────────


class SendRemindersCommandTest(TestCase):
    """
    Tests for the send_reminders management command.
    We call each private helper directly to avoid the overhead of invoking
    the full management framework; handle() integration test covers end-to-end.
    """

    def setUp(self):
        from apps.notifications.management.commands.send_reminders import Command
        self.cmd = Command()
        self.today = date.today()

        self.member = make_user(role=User.Role.MEMBER)
        self.staff = make_user(role=User.Role.STAFF)
        self.trainer = make_user(
            role=User.Role.TRAINER,
            first_name='Trainer',
            last_name='One',
        )
        self.plan = make_membership_plan()

    # ── Membership renewal ──────────────────────────────────────────────────

    def test_sends_renewal_for_expiring_membership(self):
        expiring_soon = self.today + timedelta(days=2)
        make_membership(self.member, self.plan, self.today - timedelta(days=28), expiring_soon)
        count = self.cmd._send_membership_renewal_reminders(self.today)
        self.assertEqual(count, 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.MEMBERSHIP_RENEWAL,
        ).exists())

    def test_no_renewal_when_membership_not_expiring_soon(self):
        far_future = self.today + timedelta(days=30)
        make_membership(self.member, self.plan, self.today, far_future)
        count = self.cmd._send_membership_renewal_reminders(self.today)
        self.assertEqual(count, 0)

    def test_sends_expiry_for_overdue_active_membership(self):
        """Memberships past end_date but still ACTIVE should get MEMBERSHIP_EXPIRY."""
        expired_date = self.today - timedelta(days=1)
        make_membership(self.member, self.plan, self.today - timedelta(days=31), expired_date)
        count = self.cmd._send_membership_renewal_reminders(self.today)
        self.assertGreaterEqual(count, 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.MEMBERSHIP_EXPIRY,
        ).exists())

    def test_renewal_idempotent(self):
        expiring_soon = self.today + timedelta(days=2)
        make_membership(self.member, self.plan, self.today - timedelta(days=28), expiring_soon)
        self.cmd._send_membership_renewal_reminders(self.today)
        count2 = self.cmd._send_membership_renewal_reminders(self.today)
        self.assertEqual(count2, 0)  # already sent today

    # ── Payment due ────────────────────────────────────────────────────────

    def test_sends_payment_due_for_pending_payment(self):
        make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PENDING)
        count = self.cmd._send_payment_due_reminders(self.today)
        self.assertEqual(count, 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.PAYMENT_DUE,
        ).exists())

    def test_sends_payment_due_for_partial_payment(self):
        make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PARTIAL)
        count = self.cmd._send_payment_due_reminders(self.today)
        self.assertEqual(count, 1)

    def test_no_payment_due_for_paid_payment(self):
        make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PAID)
        count = self.cmd._send_payment_due_reminders(self.today)
        self.assertEqual(count, 0)

    def test_payment_due_idempotent(self):
        make_payment(self.member, self.staff, status_=Payment.PaymentStatus.PENDING)
        self.cmd._send_payment_due_reminders(self.today)
        count2 = self.cmd._send_payment_due_reminders(self.today)
        self.assertEqual(count2, 0)

    # ── Inactivity ─────────────────────────────────────────────────────────

    def test_sends_inactivity_for_absent_member(self):
        # Last check-in was 20 days ago
        old_date = self.today - timedelta(days=20)
        Attendance.objects.create(
            user=self.member,
            attendance_type=Attendance.AttendanceType.MEMBER,
            date=old_date,
            status=Attendance.Status.PRESENT,
        )
        count = self.cmd._send_inactivity_alerts(self.today)
        self.assertGreaterEqual(count, 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.INACTIVITY,
        ).exists())

    def test_no_inactivity_for_recent_member(self):
        recent = self.today - timedelta(days=3)
        Attendance.objects.create(
            user=self.member,
            attendance_type=Attendance.AttendanceType.MEMBER,
            date=recent,
            status=Attendance.Status.PRESENT,
        )
        self.assertFalse(Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.INACTIVITY,
        ).exists())
        count = self.cmd._send_inactivity_alerts(self.today)
        self.assertEqual(count, 0)

    def test_no_inactivity_for_member_never_checked_in(self):
        """Members who never visited should not get an inactivity alert."""
        count = self.cmd._send_inactivity_alerts(self.today)
        self.assertFalse(Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.INACTIVITY,
        ).exists())
        self.assertEqual(count, 0)

    def test_inactivity_idempotent(self):
        old_date = self.today - timedelta(days=20)
        Attendance.objects.create(
            user=self.member,
            attendance_type=Attendance.AttendanceType.MEMBER,
            date=old_date,
        )
        self.cmd._send_inactivity_alerts(self.today)
        count2 = self.cmd._send_inactivity_alerts(self.today)
        self.assertEqual(count2, 0)

    # ── Workout reminder ───────────────────────────────────────────────────

    def test_sends_workout_reminder_when_no_recent_log(self):
        make_workout_assignment(self.member, self.trainer)
        count = self.cmd._send_workout_reminders(self.today)
        self.assertEqual(count, 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.WORKOUT_REMINDER,
        ).exists())

    def test_no_workout_reminder_when_logged_recently(self):
        assignment = make_workout_assignment(self.member, self.trainer)
        day = WorkoutDay.objects.create(
            template=assignment.template,
            week_number=1,
            day_number=1,
            day_name='Day 1',
        )
        WorkoutCompletionLog.objects.create(
            assignment=assignment,
            workout_day=day,
            date=self.today - timedelta(days=1),
            status=WorkoutCompletionLog.Status.COMPLETED,
        )
        count = self.cmd._send_workout_reminders(self.today)
        self.assertEqual(count, 0)

    def test_no_workout_reminder_for_member_with_no_plan(self):
        """Member has no WorkoutAssignment — should not receive a reminder."""
        count = self.cmd._send_workout_reminders(self.today)
        self.assertEqual(count, 0)
        self.assertFalse(Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.WORKOUT_REMINDER,
        ).exists())

    def test_no_workout_reminder_for_paused_assignment(self):
        make_workout_assignment(self.member, self.trainer, status_=WorkoutAssignment.Status.PAUSED)
        count = self.cmd._send_workout_reminders(self.today)
        self.assertEqual(count, 0)

    def test_workout_reminder_idempotent(self):
        make_workout_assignment(self.member, self.trainer)
        self.cmd._send_workout_reminders(self.today)
        count2 = self.cmd._send_workout_reminders(self.today)
        self.assertEqual(count2, 0)

    # ── handle() integration ───────────────────────────────────────────────

    def test_handle_outputs_success_message(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('send_reminders', stdout=out)
        self.assertIn('Done.', out.getvalue())


# ─── Notification API view tests ──────────────────────────────────────────────


class NotificationListCreateViewTest(APITestCase):

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.owner = make_user(role=User.Role.OWNER)
        self.other = make_user(role=User.Role.MEMBER)
        self.url = reverse('notification-list-create')

    def _make(self, recipient=None, is_read=False, n_type=Notification.NotificationType.GENERAL):
        return Notification.objects.create(
            recipient=recipient or self.member,
            notification_type=n_type,
            title='Test',
            message='Test message',
            is_read=is_read,
        )

    # ── GET (list) ─────────────────────────────────────────────────────────

    def test_list_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def _results(self, response):
        """Return the list of notification dicts from either paginated or plain response."""
        data = response.data
        return data['results'] if isinstance(data, dict) and 'results' in data else data

    def test_member_sees_only_own_notifications(self):
        self._make(recipient=self.member)
        self._make(recipient=self.other)
        response = self.client.get(self.url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._results(response)
        # All returned notifications must belong to self.member
        ids = {n['recipient'] for n in results}
        self.assertEqual(ids, {self.member.pk})

    def test_filter_by_is_read_false(self):
        self._make(is_read=False)
        self._make(is_read=True)
        response = self.client.get(self.url + '?is_read=false', **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._results(response)
        self.assertTrue(all(not n['is_read'] for n in results))
        self.assertGreaterEqual(len(results), 1)

    def test_filter_by_is_read_true(self):
        self._make(is_read=False)
        self._make(is_read=True)
        response = self.client.get(self.url + '?is_read=true', **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._results(response)
        self.assertTrue(all(n['is_read'] for n in results))
        self.assertGreaterEqual(len(results), 1)

    def test_filter_by_notification_type(self):
        self._make(n_type=Notification.NotificationType.PAYMENT_DUE)
        self._make(n_type=Notification.NotificationType.GENERAL)
        response = self.client.get(
            self.url + '?notification_type=PAYMENT_DUE',
            **auth_header(self.member),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = self._results(response)
        self.assertTrue(all(n['notification_type'] == 'PAYMENT_DUE' for n in results))
        self.assertGreaterEqual(len(results), 1)

    # ── POST (create/push) ─────────────────────────────────────────────────

    def test_member_cannot_push_notification(self):
        payload = {
            'recipients': [self.other.pk],
            'notification_type': 'GENERAL',
            'title': 'Hello',
            'message': 'msg',
        }
        response = self.client.post(self.url, payload, format='json', **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_push_notification_to_multiple_recipients(self):
        payload = {
            'recipients': [self.member.pk, self.other.pk],
            'notification_type': 'ANNOUNCEMENT',
            'title': 'Big news',
            'message': 'Something happened',
        }
        before_count = Notification.objects.filter(notification_type='ANNOUNCEMENT').count()
        response = self.client.post(self.url, payload, format='json', **auth_header(self.owner))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data), 2)
        after_count = Notification.objects.filter(notification_type='ANNOUNCEMENT').count()
        self.assertEqual(after_count - before_count, 2)


class UnreadCountViewTest(APITestCase):

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.url = reverse('notification-unread-count')

    def test_returns_zero_when_no_notifications(self):
        response = self.client.get(self.url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['unread_count'], 0)

    def test_counts_only_unread(self):
        Notification.objects.create(
            recipient=self.member, notification_type='GENERAL',
            title='A', message='msg', is_read=False,
        )
        Notification.objects.create(
            recipient=self.member, notification_type='GENERAL',
            title='B', message='msg', is_read=True,
        )
        response = self.client.get(self.url, **auth_header(self.member))
        self.assertEqual(response.data['unread_count'], 1)

    def test_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class MarkAsReadViewTest(APITestCase):

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.notification = Notification.objects.create(
            recipient=self.member, notification_type='GENERAL',
            title='Test', message='msg', is_read=False,
        )
        self.url = reverse('notification-mark-read', args=[self.notification.pk])

    def test_mark_read(self):
        response = self.client.patch(self.url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)

    def test_cannot_mark_read_for_another_user(self):
        other = make_user(role=User.Role.MEMBER)
        response = self.client.patch(self.url, **auth_header(other))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_404_for_nonexistent(self):
        url = reverse('notification-mark-read', args=[99999])
        response = self.client.patch(url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class MarkAllAsReadViewTest(APITestCase):

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.url = reverse('notification-mark-all-read')
        for i in range(3):
            Notification.objects.create(
                recipient=self.member, notification_type='GENERAL',
                title=f'Notif {i}', message='msg',
            )

    def test_marks_all_unread_as_read(self):
        response = self.client.post(self.url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('3', response.data['detail'])
        self.assertEqual(
            Notification.objects.filter(recipient=self.member, is_read=False).count(), 0
        )

    def test_does_not_affect_other_users_notifications(self):
        other = make_user(role=User.Role.MEMBER)
        Notification.objects.create(
            recipient=other, notification_type='GENERAL', title='Other', message='msg'
        )
        self.client.post(self.url, **auth_header(self.member))
        self.assertEqual(
            Notification.objects.filter(recipient=other, is_read=False).count(), 1
        )

    def test_requires_auth(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class NotificationDeleteViewTest(APITestCase):

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.owner = make_user(role=User.Role.OWNER)
        self.other = make_user(role=User.Role.MEMBER)
        self.notification = Notification.objects.create(
            recipient=self.member, notification_type='GENERAL',
            title='Delete me', message='msg',
        )
        self.url = reverse('notification-delete', args=[self.notification.pk])

    def test_recipient_can_delete_own_notification(self):
        response = self.client.delete(self.url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Notification.objects.filter(pk=self.notification.pk).exists())

    def test_owner_can_delete_any_notification(self):
        response = self.client.delete(self.url, **auth_header(self.owner))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_other_member_cannot_delete(self):
        response = self.client.delete(self.url, **auth_header(self.other))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_returns_404_for_nonexistent(self):
        url = reverse('notification-delete', args=[99999])
        response = self.client.delete(url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_auth(self):
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
