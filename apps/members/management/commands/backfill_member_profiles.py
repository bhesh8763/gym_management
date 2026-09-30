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

from apps.gyms.models import GymMembership
from apps.members.models import MemberProfile

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a MemberProfile for any existing User with role=MEMBER that is missing one.'

    def handle(self, *args, **options):
        count = 0
        seen_users = set()
        memberships = GymMembership.objects.filter(
            role=GymMembership.Role.MEMBER,
            status=GymMembership.Status.ACTIVE,
            gym__status__in=['ACTIVE', 'TRIAL'],
        ).select_related('user', 'gym')
        for membership in memberships:
            access = membership.branch_memberships.select_related('branch').first()
            MemberProfile.objects.get_or_create(
                user=membership.user,
                gym=membership.gym,
                defaults={'branch': access.branch if access else None},
            )
            seen_users.add(membership.user_id)
            count += 1

        # Preserve the legacy compatibility path for users that predate
        # GymMembership entirely; production requests never rely on gym=None.
        for user in User.objects.filter(role=User.Role.MEMBER).exclude(pk__in=seen_users):
            MemberProfile.objects.get_or_create(user=user, gym=None)
            count += 1

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No missing profiles found — nothing to do.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Ensured {count} member profile row(s).'))
