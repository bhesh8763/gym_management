"""
Serializers for the Members app.

Handles member profile creation, update, and read with computed fields.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from django.db.models import Q
from rest_framework import serializers

from apps.members.models import MemberProfile

User = get_user_model()


# ─── Nested user serializer used inside profile responses ─────────────────────

class MemberUserSerializer(serializers.ModelSerializer):
    """Lightweight user fields embedded in profile responses."""

    full_name = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'middle_name', 'last_name', 'full_name',
            'phone', 'profile_picture', 'is_active', 'date_joined',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_profile_picture(self, obj):
        if not obj.profile_picture:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.profile_picture.url)
        # Fallback to relative URL if no request context
        return obj.profile_picture.url


# ─── Main profile serializers ─────────────────────────────────────────────────

class MemberProfileSerializer(serializers.ModelSerializer):
    """
    Full read serializer — returned by list, detail, and create/update responses.
    Includes nested user info and computed bmi.
    """
    user = MemberUserSerializer(read_only=True)
    bmi = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    fitness_goal_display = serializers.CharField(source='get_fitness_goal_display', read_only=True)
    fitness_level_display = serializers.CharField(source='get_fitness_level_display', read_only=True)

    class Meta:
        model = MemberProfile
        fields = [
            'id', 'user', 'gym', 'branch',
            'date_of_birth', 'gender', 'gender_display',
            'address',
            'emergency_contact_name', 'emergency_contact_phone',
            'height_cm', 'weight_kg', 'bmi',
            'fitness_goal', 'fitness_goal_display',
            'fitness_level', 'fitness_level_display',
            'medical_conditions', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'user', 'created_at', 'updated_at']

    def get_bmi(self, obj):
        return obj.bmi


class MemberProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for updating a member's own profile fields.
    Does not touch the linked User record — use MeView for that.
    """

    class Meta:
        model = MemberProfile
        fields = [
            'date_of_birth', 'gender', 'address',
            'emergency_contact_name', 'emergency_contact_phone',
            'height_cm', 'weight_kg',
            'fitness_goal', 'fitness_level',
            'medical_conditions', 'notes',
        ]


# ─── Member creation (admin/staff creates both user + profile) ────────────────

class MemberCreateSerializer(serializers.Serializer):
    """
    Used by Owner/Staff to create a new Member user + profile in one request.

    Required user fields:  email, first_name, last_name, password
    Optional user fields:  phone, profile_picture
    Optional profile fields: everything else
    """
    # User fields
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    profile_picture = serializers.ImageField(required=False, allow_null=True)
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )

    # Profile fields
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=MemberProfile.Gender.choices, required=False, allow_blank=True
    )
    address = serializers.CharField(required=False, allow_blank=True)
    emergency_contact_name = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    emergency_contact_phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )
    height_cm = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )
    weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )
    fitness_goal = serializers.ChoiceField(
        choices=MemberProfile.FitnessGoal.choices, required=False, allow_blank=True
    )
    fitness_level = serializers.ChoiceField(
        choices=MemberProfile.FitnessLevel.choices, required=False,
        default=MemberProfile.FitnessLevel.BEGINNER,
    )
    medical_conditions = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        existing = User.objects.filter(email__iexact=value).first()
        if existing and gym is None:
            raise serializers.ValidationError('A user with this email already exists.')
        if existing and gym is not None:
            from apps.gyms.models import GymMembership
            if GymMembership.objects.filter(
                user=existing, gym=gym, status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError('This user is already a member of this gym.')
        return value

    def create(self, validated_data):
        # Split user vs profile fields
        user_fields = ['email', 'first_name', 'middle_name', 'last_name', 'phone', 'profile_picture', 'password']
        user_data = {k: validated_data.pop(k) for k in user_fields if k in validated_data}
        password = user_data.pop('password')

        request = self.context.get('request')
        gym = getattr(request, 'gym', None)
        email = user_data.get('email', '')
        user = User.objects.filter(email__iexact=email).first()
        had_membership = user is not None and user.gym_memberships.exists()
        if user is None:
            user = User(role=User.Role.MEMBER, **user_data)
            user.set_password(password)
            user.save()
        elif not had_membership:
            # Preserve the account's identity; the tenant role is authoritative.
            user.role = User.Role.MEMBER
            user.save(update_fields=['role'])

        from apps.gyms.models import GymMembership
        if gym is not None:
            membership, _ = GymMembership.objects.get_or_create(
                user=user,
                gym=gym,
                defaults={
                    'role': User.Role.MEMBER,
                    'status': GymMembership.Status.ACTIVE,
                },
            )
            if not user.gym_memberships.filter(is_default=True).exists():
                membership.is_default = True
                membership.save(update_fields=['is_default', 'updated_at'])
            if not user.is_active:
                user.is_active = True
                user.save(update_fields=['is_active'])
            from apps.gyms.services import primary_branch
            request_branch = getattr(request, 'branch', None)
            branch = (
                request_branch
                if request_branch is not None and request_branch.gym_id == gym.id
                else primary_branch(gym)
            )
            if branch:
                membership.branch_memberships.get_or_create(branch=branch)

        # Create or update the profile (signal may have auto-created it)
        profile = MemberProfile._base_manager.filter(user=user, gym=gym).first()
        if profile is None:
            profile = MemberProfile._base_manager.filter(user=user, gym__isnull=True).first()
        if profile is None:
            profile = MemberProfile(user=user, gym=gym)
        elif profile.is_deleted:
            # Re-adding a member revives their trashed profile; without this
            # the row would keep deleted_at set and stay invisible everywhere.
            profile.restore()
        profile.gym = gym
        selected_branch = getattr(request, 'branch', None)
        if selected_branch is not None and selected_branch.gym_id != gym.id:
            selected_branch = None
        profile.branch = selected_branch
        if profile.branch is None and gym is not None:
            from apps.gyms.services import primary_branch
            profile.branch = primary_branch(gym)
        for attr, value in validated_data.items():
            setattr(profile, attr, value)
        profile.save()

        return profile


# ─── List serializer (lighter, no nested user detail) ────────────────────────

class MemberListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for the member list view.
    Shows key info without heavy nesting.
    """
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    display_id = serializers.CharField(source='user.display_id', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)
    profile_picture = serializers.SerializerMethodField()
    bmi = serializers.SerializerMethodField()
    fitness_goal_display = serializers.CharField(source='get_fitness_goal_display', read_only=True)
    fitness_level_display = serializers.CharField(source='get_fitness_level_display', read_only=True)
    current_membership = serializers.SerializerMethodField()

    class Meta:
        model = MemberProfile
        fields = [
            'id', 'user_id', 'gym', 'branch', 'display_id', 'full_name', 'email', 'phone', 'is_active',
            'profile_picture', 'gender',
            'fitness_goal', 'fitness_goal_display',
            'fitness_level', 'fitness_level_display',
            'bmi', 'current_membership', 'created_at',
        ]

    def get_bmi(self, obj):
        return obj.bmi

    def get_profile_picture(self, obj):
        if not obj.user.profile_picture:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.user.profile_picture.url)
        return obj.user.profile_picture.url

    def get_current_membership(self, obj):
        """
        Picks the membership that should represent this member's "current" plan
        for list/preview purposes: prefer ACTIVE, otherwise the one with the
        latest end_date. Excludes CANCELLED (soft-deleted) memberships.

        Uses the `_current_memberships` prefetch attached in the view's
        get_queryset() — falls back to a live query if that prefetch wasn't
        applied (e.g. if this serializer is reused somewhere else later).
        """
        memberships = getattr(obj.user, '_current_memberships', None)
        profile_gym_id = obj.gym_id or getattr(self.context.get('request'), 'gym_id', None)
        if memberships is None:
            memberships = list(
                obj.user.memberships.filter(gym_id=profile_gym_id)
                .exclude(status='CANCELLED')
                .select_related('plan')
            )

        if not memberships:
            return None
        memberships = [m for m in memberships if m.gym_id == profile_gym_id]

        if not memberships:
            return None

        def sort_key(m):
            is_active = m.status == 'ACTIVE'
            return (is_active, m.end_date)

        best = max(memberships, key=sort_key)
        return {
            'plan_name': best.plan.name,
            'status': best.status,
            'end_date': best.end_date,
        }


# ─── Aggregated profile detail serializer ─────────────────────────────────────

class MemberAggregatedProfileSerializer(serializers.ModelSerializer):
    """
    All-in-one serializer for the member profile detail page.
    Returns profile data plus related membership, attendance stats,
    workout assignment, diet plan, trainer, and recent progress.
    """
    user = MemberUserSerializer(read_only=True)
    bmi = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    fitness_goal_display = serializers.CharField(source='get_fitness_goal_display', read_only=True)
    fitness_level_display = serializers.CharField(source='get_fitness_level_display', read_only=True)

    # Membership
    active_membership = serializers.SerializerMethodField()
    membership_history = serializers.SerializerMethodField()

    # Attendance
    attendance_stats = serializers.SerializerMethodField()

    # Trainer
    assigned_trainer = serializers.SerializerMethodField()

    # Workouts
    active_workouts = serializers.SerializerMethodField()

    # Diet
    active_diet_plan = serializers.SerializerMethodField()

    # Progress
    latest_progress = serializers.SerializerMethodField()
    personal_records = serializers.SerializerMethodField()

    # Payments
    recent_payments = serializers.SerializerMethodField()
    payment_dues = serializers.SerializerMethodField()

    class Meta:
        model = MemberProfile
        fields = [
            'id', 'user',
            'date_of_birth', 'gender', 'gender_display',
            'address',
            'emergency_contact_name', 'emergency_contact_phone',
            'height_cm', 'weight_kg', 'bmi',
            'fitness_goal', 'fitness_goal_display',
            'fitness_level', 'fitness_level_display',
            'medical_conditions', 'notes',
            'active_membership', 'membership_history',
            'attendance_stats',
            'assigned_trainer',
            'active_workouts',
            'active_diet_plan',
            'latest_progress', 'personal_records',
            'recent_payments', 'payment_dues',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'user', 'created_at', 'updated_at']

    def _tenant_queryset(self, queryset, obj):
        """Scope reverse-relation queries to this profile's gym/branch.

        Related managers use Django's base manager, not ``objects`` (and
        therefore do not automatically inherit the request-local TenantManager).
        Keep these explicit filters in the aggregate serializer so a member
        who belongs to multiple gyms never sees another tenant's history.
        """
        request = self.context.get('request')
        gym_id = obj.gym_id or getattr(request, 'gym_id', None)
        queryset = queryset.filter(gym_id=gym_id)
        branch = getattr(request, 'branch', None) if request is not None else obj.branch
        if branch is not None:
            queryset = queryset.filter(Q(branch=branch) | Q(branch__isnull=True))
        return queryset

    def get_bmi(self, obj):
        return obj.bmi

    def get_active_membership(self, obj):
        ms = self._tenant_queryset(
            obj.user.memberships.filter(status='ACTIVE'), obj
        ).select_related('plan').order_by('-end_date').first()
        if not ms:
            return None
        return {
            'id': ms.id,
            'plan_name': ms.plan.name,
            'plan_price': str(ms.plan.price),
            'duration_days': ms.plan.duration_days,
            'status': ms.status,
            'start_date': ms.start_date,
            'end_date': ms.end_date,
            'price_paid': str(ms.price_paid),
            'days_remaining': ms.days_remaining,
        }

    def get_membership_history(self, obj):
        from apps.memberships.models import Membership
        memberships = self._tenant_queryset(
            obj.user.memberships.exclude(status='CANCELLED'), obj
        ).select_related('plan').order_by('-start_date')[:10]
        return [{
            'id': m.id,
            'plan_name': m.plan.name,
            'status': m.status,
            'start_date': m.start_date,
            'end_date': m.end_date,
            'price_paid': str(m.price_paid),
        } for m in memberships]

    def get_attendance_stats(self, obj):
        from apps.attendance.models import Attendance
        today = timezone.now().date()
        month_start = today.replace(day=1)
        records = self._tenant_queryset(
            Attendance.objects.filter(user=obj.user, attendance_type='MEMBER'), obj
        )
        this_month = records.filter(date__gte=month_start).filter(status='PRESENT').count()
        total_present = records.filter(status='PRESENT').count()
        total_records = records.count()
        streak = 0
        check_date = today
        while True:
            if records.filter(date=check_date, status='PRESENT').exists():
                streak += 1
                check_date -= timezone.timedelta(days=1)
            else:
                break
        return {
            'this_month': this_month,
            'total_present': total_present,
            'total_records': total_records,
            'streak': streak,
        }

    def get_assigned_trainer(self, obj):
        from apps.trainers.models import TrainerMemberAssignment
        assignment = self._tenant_queryset(
            TrainerMemberAssignment.objects.filter(
                member=obj.user, is_active=True
            ), obj
        ).select_related('trainer').first()
        if not assignment:
            return None
        trainer = assignment.trainer
        from apps.trainers.models import TrainerProfile
        profile_qs = TrainerProfile._base_manager.filter(
            user=trainer,
            gym=assignment.gym,
        )
        profile_branch = getattr(self.context.get('request'), 'branch', None) or assignment.branch
        if profile_branch is not None:
            profile_qs = profile_qs.filter(
                Q(branch_id=profile_branch.id) | Q(branch__isnull=True)
            )
        profile = profile_qs.first()
        return {
            'id': trainer.id,
            'full_name': trainer.get_full_name(),
            'profile_picture': trainer.profile_picture.url if trainer.profile_picture else None,
            'specializations': profile.specializations if profile else [],
            'experience_years': profile.experience_years if profile else 0,
        }

    def get_active_workouts(self, obj):
        from apps.workouts.models import WorkoutAssignment
        assignments = self._tenant_queryset(
            WorkoutAssignment.objects.filter(
                member=obj.user, status='ACTIVE'
            ), obj
        ).select_related('template').order_by('-start_date')
        if not assignments.exists():
            return []
        return [{
            'id': a.id,
            'template_name': a.template.name,
            'goal': a.template.goal,
            'difficulty': a.template.difficulty,
            'completion_pct': a.completion_pct,
            'start_date': a.start_date,
            'end_date': a.end_date,
            'goal_note': a.goal_note,
        } for a in assignments]

    def get_active_diet_plan(self, obj):
        from apps.diet.models import DietPlan
        plan = self._tenant_queryset(
            DietPlan.objects.filter(member=obj.user, is_active=True), obj
        ).first()
        if not plan:
            return None
        meals = plan.meals.all().order_by('time_suggestion')
        return {
            'id': plan.id,
            'name': plan.name,
            'goal': plan.goal,
            'daily_calories': plan.daily_calories,
            'protein_g': plan.protein_g,
            'carbs_g': plan.carbs_g,
            'fats_g': plan.fats_g,
            'meal_count': meals.count(),
        }

    def get_latest_progress(self, obj):
        from apps.progress.models import ProgressEntry
        entry = self._tenant_queryset(
            ProgressEntry.objects.filter(member=obj.user), obj
        ).order_by('-date').first()
        if not entry:
            return None
        return {
            'id': entry.id,
            'date': entry.date,
            'weight_kg': str(entry.weight_kg) if entry.weight_kg else None,
            'body_fat_percentage': str(entry.body_fat_percentage) if entry.body_fat_percentage else None,
            'muscle_mass_kg': str(entry.muscle_mass_kg) if entry.muscle_mass_kg else None,
            'bmi': entry.bmi,
        }

    def get_personal_records(self, obj):
        from apps.progress.models import PersonalRecord
        records = self._tenant_queryset(
            PersonalRecord.objects.filter(member=obj.user), obj
        ).select_related('exercise').order_by('-date')[:5]
        return [{
            'id': pr.id,
            'exercise_name': pr.exercise.name,
            'value': str(pr.value),
            'unit': pr.unit,
            'date': pr.date,
        } for pr in records]

    def get_recent_payments(self, obj):
        from apps.payments.models import Payment
        payments = self._tenant_queryset(
            Payment.objects.filter(member=obj.user), obj
        ).select_related('membership', 'membership__plan').order_by('-paid_at')[:5]
        return [{
            'id': p.id,
            'amount': str(p.amount),
            'discount': str(p.discount),
            'amount_paid': str(p.amount_paid),
            'payment_method': p.payment_method,
            'status': p.status,
            'payment_for': p.payment_for,
            'plan_name': p.membership.plan.name if p.membership and p.membership.plan else None,
            'paid_at': p.paid_at,
            'receipt_number': p.receipt_number,
        } for p in payments]

    def get_payment_dues(self, obj):
        from decimal import Decimal
        from apps.memberships.models import Membership
        from apps.lockers.models import LockerAssignment

        dues = []

        pending_memberships = self._tenant_queryset(
            Membership.objects.filter(
                member=obj.user, status=Membership.Status.PENDING
            ), obj
        ).select_related('plan').order_by('-created_at')
        for pm in pending_memberships:
            outstanding = pm.plan.price - (pm.price_paid or Decimal('0'))
            if outstanding > 0:
                dues.append({
                    'payment_for': 'MEMBERSHIP',
                    'reference_id': pm.id,
                    'label': f'{pm.plan.name} Membership',
                    'amount': float(outstanding),
                })

        active_locker = self._tenant_queryset(
            LockerAssignment.objects.filter(
                member=obj.user, is_active=True
            ), obj
        ).select_related('locker').first()
        if active_locker and active_locker.locker.monthly_fee > 0:
            from apps.payments.models import Payment
            now = timezone.now()
            has_paid = self._tenant_queryset(
                Payment.objects.filter(
                    member=obj.user,
                    payment_for='LOCKER',
                    status='PAID',
                    created_at__year=now.year,
                    created_at__month=now.month,
                ), obj
            ).exists()
            if not has_paid:
                dues.append({
                    'payment_for': 'LOCKER',
                    'reference_id': active_locker.id,
                    'label': f'Locker {active_locker.locker.locker_number} Fee',
                    'amount': float(active_locker.locker.monthly_fee),
                })

        return dues