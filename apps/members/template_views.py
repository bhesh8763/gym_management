"""
Template-based views for the Members UI.

These views render Django HTML templates and are backed by the same
MemberProfile model used by the REST API.  Authentication is enforced
via Django session / JWT cookie — for simplicity we use
login_required + role checks directly.

URLs (mounted under /members/ui/):
    GET  /members/ui/              — member list with search + filter
    GET  /members/ui/add/          — blank create form
    POST /members/ui/add/          — process create form
    GET  /members/ui/<pk>/         — member detail
    GET  /members/ui/<pk>/edit/    — pre-populated edit form
    POST /members/ui/<pk>/edit/    — process edit form
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from rest_framework.exceptions import PermissionDenied

from apps.gyms.models import GymMembership
from apps.gyms.tenancy import resolve_request_tenant
from apps.members.models import MemberProfile

User = get_user_model()

# ─── Tenant/session guard helpers ──────────────────────────────────────────────

def _bind_request_tenant(request):
    """Attach the same request-local tenant used by the REST API to UI views."""
    if not request.user.is_authenticated:
        return False
    try:
        membership = resolve_request_tenant(request, request.user)
    except PermissionDenied:
        return False
    if getattr(settings, 'TENANCY_REQUIRE_MEMBERSHIP', False) and membership is None:
        return False
    return True


def _request_role(request):
    return getattr(request, 'gym_role', request.user.role)


def _profile_queryset(request):
    qs = MemberProfile.objects.select_related('user')
    gym = getattr(request, 'gym', None)
    if gym is not None:
        qs = qs.filter(gym=gym)
    branch = getattr(request, 'branch', None)
    if branch is not None:
        qs = qs.filter(Q(branch=branch) | Q(branch__isnull=True))
    return qs


def _member_profile_queryset(request):
    qs = _profile_queryset(request)
    gym = getattr(request, 'gym', None)
    if gym is not None:
        return qs.filter(
            user__gym_memberships__gym=gym,
            user__gym_memberships__role=GymMembership.Role.MEMBER,
            user__gym_memberships__status=GymMembership.Status.ACTIVE,
        ).distinct()
    return qs.filter(user__role=User.Role.MEMBER)


class TenantLoginRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _bind_request_tenant(request):
            return HttpResponseForbidden('An active gym membership and branch are required.')
        return super().dispatch(request, *args, **kwargs)


class StaffRequiredMixin(TenantLoginRequiredMixin):
    """Allow only Owner and Staff to access management views in the active gym."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if not _bind_request_tenant(request):
                return HttpResponseForbidden('An active gym membership and branch are required.')
            if _request_role(request) not in (User.Role.OWNER, User.Role.STAFF):
                messages.error(request, 'Access restricted to owners and staff.')
                return redirect('members:ui-list')
        return super().dispatch(request, *args, **kwargs)


# ─── List ─────────────────────────────────────────────────────────────────────

class MemberListTemplateView(TenantLoginRequiredMixin, View):
    template_name = 'members/member_list.html'

    def get(self, request):
        qs = _member_profile_queryset(request)

        search = request.GET.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__phone__icontains=search)
            )

        fitness_goal = request.GET.get('fitness_goal', '')
        if fitness_goal:
            qs = qs.filter(fitness_goal=fitness_goal)

        fitness_level = request.GET.get('fitness_level', '')
        if fitness_level:
            qs = qs.filter(fitness_level=fitness_level)

        gender = request.GET.get('gender', '')
        if gender:
            qs = qs.filter(gender=gender)

        is_active = request.GET.get('is_active', '')
        if is_active in ('true', 'false'):
            qs = qs.filter(user__is_active=(is_active == 'true'))

        ordering = request.GET.get('ordering', '-created_at')
        valid_orderings = {
            'created_at': 'created_at',
            '-created_at': '-created_at',
            'full_name': 'user__first_name',
            '-full_name': '-user__first_name',
        }
        qs = qs.order_by(valid_orderings.get(ordering, '-created_at'))

        from django.utils import timezone
        all_members = _member_profile_queryset(request)
        now = timezone.now()
        context = {
            'members': qs,
            'search': search,
            'fitness_goal': fitness_goal,
            'fitness_level': fitness_level,
            'gender': gender,
            'is_active': is_active,
            'ordering': ordering,
            'fitness_goal_choices': MemberProfile.FitnessGoal.choices,
            'fitness_level_choices': MemberProfile.FitnessLevel.choices,
            'gender_choices': MemberProfile.Gender.choices,
            'total_count': qs.count(),
            'active_count': all_members.filter(user__is_active=True).count(),
            'inactive_count': all_members.filter(user__is_active=False).count(),
            'new_this_month': all_members.filter(
                created_at__year=now.year,
                created_at__month=now.month
            ).count(),
        }
        return render(request, self.template_name, context)


# ─── Create ───────────────────────────────────────────────────────────────────

class MemberCreateTemplateView(StaffRequiredMixin, View):
    template_name = 'members/member_form.html'

    def get(self, request):
        context = {
            'action': 'create',
            'fitness_goal_choices': MemberProfile.FitnessGoal.choices,
            'fitness_level_choices': MemberProfile.FitnessLevel.choices,
            'gender_choices': MemberProfile.Gender.choices,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        data = request.POST
        errors = {}

        # Validate required fields
        email = data.get('email', '').strip()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        password = data.get('password', '')

        if not email:
            errors['email'] = 'Email is required.'
        elif User.objects.filter(email=email).exists():
            errors['email'] = 'A user with this email already exists.'

        if not first_name:
            errors['first_name'] = 'First name is required.'
        if not last_name:
            errors['last_name'] = 'Last name is required.'
        if not password:
            errors['password'] = 'Password is required.'
        elif len(password) < 8:
            errors['password'] = 'Password must be at least 8 characters.'

        if errors:
            context = {
                'action': 'create',
                'errors': errors,
                'form_data': data,
                'fitness_goal_choices': MemberProfile.FitnessGoal.choices,
                'fitness_level_choices': MemberProfile.FitnessLevel.choices,
                'gender_choices': MemberProfile.Gender.choices,
            }
            return render(request, self.template_name, context)

        # Create user
        gym = getattr(request, 'gym', None)
        branch = getattr(request, 'branch', None)
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=data.get('phone', ''),
            role=User.Role.MEMBER,
        )
        user.set_password(password)
        if 'profile_picture' in request.FILES:
            user.profile_picture = request.FILES['profile_picture']
        user.save()

        # Create the tenant membership and profile together. The legacy
        # gym=None branch is retained only for compatibility mode.
        if gym is not None:
            membership, _ = GymMembership.objects.get_or_create(
                user=user,
                gym=gym,
                defaults={
                    'role': GymMembership.Role.MEMBER,
                    'status': GymMembership.Status.ACTIVE,
                    'is_default': True,
                },
            )
            if not user.gym_memberships.filter(is_default=True).exists():
                membership.is_default = True
                membership.save(update_fields=['is_default', 'updated_at'])
            if branch is not None:
                membership.branch_memberships.get_or_create(branch=branch)

        # Create profile (reuse the signal-created legacy row when possible).
        profile = MemberProfile._base_manager.filter(user=user, gym=gym).first()
        if profile is None:
            profile = MemberProfile._base_manager.filter(
                user=user, gym__isnull=True,
            ).first()
        if profile is None:
            profile = MemberProfile(user=user, gym=gym, branch=branch)
        elif profile.is_deleted:
            # Revive a trashed profile instead of leaving it invisible.
            profile.restore()
        if profile.gym_id is None:
            profile.gym = gym
            profile.branch = branch
        profile.date_of_birth = data.get('date_of_birth') or None
        profile.gender = data.get('gender', '')
        profile.address = data.get('address', '')
        profile.emergency_contact_name = data.get('emergency_contact_name', '')
        profile.emergency_contact_phone = data.get('emergency_contact_phone', '')
        profile.height_cm = data.get('height_cm') or None
        profile.weight_kg = data.get('weight_kg') or None
        profile.fitness_goal = data.get('fitness_goal', '')
        profile.fitness_level = data.get('fitness_level', MemberProfile.FitnessLevel.BEGINNER)
        profile.medical_conditions = data.get('medical_conditions', '')
        profile.notes = data.get('notes', '')
        profile.save()

        messages.success(request, f'Member "{user.get_full_name()}" created successfully.')
        return redirect('members:ui-detail', pk=profile.pk)


# ─── Detail ───────────────────────────────────────────────────────────────────

class MemberDetailTemplateView(TenantLoginRequiredMixin, View):
    template_name = 'members/member_detail.html'

    def get(self, request, pk):
        profile = get_object_or_404(
            _profile_queryset(request), pk=pk
        )
        # Members can only see their own profile
        if _request_role(request) == User.Role.MEMBER and profile.user != request.user:
            messages.error(request, 'You can only view your own profile.')
            return redirect('members:ui-list')

        context = {'profile': profile}
        return render(request, self.template_name, context)


# ─── Edit ─────────────────────────────────────────────────────────────────────

class MemberEditTemplateView(TenantLoginRequiredMixin, View):
    template_name = 'members/member_form.html'

    def _can_edit(self, request, profile):
        if _request_role(request) in (User.Role.OWNER, User.Role.STAFF):
            return True
        return profile.user == request.user

    def get(self, request, pk):
        profile = get_object_or_404(
            _profile_queryset(request), pk=pk
        )
        if not self._can_edit(request, profile):
            messages.error(request, 'You do not have permission to edit this profile.')
            return redirect('members:ui-detail', pk=pk)

        context = {
            'action': 'edit',
            'profile': profile,
            'fitness_goal_choices': MemberProfile.FitnessGoal.choices,
            'fitness_level_choices': MemberProfile.FitnessLevel.choices,
            'gender_choices': MemberProfile.Gender.choices,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        profile = get_object_or_404(
            _profile_queryset(request), pk=pk
        )
        if not self._can_edit(request, profile):
            messages.error(request, 'You do not have permission to edit this profile.')
            return redirect('members:ui-detail', pk=pk)

        data = request.POST
        user = profile.user

        # Update user fields (owner/staff can change more)
        if _request_role(request) in (User.Role.OWNER, User.Role.STAFF):
            user.first_name = data.get('first_name', user.first_name).strip()
            user.last_name = data.get('last_name', user.last_name).strip()
            user.phone = data.get('phone', user.phone)
            is_active_str = data.get('is_active', '')
            if is_active_str:
                user.is_active = is_active_str == 'true'
        if 'profile_picture' in request.FILES:
            user.profile_picture = request.FILES['profile_picture']
        user.save()

        # Update profile fields
        profile.date_of_birth = data.get('date_of_birth') or None
        profile.gender = data.get('gender', profile.gender)
        profile.address = data.get('address', profile.address)
        profile.emergency_contact_name = data.get(
            'emergency_contact_name', profile.emergency_contact_name
        )
        profile.emergency_contact_phone = data.get(
            'emergency_contact_phone', profile.emergency_contact_phone
        )
        profile.height_cm = data.get('height_cm') or profile.height_cm
        profile.weight_kg = data.get('weight_kg') or profile.weight_kg
        profile.fitness_goal = data.get('fitness_goal', profile.fitness_goal)
        profile.fitness_level = data.get('fitness_level', profile.fitness_level)
        profile.medical_conditions = data.get('medical_conditions', profile.medical_conditions)
        profile.notes = data.get('notes', profile.notes)
        profile.save()

        messages.success(request, 'Profile updated successfully.')
        return redirect('members:ui-detail', pk=profile.pk)
