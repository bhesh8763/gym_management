from django.urls import path
from . import views

urlpatterns = [
    # JSON report endpoints
    path('overview/', views.overview_report, name='report-overview'),
    path('revenue/', views.revenue_report, name='report-revenue'),
    path('memberships/', views.membership_report, name='report-memberships'),
    path('attendance/', views.attendance_report, name='report-attendance'),
    path('equipment/', views.equipment_report, name='report-equipment'),
    path('lockers/', views.locker_report, name='report-lockers'),
    path('staff/', views.staff_report, name='report-staff'),

    # Export endpoints — CSV or Excel via ?format=csv|excel
    path('export/attendance/', views.export_attendance, name='export-attendance'),
    path('export/memberships/', views.export_memberships, name='export-memberships'),
    path('export/revenue/', views.export_revenue, name='export-revenue'),
    path('export/members/', views.export_members, name='export-members'),
    path('export/equipment/', views.export_equipment, name='export-equipment'),
    path('export/maintenance/', views.export_maintenance, name='export-maintenance'),
    path('export/diet/', views.export_diet, name='export-diet'),
    path('export/progress/', views.export_progress, name='export-progress'),
    path('export/staff/', views.export_staff, name='export-staff'),
]
