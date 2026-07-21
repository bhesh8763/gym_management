"""
Serializers for the Notifications app.
"""
from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    recipient_name = serializers.CharField(source='recipient.get_full_name', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'recipient', 'recipient_name', 'notification_type', 'title',
            'message', 'is_read', 'read_at', 'related_membership_id',
            'related_payment_id', 'created_at',
        ]
        read_only_fields = ['id', 'recipient_name', 'read_at', 'created_at']


class NotificationCreateSerializer(serializers.ModelSerializer):
    """Used by Owner/Staff to manually push a notification/announcement to one
    or more recipients."""

    recipients = serializers.PrimaryKeyRelatedField(
        queryset=Notification._meta.get_field('recipient').related_model.objects.all(),
        many=True,
        write_only=True,
        help_text='List of user IDs to notify. Use this instead of "recipient" to send to many at once.',
    )

    class Meta:
        model = Notification
        fields = [
            'recipients', 'notification_type', 'title', 'message',
            'related_membership_id', 'related_payment_id',
        ]

    def create(self, validated_data):
        recipients = validated_data.pop('recipients')
        notifications = [
            Notification(recipient=user, **validated_data) for user in recipients
        ]
        return Notification.objects.bulk_create(notifications)
