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
