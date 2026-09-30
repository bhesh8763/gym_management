"""
Signals for the Accounts app.

Ensures every User with role=MEMBER always has a matching MemberProfile row,
regardless of which code path created the User:
  - Public self-registration (/api/auth/register/)
  - Owner/Staff "Add Member" form (/api/members/)
  - Django admin
  - python manage.py shell / createsuperuser-style scripts

Without this, a User could exist and log in successfully while never
appearing on the Members page, since that page reads from MemberProfile,
not User, directly.
"""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_member_profile_for_new_members(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.role != instance.Role.MEMBER:
        return

    # Local import avoids a circular import between accounts <-> members at app load time.
    from apps.members.models import MemberProfile
    MemberProfile.objects.get_or_create(user=instance)
