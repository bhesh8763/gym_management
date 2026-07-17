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

    # Module endpoints
    path('api/members/', include('apps.members.urls')),
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
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
