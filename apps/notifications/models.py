"""
Notification model for in-system alerts to users.
Types: membership renewal, payment due, inactivity, general announcements.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
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


class MessageGroup(models.Model):
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


class GroupMessage(models.Model):
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


class PinnedConversation(models.Model):
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
                fields=['user', 'kind', 'target_id'],
                name='unique_pinned_conversation',
            )
        ]

    def __str__(self):
        return f'{self.user} pinned {self.kind}:{self.target_id}'
