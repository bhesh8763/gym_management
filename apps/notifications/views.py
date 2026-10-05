"""
Views for the Notifications app.

API Endpoints:
    GET    /api/notifications/                - List my notifications (any authenticated user)
    POST   /api/notifications/                 - Push a notification to one or more users (Owner/Staff)
    GET    /api/notifications/unread-count/    - Count of unread notifications for me
    PATCH  /api/notifications/<id>/read/       - Mark one notification as read
    POST   /api/notifications/mark-all-read/   - Mark all my notifications as read
    DELETE /api/notifications/<id>/            - Delete a notification (Owner/Staff, or the recipient)
    POST   /api/notifications/push/test/       - Send a test Web Push to my own devices

Search/Filter (query params on list):
    ?is_read=<true|false>
    ?notification_type=<MEMBERSHIP_EXPIRY|PAYMENT_DUE|...>
"""
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings

from apps.accounts.models import User
from apps.accounts.permissions import IsOwnerOrStaff
from apps.gyms.tenancy import tenant_queryset
from apps.notifications.models import Notification, PushSubscription
from apps.notifications.serializers import NotificationCreateSerializer, NotificationSerializer, PushSubscriptionSerializer


# ─── List (mine) + Create (push to others) ────────────────────────────────────

class NotificationListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/notifications/  — list the current user's own notifications
    POST /api/notifications/  — Owner/Staff pushes a notification to one or more recipients
    """
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaff()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return NotificationCreateSerializer
        return NotificationSerializer

    def get_queryset(self):
        qs = tenant_queryset(
            Notification.objects.filter(recipient=self.request.user),
            self.request,
        )

        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            qs = qs.filter(is_read=is_read.lower() in ('true', '1', 'yes'))

        notification_type = self.request.query_params.get('notification_type')
        if notification_type:
            qs = qs.filter(notification_type=notification_type)

        return qs

    def create(self, request, *args, **kwargs):
        serializer = NotificationCreateSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        created = serializer.save()
        return Response(
            NotificationSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )


# ─── Unread count ──────────────────────────────────────────────────────────────

class UnreadCountView(APIView):
    """GET /api/notifications/unread-count/ — badge count for the bell icon."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = tenant_queryset(
            Notification.objects.filter(recipient=request.user, is_read=False),
            request,
        ).count()
        return Response({'unread_count': count})


# ─── Mark single as read ───────────────────────────────────────────────────────

class MarkAsReadView(APIView):
    """PATCH /api/notifications/<id>/read/ — mark one notification as read."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        notification = tenant_queryset(
            Notification.objects.filter(pk=pk, recipient=request.user),
            request,
        ).first()
        if notification is None:
            raise NotFound('Notification not found.')
        notification.mark_read()
        return Response(NotificationSerializer(notification).data)


# ─── Mark all as read ───────────────────────────────────────────────────────────

class MarkAllAsReadView(APIView):
    """POST /api/notifications/mark-all-read/ — mark every unread notification as read."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        updated = tenant_queryset(
            Notification.objects.filter(recipient=request.user, is_read=False),
            request,
        ).update(is_read=True, read_at=timezone.now())
        return Response({'detail': f'{updated} notification(s) marked as read.'})


# ─── Detail / Delete ──────────────────────────────────────────────────────────────

class NotificationDeleteView(APIView):
    """GET /api/notifications/<id>/    — one notification, for its recipient.
    DELETE /api/notifications/<id>/   — Owner/Staff can delete any; a user can delete their own."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk)
        except Notification.DoesNotExist:
            raise NotFound('Notification not found.')
        if getattr(request, 'gym', None) is not None and notification.gym_id != getattr(request, 'gym', None).id:
            raise NotFound('Notification not found.')
        # Detail pages are personal — never leak another recipient's rows.
        if notification.recipient_id != request.user.id:
            raise NotFound('Notification not found.')
        return Response(NotificationSerializer(notification).data)

    def delete(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk)
        except Notification.DoesNotExist:
            raise NotFound('Notification not found.')
        if getattr(request, 'gym', None) is not None and notification.gym_id != getattr(request, 'gym', None).id:
            raise NotFound('Notification not found.')

        is_privileged = getattr(request, 'gym_role', request.user.role) in (User.Role.OWNER, User.Role.STAFF)
        if not is_privileged and notification.recipient != request.user:
            raise PermissionDenied('You do not have permission to delete this notification.')

        notification.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── Web Push subscriptions ─────────────────────────────────────────────────────

class PushPublicKeyView(APIView):
    """GET /api/notifications/push/public-key/ — the VAPID key the browser needs to subscribe."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        enabled = bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)
        return Response({'key': settings.VAPID_PUBLIC_KEY, 'enabled': enabled})


class PushSubscribeView(APIView):
    """
    POST /api/notifications/push/subscribe/ — register this device for push.

    Upserts by endpoint: if the same browser endpoint comes in again (another
    user logs in on the same device) the row is reassigned to the new user.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PushSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub, created = PushSubscription.objects.update_or_create(
            endpoint=serializer.validated_data['endpoint'],
            defaults={**serializer.validated_data, 'user': request.user},
        )
        return Response(
            {'id': sub.id, 'created': created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PushUnsubscribeView(APIView):
    """POST /api/notifications/push/unsubscribe/ — remove this device (used on logout)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        endpoint = request.data.get('endpoint', '')
        deleted, _ = PushSubscription.objects.filter(
            user=request.user, endpoint=endpoint,
        ).delete()
        return Response({'deleted': deleted})


class PushTestView(APIView):
    """
    POST /api/notifications/push/test/ — fire a real Web Push at the caller's
    own devices so the whole chain can be verified in one tap from a phone:
    subscription saved? VAPID keys configured? push service delivering?

    The three response fields are needed together to interpret a failure:
      - subscriptions=0  → this device never completed the opt-in
      - configured=false → the server has no VAPID keys in its environment
      - delivered=0 with both of the above fine → the push service rejected
        the send; the response explains where it stopped.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.notifications.services import send_push

        subscriptions = PushSubscription.objects.filter(user=request.user).count()
        delivered = send_push(
            request.user,
            'FitCore test',
            'If you can read this on your device, push notifications work end to end.',
            Notification.NotificationType.GENERAL,
        )
        configured = bool(
            getattr(settings, 'VAPID_PUBLIC_KEY', '')
            and getattr(settings, 'VAPID_PRIVATE_KEY', '')
        )
        return Response({
            'subscriptions': subscriptions,
            'delivered': delivered,
            'configured': configured,
        })
