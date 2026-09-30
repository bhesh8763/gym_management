"""
Custom JWT authentication with instant access-token revocation.

SimpleJWT's stock ``JWTAuthentication`` verifies only the token's signature
and expiry — nothing in the database, so an access token stays valid until
its ``exp`` no matter what happens to the user's password.

This class adds one cheap check on top: every token we issue carries a
``token_version`` claim equal to the user's ``token_version`` at issue time
(bumped automatically by ``User.set_password``). If the claim does not match
the current DB value, the token is rejected with 401.

Cost is negligible: SimpleJWT already loads the User row for every
authenticated request, so this only reads one extra field from an object
that is fetched anyway.
"""
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class VersionedJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        """Authenticate, validate impersonation state, and resolve the tenant."""
        result = super().authenticate(request)
        if result is None:
            return result
        user, token = result
        request.jwt_claim_gym_id = token.get('gym_id')

        impersonation_id = token.get('impersonation_id')
        if impersonation_id is not None:
            from apps.gyms.models import ImpersonationSession
            session = ImpersonationSession.objects.select_related('actor', 'subject').filter(
                pk=impersonation_id,
            ).first()
            if session is None or not session.is_active:
                raise InvalidToken('Impersonation session is invalid or expired.')
            if (
                session.subject_id != user.id
                or session.actor_id != token.get('actor_id')
                or str(session.gym_id) != str(token.get('gym_id'))
            ):
                raise InvalidToken('Impersonation session identity does not match this token.')
            request.impersonation_session = session
            request.impersonation_actor = session.actor

        from apps.gyms.tenancy import resolve_request_tenant
        membership = resolve_request_tenant(request, user)
        from django.conf import settings
        if getattr(settings, 'TENANCY_REQUIRE_MEMBERSHIP', False) and membership is None:
            raise InvalidToken('An active gym membership is required.')
        return user, token

    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        token_version = validated_token.get('token_version')
        if token_version is None:
            # Tokens issued before this feature (or by other tooling)
            # carry no claim. Accept them so a deploy doesn't log everyone
            # out; they age out naturally within ACCESS_TOKEN_LIFETIME.
            return user

        try:
            current = int(user.token_version or 0)
            claimed = int(token_version)
        except (TypeError, ValueError):
            raise InvalidToken('Token version claim is malformed.')

        if claimed != current:
            # Password changed (or was reset / force-invalidated) after
            # this token was issued.
            raise InvalidToken('User session has been invalidated.')

        return user
