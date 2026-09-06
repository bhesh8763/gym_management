"""
Custom allauth provider adapters that force callback URLs to use
``localhost`` instead of ``127.0.0.1``.  Facebook requires ``localhost``
for HTTP in development — ``127.0.0.1`` is rejected.
"""
from urllib.parse import urlparse, urlunparse

from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.facebook.views import FacebookOAuth2Adapter


def _force_localhost(url: str) -> str:
    """Replace 127.0.0.1 / ::1 with ``localhost`` so Facebook accepts HTTP."""
    parsed = urlparse(url)
    if parsed.hostname in ("127.0.0.1", "::1"):
        replaced = parsed._replace(
            netloc=parsed.netloc.replace(parsed.hostname, "localhost")
        )
        return urlunparse(replaced)
    return url


class CustomGoogleOAuth2Adapter(GoogleOAuth2Adapter):
    def get_callback_url(self, request, app):
        return _force_localhost(super().get_callback_url(request, app))


class CustomFacebookOAuth2Adapter(FacebookOAuth2Adapter):
    def get_callback_url(self, request, app):
        return _force_localhost(super().get_callback_url(request, app))
