"""
URL configuration for gym_management project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth endpoints
    path('api/auth/', include('apps.accounts.urls')),

    # Members — API (/api/members/…) + UI (/members/ui/…) both served from
    # the same URLconf with the 'members' app_name namespace.
    path('api/members/', include('apps.members.urls', namespace='members')),

    # Template UI shortcut — redirect /members/ to the UI list view
    # (the actual UI routes live under /api/members/ui/ via the urlconf above)
    path('api/memberships/', include('apps.memberships.urls')),
    path('api/attendance/', include('apps.attendance.urls')),
    path('api/payments/', include('apps.payments.urls')),
    path('api/staff/', include('apps.staff.urls')),
    path('api/trainers/', include('apps.trainers.urls')),
    path('api/workouts/', include('apps.workouts.urls')),
    path('api/diet/', include('apps.diet.urls')),
    path('api/progress/', include('apps.progress.urls')),
    path('api/lockers/', include('apps.lockers.urls')),
    path('api/equipment/', include('apps.equipment.urls')),
    path('api/notifications/', include('apps.notifications.urls')),
    path('api/reports/', include('apps.reports.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
