"""
JWT claims serializer for dj-rest-auth (social login flows).

dj-rest-auth encodes JWTs for Google/Facebook logins through
``REST_AUTH['JWT_TOKEN_CLAIMS_SERIALIZER']``. Pointing it at this class
ensures social-login tokens carry the same ``token_version`` claim as
password-login tokens, so the version check in authentication applies
uniformly to every token the backend issues.
"""
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.serializers import CustomTokenObtainPairSerializer


class SocialTokenObtainPairSerializer(CustomTokenObtainPairSerializer, TokenObtainPairSerializer):
    """Claims serializer used by dj-rest-auth's ``jwt_encode``.

    Inherits ``get_token`` from ``CustomTokenObtainPairSerializer`` so the
    ``token_version``/``role``/``email`` claims are embedded identically for
    social-login sessions. The double base is only for import clarity.
    """

    def validate(self, attrs):
        # dj-rest-auth never calls validate() with credentials — it only
        # uses get_token(). Make validate() harmless if it were ever hit.
        raise NotImplementedError('This serializer is only for token claims, not credential login.')
