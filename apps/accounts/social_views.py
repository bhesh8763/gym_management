"""
Custom OAuth2 views that use adapters which force ``localhost`` in
callback URLs (see adapters.py).
"""
from allauth.socialaccount.providers.oauth2.views import (
    OAuth2CallbackView,
    OAuth2LoginView,
)

from .adapters import CustomGoogleOAuth2Adapter, CustomFacebookOAuth2Adapter


google_login = OAuth2LoginView.adapter_view(CustomGoogleOAuth2Adapter)
google_callback = OAuth2CallbackView.adapter_view(CustomGoogleOAuth2Adapter)

facebook_login = OAuth2LoginView.adapter_view(CustomFacebookOAuth2Adapter)
facebook_callback = OAuth2CallbackView.adapter_view(CustomFacebookOAuth2Adapter)
