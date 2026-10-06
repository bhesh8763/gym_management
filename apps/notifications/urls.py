from django.urls import path

from apps.notifications.views import (
    MarkAllAsReadView,
    MarkAsReadView,
    NotificationDeleteView,
    NotificationListCreateView,
    PushPublicKeyView,
    PushSubscribeView,
    PushUnsubscribeView,
    UnreadCountView,
)

urlpatterns = [
    path('', NotificationListCreateView.as_view(), name='notification-list-create'),
    path('unread-count/', UnreadCountView.as_view(), name='notification-unread-count'),
    path('mark-all-read/', MarkAllAsReadView.as_view(), name='notification-mark-all-read'),
    # Web Push — literal 'push/...' must precede the int converter routes
    path('push/public-key/', PushPublicKeyView.as_view(), name='notification-push-key'),
    path('push/subscribe/', PushSubscribeView.as_view(), name='notification-push-subscribe'),
    path('push/unsubscribe/', PushUnsubscribeView.as_view(), name='notification-push-unsubscribe'),
    path('<int:pk>/read/', MarkAsReadView.as_view(), name='notification-mark-read'),
    path('<int:pk>/', NotificationDeleteView.as_view(), name='notification-delete'),
]
