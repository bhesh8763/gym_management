from django.urls import path

from .views import (
    ProgressEntryListCreateView,
    ProgressEntryDetailView,
    PersonalRecordListCreateView,
    PersonalRecordDetailView,
    MemberStatsView,
)

urlpatterns = [
    path('member-stats/', MemberStatsView.as_view(), name='progress-member-stats'),
    path('entries/', ProgressEntryListCreateView.as_view(), name='progress-entry-list'),
    path('entries/<int:pk>/', ProgressEntryDetailView.as_view(), name='progress-entry-detail'),

    path('personal-records/', PersonalRecordListCreateView.as_view(), name='personal-record-list'),
    path('personal-records/<int:pk>/', PersonalRecordDetailView.as_view(), name='personal-record-detail'),
]
