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
            'id', 'gym', 'branch', 'recipient', 'recipient_name', 'notification_type', 'title',
            'message', 'is_read', 'read_at', 'related_membership_id',
            'related_payment_id', 'created_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'recipient_name', 'read_at', 'created_at']


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

    def validate(self, attrs):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        recipients = attrs.get('recipients', [])
        if gym is not None:
            from apps.gyms.models import GymMembership
            allowed = set(GymMembership.objects.filter(
                gym=gym,
                user__in=recipients,
                status=GymMembership.Status.ACTIVE,
            ).values_list('user_id', flat=True))
            invalid = [user.id for user in recipients if user.id not in allowed]
            if invalid:
                raise serializers.ValidationError({'recipients': 'All recipients must belong to this gym.'})
        return attrs

    def create(self, validated_data):
        recipients = validated_data.pop('recipients')
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        branch = getattr(request, 'branch', None) if request else None
        notifications = [
            Notification(
                gym=gym,
                branch=branch,
                recipient=user,
                **validated_data,
            )
            for user in recipients
        ]
        return Notification.objects.bulk_create(notifications)
