"""
One-off fix for Members created before the auto-profile signal existed
(e.g. anyone who self-registered via /api/auth/register/ and never got
a MemberProfile row, so they never appeared on the Members page).

Run once after deploying the signal:
    python manage.py backfill_member_profiles

Safe to run multiple times — uses get_or_create, so it's a no-op for
members that already have a profile.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.members.models import MemberProfile

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a MemberProfile for any existing User with role=MEMBER that is missing one.'

    def handle(self, *args, **options):
        members_without_profile = User.objects.filter(
            role=User.Role.MEMBER, member_profile__isnull=True
        )
        count = 0
        for user in members_without_profile:
            MemberProfile.objects.get_or_create(user=user)
            self.stdout.write(f'  created profile for {user.email}')
            count += 1

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No missing profiles found — nothing to do.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Created {count} missing member profile(s).'))
