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
import json
import threading
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.attendance.models import Attendance
from apps.memberships.models import Membership, MembershipPlan
from apps.notifications.models import Notification, PushSubscription
from apps.notifications.routing import websocket_urlpatterns
from apps.notifications.services import broadcast_to_user, notify, send_push
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

    @override_settings(
        VAPID_PUBLIC_KEY='PUBKEY',
        VAPID_PRIVATE_KEY='PRIVKEY',
        VAPID_SUBJECT='mailto:test@example.com',
    )
    def test_owner_push_schedules_webpush_for_each_recipient(self):
        """bulk_create bypasses save() — POST must schedule the push itself.

        Regression: announcements created here reached the bell but never the
        device (messages pushed, Notifications-page sends did not).
        """
        PushSubscription.objects.create(
            user=self.member,
            endpoint='https://push.example.com/ep-member',
            p256dh='B' + 'a' * 110,
            auth='b' * 50,
        )
        PushSubscription.objects.create(
            user=self.other,
            endpoint='https://push.example.com/ep-other',
            p256dh='B' + 'c' * 110,
            auth='d' * 50,
        )
        payload = {
            'recipients': [self.member.pk, self.other.pk],
            'notification_type': 'ANNOUNCEMENT',
            'title': 'Big news',
            'message': 'Something happened',
        }
        with mock.patch('pywebpush.webpush') as webpush_mock, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, payload, format='json', **auth_header(self.owner))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(webpush_mock.call_count, 2)
        endpoints = {
            call.kwargs['subscription_info']['endpoint']
            for call in webpush_mock.call_args_list
        }
        self.assertEqual(
            endpoints,
            {'https://push.example.com/ep-member', 'https://push.example.com/ep-other'},
        )


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


class NotificationDetailViewTest(APITestCase):
    """GET /api/notifications/<id>/ — backs the notification detail page."""

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.other = make_user(role=User.Role.MEMBER)
        self.notification = Notification.objects.create(
            recipient=self.member, notification_type='PAYMENT_DUE',
            title='Payment due', message='Full detail body', is_read=False,
        )
        self.url = reverse('notification-delete', args=[self.notification.pk])

    def test_recipient_gets_own_notification(self):
        response = self.client.get(self.url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.notification.pk)
        self.assertEqual(response.data['title'], 'Payment due')
        self.assertEqual(response.data['message'], 'Full detail body')
        self.assertFalse(response.data['is_read'])

    def test_another_users_row_is_404_not_403(self):
        """No existence leak: other recipients see plain not-found."""
        response = self.client.get(self.url, **auth_header(self.other))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_nonexistent_returns_404(self):
        url = reverse('notification-delete', args=[99999])
        response = self.client.get(url, **auth_header(self.member))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class NotificationSenderFieldTest(APITestCase):
    """Verify the new ``sender`` FK on Notification is used by the messaging API
    and that legacy inbox serialization no longer parses the title."""

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.trainer = make_user(role=User.Role.TRAINER)
        self.assignment = make_workout_assignment(self.member, self.trainer)
        self.reply_url = reverse('trainer-reply')
        self.direct_url = reverse('message-direct')

    def test_trainer_reply_notification_has_sender(self):
        """Trainer replies should set sender=trainer explicitly."""
        self.client.credentials(**auth_header(self.trainer))
        r = self.client.post(self.reply_url, {
            'member_id': self.member.pk,
            'message': 'Good form today',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

        reply = Notification.objects.filter(
            recipient=self.member,
            notification_type=Notification.NotificationType.TRAINER_REPLY,
        ).latest('created_at')
        self.assertEqual(reply.sender, self.trainer)
        self.assertIsNotNone(reply.sender_id)

    def test_member_message_notification_has_sender(self):
        """Member messages should set sender=member explicitly."""
        self.client.credentials(**auth_header(self.member))
        r = self.client.post(self.direct_url, {
            'recipient_id': self.trainer.pk,
            'message': 'Ready for tomorrow',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

        msg = Notification.objects.filter(
            recipient=self.trainer,
            notification_type=Notification.NotificationType.MEMBER_MESSAGE,
        ).latest('created_at')
        self.assertEqual(msg.sender, self.member)

    def test_inbox_serializer_reads_sender_from_fk(self):
        """The inbox serialization should use the sender FK, not the legacy
        "Message from X" title prefix."""
        from apps.workouts.views import _serialize_notification

        n = Notification.objects.create(
            sender=self.trainer,
            recipient=self.member,
            notification_type=Notification.NotificationType.TRAINER_REPLY,
            title='Trainer reply',
            message='Some feedback',
            related_membership_id=self.trainer.pk,
        )

        serialized = _serialize_notification(n)
        self.assertEqual(serialized['sender_name'], self.trainer.get_full_name())
        self.assertEqual(serialized['sender_id'], self.trainer.pk)
        # The old parsed-name convention would have put the title itself here.
        self.assertNotEqual(serialized['sender_name'], 'Trainer reply')


# ─── Web Push tests ───────────────────────────────────────────────────────────


class PushSubscriptionAPITest(APITestCase):
    """GET /push/public-key/ · POST /push/subscribe/ · POST /push/unsubscribe/."""

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.other = make_user(role=User.Role.MEMBER)
        self.key_url = reverse('notification-push-key')
        self.sub_url = reverse('notification-push-subscribe')
        self.unsub_url = reverse('notification-push-unsubscribe')
        self.body = {
            'endpoint': 'https://push.example.com/sub-abc',
            'p256dh': 'B' + 'a' * 110,
            'auth': 'b' * 50,
            'user_agent': 'Mozilla/5.0 (test)',
        }

    def test_public_key_requires_auth(self):
        r = self.client.get(self.key_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_public_key_returns_key_and_enabled_flag(self):
        with self.settings(VAPID_PUBLIC_KEY='PUBKEY', VAPID_PRIVATE_KEY='PRIVKEY'):
            self.client.credentials(**auth_header(self.member))
            r = self.client.get(self.key_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.json(), {'key': 'PUBKEY', 'enabled': True})

    def test_public_key_reports_disabled_when_unconfigured(self):
        with self.settings(VAPID_PUBLIC_KEY='', VAPID_PRIVATE_KEY=''):
            self.client.credentials(**auth_header(self.member))
            r = self.client.get(self.key_url)
        self.assertEqual(r.json()['enabled'], False)

    def test_subscribe_requires_auth(self):
        r = self.client.post(self.sub_url, self.body, format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_subscribe_creates_row_for_logged_in_user(self):
        self.client.credentials(**auth_header(self.member))
        r = self.client.post(self.sub_url, self.body, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        sub = PushSubscription.objects.get(endpoint=self.body['endpoint'])
        self.assertEqual(sub.user, self.member)
        self.assertEqual(sub.p256dh, self.body['p256dh'])
        self.assertEqual(sub.auth, self.body['auth'])

    def test_subscribe_twice_keeps_single_row(self):
        self.client.credentials(**auth_header(self.member))
        first = self.client.post(self.sub_url, self.body, format='json')
        second = self.client.post(self.sub_url, self.body, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(
            PushSubscription.objects.filter(endpoint=self.body['endpoint']).count(), 1,
        )

    def test_subscribe_reassigns_endpoint_to_new_user(self):
        """Same browser, different user logs in — the row follows the user."""
        self.client.credentials(**auth_header(self.member))
        self.client.post(self.sub_url, self.body, format='json')
        self.client.credentials(**auth_header(self.other))
        r = self.client.post(self.sub_url, self.body, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(
            PushSubscription.objects.get(endpoint=self.body['endpoint']).user, self.other,
        )

    def test_subscribe_rejects_non_http_endpoint(self):
        self.client.credentials(**auth_header(self.member))
        bad = {**self.body, 'endpoint': 'javascript:alert(1)'}
        r = self.client.post(self.sub_url, bad, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unsubscribe_removes_own_row(self):
        self.client.credentials(**auth_header(self.member))
        self.client.post(self.sub_url, self.body, format='json')
        r = self.client.post(self.unsub_url, {'endpoint': self.body['endpoint']}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.json()['deleted'], 1)
        self.assertFalse(PushSubscription.objects.exists())

    def test_unsubscribe_does_not_touch_other_users_rows(self):
        other_sub = PushSubscription.objects.create(
            user=self.other,
            endpoint='https://push.example.com/other',
            p256dh='B' + 'c' * 110,
            auth='d' * 50,
        )
        self.client.credentials(**auth_header(self.member))
        r = self.client.post(self.unsub_url, {'endpoint': other_sub.endpoint}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.json()['deleted'], 0)
        self.assertTrue(PushSubscription.objects.filter(pk=other_sub.pk).exists())


@override_settings(
    VAPID_PUBLIC_KEY='PUBKEY',
    VAPID_PRIVATE_KEY='PRIVKEY',
    VAPID_SUBJECT='mailto:test@example.com',
)
class SendPushTest(TestCase):
    """services.send_push() — delivery, dead-subscription cleanup, config gating."""

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.sub = PushSubscription.objects.create(
            user=self.member,
            endpoint='https://push.example.com/ep-1',
            p256dh='B' + 'a' * 110,
            auth='b' * 50,
        )

    def test_delivers_to_each_subscription_with_payload(self):
        with mock.patch('pywebpush.webpush') as webpush_mock:
            delivered = send_push(self.member, 'Hello', 'World message', 'PAYMENT_DUE')
        self.assertEqual(delivered, 1)
        webpush_mock.assert_called_once()
        kwargs = webpush_mock.call_args.kwargs
        payload = json.loads(kwargs['data'])
        self.assertEqual(payload['title'], 'Hello')
        self.assertEqual(payload['body'], 'World message')
        self.assertTrue(payload['url'].endswith('/my-payments.html'))  # deep link
        self.assertEqual(kwargs['subscription_info']['endpoint'], self.sub.endpoint)
        self.assertEqual(kwargs['vapid_claims'], {'sub': 'mailto:test@example.com'})

    def test_payload_deep_links_to_the_detail_page_when_id_given(self):
        """With a notification id the tap opens THAT notification's page."""
        with mock.patch('pywebpush.webpush') as webpush_mock:
            send_push(self.member, 'Hello', 'World', 'PAYMENT_DUE', notification_id=42)
        payload = json.loads(webpush_mock.call_args.kwargs['data'])
        self.assertTrue(
            payload['url'].endswith('/notification-detail.html?id=42'),
            payload['url'],
        )

    def test_no_subscriptions_means_no_network_call(self):
        PushSubscription.objects.all().delete()
        with mock.patch('pywebpush.webpush') as webpush_mock:
            delivered = send_push(self.member, 'Hi', 'Body')
        self.assertEqual(delivered, 0)
        webpush_mock.assert_not_called()

    @override_settings(VAPID_PUBLIC_KEY='', VAPID_PRIVATE_KEY='')
    def test_skips_entirely_when_vapid_unconfigured(self):
        with mock.patch('pywebpush.webpush') as webpush_mock:
            delivered = send_push(self.member, 'Hi', 'Body')
        self.assertEqual(delivered, 0)
        webpush_mock.assert_not_called()

    def test_removes_subscription_when_push_service_says_gone(self):
        """HTTP 410 Gone → the subscription is dead and must be deleted."""
        from pywebpush import WebPushException

        response = mock.Mock(status_code=410)
        with mock.patch(
            'pywebpush.webpush',
            side_effect=WebPushException('gone', response=response),
        ):
            delivered = send_push(self.member, 'Hi', 'Body')
        self.assertEqual(delivered, 0)
        self.assertFalse(PushSubscription.objects.filter(pk=self.sub.pk).exists())

    def test_keeps_subscription_on_transient_errors(self):
        with mock.patch('pywebpush.webpush', side_effect=RuntimeError('boom')):
            delivered = send_push(self.member, 'Hi', 'Body')
        self.assertEqual(delivered, 0)
        self.assertTrue(PushSubscription.objects.filter(pk=self.sub.pk).exists())

    def test_never_raises_to_the_caller(self):
        """send_push is best-effort — notify() must never break because of it."""
        with mock.patch('pywebpush.webpush', side_effect=RuntimeError('boom')):
            send_push(self.member, 'Hi', 'Body')  # must not raise


class NotifyPushHookTest(TestCase):
    """notify() must schedule a Web Push for the recipient after commit."""

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        # The recipient must actually have a device subscribed.
        self.sub = PushSubscription.objects.create(
            user=self.member,
            endpoint='https://push.example.com/ep-hook',
            p256dh='B' + 'a' * 110,
            auth='b' * 50,
        )

    @override_settings(
        VAPID_PUBLIC_KEY='PUBKEY',
        VAPID_PRIVATE_KEY='PRIVKEY',
        VAPID_SUBJECT='mailto:test@example.com',
    )
    def test_notify_dispatches_push_on_commit(self):
        with mock.patch('pywebpush.webpush') as webpush_mock, \
                self.captureOnCommitCallbacks(execute=True):
            notification = notify(
                self.member,
                Notification.NotificationType.GENERAL,
                'Title here',
                'Body here',
                send_email=False,
            )
        self.assertIsNotNone(notification.pk)
        webpush_mock.assert_called_once()
        payload = json.loads(webpush_mock.call_args.kwargs['data'])
        self.assertEqual(payload['title'], 'Title here')

    @override_settings(
        VAPID_PUBLIC_KEY='PUBKEY',
        VAPID_PRIVATE_KEY='PRIVKEY',
        VAPID_SUBJECT='mailto:test@example.com',
    )
    def test_notify_push_url_targets_that_notifications_detail_page(self):
        """The pushed deep link goes straight to the new notification's detail page."""
        with mock.patch('pywebpush.webpush') as webpush_mock, \
                self.captureOnCommitCallbacks(execute=True):
            notification = notify(
                self.member,
                Notification.NotificationType.GENERAL,
                'T',
                'B',
                send_email=False,
            )
        payload = json.loads(webpush_mock.call_args.kwargs['data'])
        self.assertIn(f'notification-detail.html?id={notification.pk}', payload['url'])

    @override_settings(VAPID_PUBLIC_KEY='', VAPID_PRIVATE_KEY='')
    def test_notify_without_vapid_configured_is_safe(self):
        with mock.patch('pywebpush.webpush') as webpush_mock, \
                self.captureOnCommitCallbacks(execute=True):
            notify(
                self.member,
                Notification.NotificationType.GENERAL,
                'Title',
                'Body',
                send_email=False,
            )
        self.assertEqual(Notification.objects.filter(recipient=self.member).count(), 1)
        webpush_mock.assert_not_called()


class NotificationSavePushHookTest(TestCase):
    """Notification.save() — the model-level parity hook.

    Every NEW in-app row schedules exactly one Web Push after commit, so
    flows that create notifications directly (payments, trainer assignment,
    freeze reviews, the reminder cron) reach the device as a system
    notification too; updates must never re-push.
    """

    def setUp(self):
        self.member = make_user(role=User.Role.MEMBER)
        self.sub = PushSubscription.objects.create(
            user=self.member,
            endpoint='https://push.example.com/ep-save',
            p256dh='B' + 'a' * 110,
            auth='b' * 50,
        )

    @override_settings(
        VAPID_PUBLIC_KEY='PUBKEY',
        VAPID_PRIVATE_KEY='PRIVKEY',
        VAPID_SUBJECT='mailto:test@example.com',
    )
    def test_direct_create_schedules_push_after_commit(self):
        """A bare Notification.objects.create() — no notify() wrapper — pushes."""
        with mock.patch('pywebpush.webpush') as webpush_mock, \
                self.captureOnCommitCallbacks(execute=True):
            notification = Notification.objects.create(
                recipient=self.member,
                notification_type=Notification.NotificationType.PAYMENT_RECEIVED,
                title='Payment received',
                message='NPR 1,500 received.',
            )
        self.assertIsNotNone(notification.pk)
        webpush_mock.assert_called_once()
        kwargs = webpush_mock.call_args.kwargs
        payload = json.loads(kwargs['data'])
        self.assertEqual(payload['title'], 'Payment received')
        self.assertIn(f'notification-detail.html?id={notification.pk}', payload['url'])
        self.assertEqual(kwargs['subscription_info']['endpoint'], self.sub.endpoint)

    @override_settings(
        VAPID_PUBLIC_KEY='PUBKEY',
        VAPID_PRIVATE_KEY='PRIVKEY',
        VAPID_SUBJECT='mailto:test@example.com',
    )
    def test_saving_an_existing_row_does_not_push_again(self):
        with mock.patch('pywebpush.webpush') as webpush_mock, \
                self.captureOnCommitCallbacks(execute=True):
            notification = Notification.objects.create(
                recipient=self.member,
                notification_type=Notification.NotificationType.GENERAL,
                title='T',
                message='B',
            )
        self.assertEqual(webpush_mock.call_count, 1)

        with mock.patch('pywebpush.webpush') as update_mock, \
                self.captureOnCommitCallbacks(execute=True):
            notification.mark_read()
        update_mock.assert_not_called()

    @override_settings(VAPID_PUBLIC_KEY='', VAPID_PRIVATE_KEY='')
    def test_unconfigured_server_creates_the_row_without_pushing(self):
        with mock.patch('pywebpush.webpush') as webpush_mock, \
                self.captureOnCommitCallbacks(execute=True):
            notification = Notification.objects.create(
                recipient=self.member,
                notification_type=Notification.NotificationType.GENERAL,
                title='T',
                message='B',
            )
        self.assertIsNotNone(notification.pk)
        webpush_mock.assert_not_called()


class MessageConsumerTests(TransactionTestCase):
    """WebSocket /ws/messages/: token handshake, keepalive, live fan-out.

    The connection carries server -> client events only; every open tab of
    the same user joins the same ws_user_<id> channel-layer group.

    TransactionTestCase is required here (not TestCase): the consumer's
    database_sync_to_async runs close_old_connections() around its token
    lookup, which would close a TestCase's wrapped connection out from
    under the test. Committed rows are also visible to the worker thread
    that validates the token, regardless of thread-affinity.

    serialized_rollback restores migration-seeded rows after each flush so
    the rest of the suite sees the same database state as before.
    """

    serialized_rollback = True

    def _communicator(self, token=None, origin=None):
        headers = [(b'origin', origin.encode())] if origin else []
        path = '/ws/messages/' + (f'?token={token}' if token else '')
        return WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), path, headers=headers,
        )

    def test_connect_with_valid_token_is_accepted_and_greets(self):
        user = make_user(role=User.Role.MEMBER)

        async def scenario():
            communicator = self._communicator(str(AccessToken.for_user(user)))
            accepted, _ = await communicator.connect()
            self.assertTrue(accepted)
            hello = await communicator.receive_json_from()
            self.assertEqual(hello, {'type': 'connected', 'user_id': user.pk})
            await communicator.disconnect()

        async_to_sync(scenario)()

    def test_connect_refused_without_token_or_with_garbage_token(self):
        async def scenario():
            for token in (None, 'not-a-jwt'):
                communicator = self._communicator(token)
                accepted, close_code = await communicator.connect()
                self.assertFalse(accepted)
                self.assertEqual(close_code, 4401)

        async_to_sync(scenario)()

    def test_connect_refused_with_expired_token(self):
        user = make_user(role=User.Role.MEMBER)
        token = AccessToken.for_user(user)
        token.set_exp(lifetime=timedelta(hours=-1))

        async def scenario():
            communicator = self._communicator(str(token))
            accepted, close_code = await communicator.connect()
            self.assertFalse(accepted)
            self.assertEqual(close_code, 4401)

        async_to_sync(scenario)()

    def test_broadcast_reaches_every_open_tab_of_that_user_only(self):
        user = make_user(role=User.Role.MEMBER)
        other = make_user(role=User.Role.MEMBER)
        payload = {
            'type': 'message.new',
            'kind': 'direct',
            'notification_id': 7,
            'preview': 'Live hello',
        }

        async def scenario():
            first = self._communicator(str(AccessToken.for_user(user)))
            second = self._communicator(str(AccessToken.for_user(user)))
            stranger = self._communicator(str(AccessToken.for_user(other)))
            for communicator in (first, second, stranger):
                accepted, _ = await communicator.connect()
                self.assertTrue(accepted)
                await communicator.receive_json_from()  # 'connected' hello

            # Same shape services.broadcast_to_user() emits for ws_user_<id>.
            await get_channel_layer().group_send(
                f'ws_user_{user.pk}',
                {'type': 'message.new', 'payload': payload},
            )
            for communicator in (first, second):
                received = await communicator.receive_json_from(timeout=2)
                self.assertEqual(received, payload)
            # The other user's socket stays quiet: only a ping gets an answer.
            await stranger.send_json_to({'type': 'ping'})
            self.assertEqual(
                await stranger.receive_json_from(timeout=2), {'type': 'pong'},
            )

            for communicator in (first, second, stranger):
                await communicator.disconnect()

        async_to_sync(scenario)()

    def test_broadcast_to_user_helper_reaches_connected_client(self):
        """End-to-end: services.broadcast_to_user -> consumer -> browser.

        The helper runs on its own thread with its own temporary event loop —
        the same shape as a sync request thread hitting the real server while
        the consumer lives on the server's loop.
        """
        user = make_user(role=User.Role.MEMBER)
        joined = threading.Event()
        payload = {
            'type': 'message.new', 'kind': 'group', 'group_id': 3,
            'preview': 'From the helper',
        }

        def broadcast_when_joined():
            if not joined.wait(timeout=10):
                raise AssertionError('consumer never joined ws_user_<id>')
            broadcast_to_user(user.pk, payload)

        broadcaster = threading.Thread(target=broadcast_when_joined)
        broadcaster.start()
        try:
            async def scenario():
                communicator = self._communicator(str(AccessToken.for_user(user)))
                accepted, _ = await communicator.connect()
                self.assertTrue(accepted)
                await communicator.receive_json_from()  # 'connected' hello
                joined.set()  # group_add already happened before the greeting
                received = await communicator.receive_json_from(timeout=3)
                await communicator.disconnect()
                return received

            received = async_to_sync(scenario)()
        finally:
            broadcaster.join(timeout=10)

        self.assertEqual(received, payload)
        # The consumer unregistered its loop on disconnect: no leak.
        from apps.notifications.consumers import loops_for_user
        self.assertEqual(loops_for_user(user.pk), [])

    def test_foreign_origin_is_rejected_by_asgi_router(self):
        """AllowedHostsOriginValidator (cross-site WebSocket hijacking)."""
        from channels.security.websocket import AllowedHostsOriginValidator
        from apps.notifications.routing import websocket_urlpatterns as routes

        user = make_user(role=User.Role.MEMBER)
        token = str(AccessToken.for_user(user))
        app = AllowedHostsOriginValidator(URLRouter(routes))

        async def scenario():
            evil = WebsocketCommunicator(
                app, f'/ws/messages/?token={token}',
                headers=[(b'origin', b'http://evil.example')],
            )
            accepted, _ = await evil.connect()
            self.assertFalse(accepted)

            good = WebsocketCommunicator(
                app, f'/ws/messages/?token={token}',
                headers=[(b'origin', b'http://localhost')],
            )
            accepted, _ = await good.connect()
            self.assertTrue(accepted)
            await good.disconnect()

        async_to_sync(scenario)()
