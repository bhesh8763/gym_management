"""
Notification model for in-system alerts to users.
Types: membership renewal, payment due, inactivity, general announcements.
"""
import logging

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.gyms.models import TenantScopedModel

logger = logging.getLogger(__name__)


class Notification(TenantScopedModel):
    """
    System-generated or manually triggered notification for a user.
    """

    class NotificationType(models.TextChoices):
        MEMBERSHIP_EXPIRY = 'MEMBERSHIP_EXPIRY', 'Membership Expiry'
        MEMBERSHIP_RENEWAL = 'MEMBERSHIP_RENEWAL', 'Membership Renewal'
        PAYMENT_DUE = 'PAYMENT_DUE', 'Payment Due'
        PAYMENT_RECEIVED = 'PAYMENT_RECEIVED', 'Payment Received'
        INACTIVITY = 'INACTIVITY', 'Inactivity Alert'
        WORKOUT_REMINDER = 'WORKOUT_REMINDER', 'Workout Reminder'
        GENERAL = 'GENERAL', 'General'
        ANNOUNCEMENT = 'ANNOUNCEMENT', 'Announcement'
        MEMBER_MESSAGE = 'MEMBER_MESSAGE', 'Member Message'
        TRAINER_REPLY = 'TRAINER_REPLY', 'Trainer Reply'
        TRAINER_ASSIGNED = 'TRAINER_ASSIGNED', 'Trainer Assigned'

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_notifications',
        help_text='User who caused this notification (member, trainer, staff, owner).',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(
        max_length=25, choices=NotificationType.choices, db_index=True
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_edited = models.BooleanField(default=False)

    # Optional links to related objects
    related_membership_id = models.PositiveIntegerField(null=True, blank=True)
    related_payment_id = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.recipient.get_full_name()} — {self.title}'

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def save(self, *args, **kwargs):
        """Persist the row and, when it's new, schedule its Web Push twin.

        The in-app row and the system notification are ONE event, so the
        dispatch lives here instead of at each call site. Several flows create
        notifications directly (payments, trainer assignment, freeze reviews,
        the reminder cron) and used to skip push entirely — the user would see
        the bell badge but never an OS-level notification.

        Deferred with transaction.on_commit so a rolled-back row never wakes a
        device, and wrapped so a push failure can never break the save that
        already happened. ``services`` is imported lazily: it imports this
        module, and updates (read flags, edits) must not re-push.
        """
        is_new = self._state.adding
        # Resolve the FK only for inserts (updates — read flags, edits — never
        # re-push); the instance is usually already cached by the caller's
        # create(), so this rarely costs a query.
        recipient = self.recipient if (is_new and self.recipient_id) else None
        super().save(*args, **kwargs)
        if recipient is None:
            return

        from django.db import transaction

        from apps.notifications import services

        def _push_after_commit():
            try:
                services.send_push(
                    recipient,
                    self.title,
                    self.message,
                    self.notification_type,
                    self.pk,
                )
            except Exception as exc:  # noqa: BLE001 — push must never break the caller
                logger.warning(
                    f'Web Push dispatch for notification {self.pk} failed: {exc}',
                )

        transaction.on_commit(_push_after_commit)


class PushSubscription(models.Model):
    """
    Browser push subscription for Web Push delivery to an installed PWA.

    One row per browser endpoint (a user may have several: phone, desktop).
    Deliberately NOT tenant-scoped: the endpoint belongs to the device, so a
    user switching gyms keeps the same subscription, and the next login on
    that browser reassigns the row to whoever logged in.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_subscriptions',
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=128)   # per-subscription public key
    auth = models.CharField(max_length=64)      # per-subscription auth secret
    user_agent = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'push_subscriptions'
        ordering = ['-created_at']

    def __str__(self):
        return f'PushSubscription({self.user_id}): {self.endpoint[:48]}…'


class MessageGroup(TenantScopedModel):
    """
    A shared group chat thread. Members see the same messages.
    Created by trainers, staff, or the owner; members only participate.
    """

    name = models.CharField(max_length=150)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='message_groups_created',
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='message_groups',
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'message_groups'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.members.count()} members)'


class GroupMessage(TenantScopedModel):
    """A single message inside a shared group chat thread."""

    group = models.ForeignKey(
        MessageGroup, on_delete=models.CASCADE, related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='group_messages_sent',
    )
    message = models.TextField()
    is_edited = models.BooleanField(default=False)
    read_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='group_messages_read',
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'group_messages'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.sender.get_full_name()}: {self.message[:40]}'


class PinnedConversation(TenantScopedModel):
    """A chat a user has pinned to the top of their conversation list."""

    class Kind(models.TextChoices):
        DIRECT = 'direct', 'Direct'
        GROUP = 'group', 'Group'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pinned_conversations',
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    target_id = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pinned_conversations'
        constraints = [
            models.UniqueConstraint(
                fields=['gym', 'branch', 'user', 'kind', 'target_id'],
                name='unique_pinned_conversation',
            )
        ]

    def __str__(self):
        return f'{self.user} pinned {self.kind}:{self.target_id}'
