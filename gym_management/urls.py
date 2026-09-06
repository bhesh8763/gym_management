"""
URL configuration for gym_management project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from allauth.socialaccount import providers
from allauth.socialaccount.providers.oauth2.views import (
    OAuth2CallbackView,
    OAuth2LoginView,
)
from allauth.socialaccount.providers.oauth2.urls import default_urlpatterns
from allauth.socialaccount.providers.google.provider import GoogleProvider
from allauth.socialaccount.providers.facebook.provider import FacebookProvider
from apps.accounts.adapters import CustomGoogleOAuth2Adapter, CustomFacebookOAuth2Adapter

# Custom views that force ``localhost`` in callback URLs so Facebook
# Login works over plain HTTP during local development.
google_login = OAuth2LoginView.adapter_view(CustomGoogleOAuth2Adapter)
google_callback = OAuth2CallbackView.adapter_view(CustomGoogleOAuth2Adapter)
facebook_login = OAuth2LoginView.adapter_view(CustomFacebookOAuth2Adapter)
facebook_callback = OAuth2CallbackView.adapter_view(CustomFacebookOAuth2Adapter)


def _build_provider_urls():
    """Collect login/callback URLs from each installed social provider.

    Google and Facebook use custom adapters that force ``localhost`` in
    the callback URL so Facebook Login works over HTTP in development.
    """
    # Google & Facebook: custom views that force localhost
    custom = default_urlpatterns(GoogleProvider) + default_urlpatterns(FacebookProvider)
    for entry in custom:
        if hasattr(entry, 'pattern') and hasattr(entry.pattern, 'url_patterns'):
            for sub in entry.pattern.url_patterns:
                if sub.name == 'google_login':
                    sub.callback = google_login
                elif sub.name == 'google_callback':
                    sub.callback = google_callback
                elif sub.name == 'facebook_login':
                    sub.callback = facebook_login
                elif sub.name == 'facebook_callback':
                    sub.callback = facebook_callback

    # Dynamically load all other providers (skip google/facebook)
    skip = {'google', 'facebook'}
    for cls in providers.registry.get_class_list():
        if cls.id in skip:
            continue
        try:
            mod = __import__(cls.get_package() + '.urls', fromlist=['urlpatterns'])
            custom += getattr(mod, 'urlpatterns', [])
        except Exception:
            pass
    return custom


urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth endpoints
    path('api/auth/', include('apps.accounts.urls')),

    # Social auth — provider login/callback (google/login/, facebook/login/, etc.)
    path('api/auth/', include(_build_provider_urls())),
    path('api/auth/3rdparty/', include('allauth.socialaccount.urls')),

    # Members — API (/api/members/…) + UI (/members/ui/…) both served from
    # the same URLconf with the 'members' app_name namespace.
    path('api/members/', include('apps.members.urls', namespace='members')),

    # Template UI shortcut — redirect /members/ to the UI list view
    # (the actual UI routes live under /api/members/ui/ via the urlconf above)
    path('api/memberships/', include('apps.memberships.urls')),
    path('api/attendance/', include('apps.attendance.urls')),
    path('api/payments/', include('apps.payments.urls')),
    path('api/staff/', include('apps.staff.urls')),
    path('api/workouts/', include('apps.workouts.urls')),
    path('api/diet/', include('apps.diet.urls')),
    path('api/progress/', include('apps.progress.urls')),
    path('api/lockers/', include('apps.lockers.urls')),
    path('api/equipment/', include('apps.equipment.urls')),
    path('api/notifications/', include('apps.notifications.urls')),
    path('api/reports/', include('apps.reports.urls')),
    path('api/trainers/', include('apps.trainers.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
