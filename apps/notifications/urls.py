from django.urls import path

from apps.notifications.views import (
    MarkAllAsReadView,
    MarkAsReadView,
    NotificationDeleteView,
    NotificationListCreateView,
    UnreadCountView,
)

urlpatterns = [
    path('', NotificationListCreateView.as_view(), name='notification-list-create'),
    path('unread-count/', UnreadCountView.as_view(), name='notification-unread-count'),
    path('mark-all-read/', MarkAllAsReadView.as_view(), name='notification-mark-all-read'),
    path('<int:pk>/read/', MarkAsReadView.as_view(), name='notification-mark-read'),
    path('<int:pk>/', NotificationDeleteView.as_view(), name='notification-delete'),
]
