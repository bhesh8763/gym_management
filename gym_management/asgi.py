"""
ASGI config for gym_management project.

HTTP requests go to Django exactly as before; WebSocket upgrades are routed
to the realtime messaging consumer via Django Channels. Served by daphne in
production (see render.yaml) and by `manage.py runserver` in development —
Channels swaps runserver over to ASGI automatically once `channels` is in
INSTALLED_APPS.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gym_management.settings')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter            # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator   # noqa: E402

from apps.notifications.routing import websocket_urlpatterns          # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    # Origin must match ALLOWED_HOSTS (dev: localhost, prod: the Render
    # hostname) — blocks cross-site WebSocket hijacking from other origins.
    'websocket': AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
})
