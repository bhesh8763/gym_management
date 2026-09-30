"""Helpers for issuing tenant-aware JWT refresh tokens."""


def token_for_membership(user, membership=None):
    """Return a refresh token with the account's active gym claims.

    Keeping this in one place prevents registration, gym switching, invitations,
    and impersonation from silently issuing a token that falls back to a
    different (or no) tenant.
    """
    from .serializers import CustomTokenObtainPairSerializer

    token = CustomTokenObtainPairSerializer.get_token(user)
    if membership is None:
        from apps.gyms.tenancy import get_user_membership
        membership = get_user_membership(user)
    if membership is not None:
        token['gym_id'] = membership.gym_id
        token['gym_role'] = membership.role
        token['gym_public_id'] = membership.gym.public_id
        token['role'] = membership.role
    return token
