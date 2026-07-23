from django.urls import path
from . import views

urlpatterns = [
    path('overview/', views.overview_report, name='report-overview'),
    path('revenue/', views.revenue_report, name='report-revenue'),
    path('memberships/', views.membership_report, name='report-memberships'),
    path('attendance/', views.attendance_report, name='report-attendance'),
    path('equipment/', views.equipment_report, name='report-equipment'),
    path('lockers/', views.locker_report, name='report-lockers'),
    path('staff/', views.staff_report, name='report-staff'),
]
