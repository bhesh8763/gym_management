"""
Serializers for the Notifications app.
"""
from rest_framework import serializers

from apps.notifications.models import Notification, PushSubscription, schedule_push_on_commit


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
        created = Notification.objects.bulk_create(notifications)
        # bulk_create() bypasses Model.save(), so the push-parity hook would
        # never fire — announcements would reach the bell but not the device.
        # Schedule each row explicitly: same event, same once-only guarantee.
        for notification in created:
            schedule_push_on_commit(notification)
        return created


class PushSubscriptionSerializer(serializers.ModelSerializer):
    """Payload the browser sends from pushManager.subscribe()."""

    # Uniqueness is the view's job (subscribe upserts by endpoint), so the
    # ModelSerializer's default UniqueValidator must not reject re-subscribes.
    endpoint = serializers.URLField(max_length=500, validators=[])

    class Meta:
        model = PushSubscription
        fields = ['endpoint', 'p256dh', 'auth', 'user_agent']

    def validate_endpoint(self, value):
        # Push service endpoints are always https (or http on localhost dev).
        if not value.startswith(('https://', 'http://127.0.0.1', 'http://localhost')):
            raise serializers.ValidationError('Endpoint must be an https:// URL.')
        if len(value) > 500:
            raise serializers.ValidationError('Endpoint is too long.')
        return value
