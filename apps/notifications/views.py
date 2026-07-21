"""
Views for the Notifications app.

API Endpoints:
    GET    /api/notifications/                - List my notifications (any authenticated user)
    POST   /api/notifications/                 - Push a notification to one or more users (Owner/Staff)
    GET    /api/notifications/unread-count/    - Count of unread notifications for me
    PATCH  /api/notifications/<id>/read/       - Mark one notification as read
    POST   /api/notifications/mark-all-read/   - Mark all my notifications as read
    DELETE /api/notifications/<id>/            - Delete a notification (Owner/Staff, or the recipient)

Search/Filter (query params on list):
    ?is_read=<true|false>
    ?notification_type=<MEMBERSHIP_EXPIRY|PAYMENT_DUE|...>
"""
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwnerOrStaff
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationCreateSerializer, NotificationSerializer


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
        qs = Notification.objects.filter(recipient=self.request.user)

        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            qs = qs.filter(is_read=is_read.lower() in ('true', '1', 'yes'))

        notification_type = self.request.query_params.get('notification_type')
        if notification_type:
            qs = qs.filter(notification_type=notification_type)

        return qs

    def create(self, request, *args, **kwargs):
        serializer = NotificationCreateSerializer(data=request.data)
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
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({'unread_count': count})


# ─── Mark single as read ───────────────────────────────────────────────────────

class MarkAsReadView(APIView):
    """PATCH /api/notifications/<id>/read/ — mark one notification as read."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, recipient=request.user)
        except Notification.DoesNotExist:
            raise NotFound('Notification not found.')
        notification.mark_read()
        return Response(NotificationSerializer(notification).data)


# ─── Mark all as read ───────────────────────────────────────────────────────────

class MarkAllAsReadView(APIView):
    """POST /api/notifications/mark-all-read/ — mark every unread notification as read."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        updated = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return Response({'detail': f'{updated} notification(s) marked as read.'})


# ─── Delete ─────────────────────────────────────────────────────────────────────

class NotificationDeleteView(APIView):
    """DELETE /api/notifications/<id>/ — Owner/Staff can delete any; a user can delete their own."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk)
        except Notification.DoesNotExist:
            raise NotFound('Notification not found.')

        is_privileged = request.user.role in ('OWNER', 'STAFF')
        if not is_privileged and notification.recipient != request.user:
            raise PermissionDenied('You do not have permission to delete this notification.')

        notification.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
