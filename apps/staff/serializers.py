from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from apps.gyms.tenancy import user_has_branch_access

from .models import StaffProfile, LeaveRequest, Shift, StaffShift

User = get_user_model()


class StaffProfileSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_display_id = serializers.CharField(source='user.display_id', read_only=True)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)
    user_phone = serializers.CharField(source='user.phone', read_only=True)
    profile_picture_url = serializers.SerializerMethodField()
    shifts_summary = serializers.SerializerMethodField()

    class Meta:
        model = StaffProfile
        fields = [
            'id', 'gym', 'branch', 'user', 'user_name', 'user_email', 'user_display_id', 'is_active',
            'user_phone', 'role', 'date_of_birth', 'gender', 'marital_status', 'nationality',
            'joined_date', 'salary', 'id_document',
            'notes', 'created_at', 'updated_at', 'profile_picture_url', 'shifts_summary',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'created_at', 'updated_at']

    def get_profile_picture_url(self, obj):
        if not obj.user.profile_picture:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.user.profile_picture.url)
        return obj.user.profile_picture.url

    def get_shifts_summary(self, obj):
        """Compact weekly summary, e.g. "Mon-Fri: Morning, Night; Sat: Evening"."""
        rows = StaffShift.objects.filter(staff=obj.user).order_by(
            'weekday', 'shift__start_time', 'shift__name'
        ).select_related('shift')
        names_by_day = {}
        for row in rows:
            names_by_day.setdefault(row.weekday, []).append(row.shift.name)
        if not names_by_day:
            return None
        labels = {day: ', '.join(names) for day, names in names_by_day.items()}
        parts = []
        day = 0
        while day <= 6:
            if day not in labels:
                day += 1
                continue
            label = labels[day]
            end = day
            while end < 6 and labels.get(end + 1) == label:
                end += 1
            start_abbr = StaffShift.Weekday(day).label[:3]
            span = start_abbr if end == day else f'{start_abbr}-{StaffShift.Weekday(end).label[:3]}'
            parts.append(f'{span}: {label}')
            day = end + 1
        return '; '.join(parts)

    def validate_user(self, value):
        if self.instance and value != self.instance.user:
            raise serializers.ValidationError('The profile user cannot be changed.')
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        # Include soft-deleted profiles: the DB unique (gym, user) slot is
        # still taken, so report it as a duplicate rather than 500-ing.
        duplicate = StaffProfile._base_manager.filter(user=value, gym=gym)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError('This user already has a staff profile in this gym.')
        gym = getattr(request, 'gym', None) if request else None
        if gym is not None:
            from apps.gyms.models import GymMembership
            if not GymMembership.objects.filter(
                gym=gym,
                user=value,
                role__in=[GymMembership.Role.STAFF, GymMembership.Role.TRAINER],
                status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError(
                    'User is not an active staff or trainer member of this gym.'
                )
            if not user_has_branch_access(value, gym, getattr(request, 'branch', None)):
                raise serializers.ValidationError('User does not have access to this branch.')
        elif value.role not in [User.Role.STAFF, User.Role.TRAINER]:
            raise serializers.ValidationError(
                'Staff profiles can only be created for users with the STAFF or TRAINER role.'
            )
        return value


class StaffCreateSerializer(serializers.Serializer):
    """
    Used by Owner to create a new Staff user + profile in one request
    (mirrors apps.members.serializers.MemberCreateSerializer).

    Required user fields:  email, first_name, last_name, password
    Optional user fields:  phone
    Optional profile fields: role, date_of_birth, gender, marital_status, nationality, joined_date, salary, notes
    """
    # User fields
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )

    # Profile fields
    role = serializers.ChoiceField(
        choices=StaffProfile.Role.choices, required=False,
        default=StaffProfile.Role.RECEPTIONIST,
    )
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(max_length=1, required=False, allow_blank=True)
    marital_status = serializers.CharField(max_length=15, required=False, allow_blank=True)
    nationality = serializers.CharField(max_length=100, required=False, allow_blank=True)
    joined_date = serializers.DateField(required=False, allow_null=True)
    salary = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=Decimal('0'),
    )
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_phone(self, value):
        if value and (not value.isdigit() or len(value) != 10):
            raise serializers.ValidationError(
                'Phone number must be exactly 10 digits.'
            )
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value
    
    def create(self, validated_data):
      user_fields = ['email', 'first_name', 'middle_name', 'last_name', 'phone', 'password']
      user_data = {k: validated_data.pop(k) for k in user_fields if k in validated_data}
      password = user_data.pop('password')

      staff_profile_role = validated_data.get('role', StaffProfile.Role.RECEPTIONIST)
      user_role = User.Role.TRAINER if staff_profile_role == StaffProfile.Role.TRAINER else User.Role.STAFF

      user = User(role=user_role, **user_data)
      user.set_password(password)
      user.save()

      request = self.context.get('request')
      gym = validated_data.pop('gym', getattr(request, 'gym', None))
      branch = validated_data.pop('branch', getattr(request, 'branch', None))
      from apps.gyms.models import GymMembership
      if gym is not None:
        membership, _ = GymMembership.objects.get_or_create(
          user=user,
          gym=gym,
          defaults={
              'role': user_role,
              'status': GymMembership.Status.ACTIVE,
              'is_default': True,
          },
        )
        from apps.gyms.services import primary_branch
        branch = getattr(request, 'branch', None) or primary_branch(gym)
        if branch:
            membership.branch_memberships.get_or_create(branch=branch)

      staff_profile = StaffProfile.objects.create(
          user=user,
          gym=gym,
          branch=branch if gym is not None else None,
          **validated_data,
      )

      if user_role == User.Role.TRAINER:
        from apps.trainers.models import TrainerProfile
        TrainerProfile.objects.create(
            user=user,
            gym=gym,
            branch=branch if gym is not None else None,
        )

      return staff_profile
class LeaveRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.CharField(source='requester.get_full_name', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True)
    duration_days = serializers.ReadOnlyField()

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'gym', 'branch', 'requester', 'requester_name', 'leave_type',
            'start_date', 'end_date', 'duration_days', 'reason', 'status',
            'reviewed_by', 'reviewed_by_name', 'review_note', 'created_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'requester', 'status', 'reviewed_by', 'created_at']

    def validate_start_date(self, value):
        # On create, start_date must not be in the past.
        # On update (PATCH), allow keeping an existing past start_date unchanged.
        if self.instance is None and value < timezone.now().date():
            raise serializers.ValidationError('Start date cannot be in the past.')
        if self.instance is not None and value != self.instance.start_date and value < timezone.now().date():
            raise serializers.ValidationError('Start date cannot be changed to a past date.')
        return value

    def validate(self, data):
        start_date = data.get('start_date', getattr(self.instance, 'start_date', None))
        end_date = data.get('end_date', getattr(self.instance, 'end_date', None))
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {'end_date': 'End date cannot be before start date.'}
            )

        # Prevent overlapping leave requests for the same user.
        # Overlapping means: existing.start_date <= new.end_date AND existing.end_date >= new.start_date
        # Only count PENDING and APPROVED leaves as "occupied" — REJECTED and CANCELLED are free.
        if start_date and end_date:
            requester = (
                self.instance.requester
                if self.instance
                else self.context['request'].user
            )
            qs = LeaveRequest.objects.filter(
                requester=requester,
                status__in=['PENDING', 'APPROVED'],
                start_date__lte=end_date,
                end_date__gte=start_date,
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                conflict = qs.first()
                raise serializers.ValidationError(
                    f'These dates overlap with an existing {conflict.status.lower()} '
                    f'leave request ({conflict.start_date} – {conflict.end_date}).'
                )

        return data


class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shift
        fields = [
            'id', 'name', 'start_time', 'end_time', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        start_time = data.get('start_time', getattr(self.instance, 'start_time', None))
        end_time = data.get('end_time', getattr(self.instance, 'end_time', None))
        if start_time and end_time and end_time <= start_time:
            raise serializers.ValidationError(
                {'end_time': 'End time must be after start time.'}
            )
        return data


class StaffShiftSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.get_full_name', read_only=True)
    staff_display_id = serializers.CharField(source='staff.display_id', read_only=True)
    shift_name = serializers.CharField(source='shift.name', read_only=True)
    shift_start = serializers.TimeField(source='shift.start_time', read_only=True)
    shift_end = serializers.TimeField(source='shift.end_time', read_only=True)
    weekday_display = serializers.CharField(source='get_weekday_display', read_only=True)

    class Meta:
        model = StaffShift
        fields = [
            'id', 'staff', 'staff_name', 'staff_display_id',
            'shift', 'shift_name', 'shift_start', 'shift_end',
            'weekday', 'weekday_display', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate_staff(self, value):
        if value.role not in (User.Role.STAFF, User.Role.TRAINER):
            raise serializers.ValidationError(
                'Only users with the STAFF or TRAINER role can be scheduled.'
            )
        return value

    def validate(self, data):
        staff = data.get('staff', getattr(self.instance, 'staff', None))
        shift = data.get('shift', getattr(self.instance, 'shift', None))
        weekday = data.get('weekday', getattr(self.instance, 'weekday', None))
        if staff is not None and shift is not None and weekday is not None:
            # Overlap: existing.start < new.end AND existing.end > new.start.
            # Back-to-back shifts (e.g. 05-10 and 10-16) do not overlap.
            conflicts = StaffShift.objects.filter(
                staff=staff,
                weekday=weekday,
                shift__start_time__lt=shift.end_time,
                shift__end_time__gt=shift.start_time,
            ).select_related('shift')
            if self.instance:
                conflicts = conflicts.exclude(pk=self.instance.pk)
            conflict = conflicts.first()
            if conflict:
                raise serializers.ValidationError(
                    f'Overlaps with existing {conflict.get_weekday_display()} shift '
                    f'"{conflict.shift.name}" '
                    f'({conflict.shift.start_time:%H:%M}–{conflict.shift.end_time:%H:%M}).'
                )
        return data


class BulkAssignmentDaySerializer(serializers.Serializer):
    """One weekday entry of a bulk-set payload: {weekday, shift_ids}."""

    weekday = serializers.ChoiceField(choices=StaffShift.Weekday.choices)
    shift_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True,
    )

    def validate_shift_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError('Duplicate shift ids in the same day.')
        found = set(Shift.objects.filter(pk__in=value).values_list('id', flat=True))
        missing = sorted(set(value) - found)
        if missing:
            raise serializers.ValidationError(
                f'Unknown shift ids: {", ".join(str(m) for m in missing)}.'
            )
        return value


class BulkStaffShiftSerializer(serializers.Serializer):
    """POST /api/staff/schedules/bulk-set/ payload.

    {staff, assignments: [{weekday, shift_ids: [...]}]} — replaces the
    person's entire weekly schedule.
    """

    staff = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    assignments = BulkAssignmentDaySerializer(many=True)

    def validate_staff(self, value):
        if value.role not in (User.Role.STAFF, User.Role.TRAINER):
            raise serializers.ValidationError(
                'Only users with the STAFF or TRAINER role can be scheduled.'
            )
        return value

    def validate_assignments(self, value):
        weekdays = [entry['weekday'] for entry in value]
        if len(set(weekdays)) != len(weekdays):
            raise serializers.ValidationError(
                'Each weekday may appear only once.'
            )
        for entry in value:
            shifts = list(Shift.objects.filter(pk__in=entry['shift_ids']))
            for i, a in enumerate(shifts):
                for b in shifts[i + 1:]:
                    if a.start_time < b.end_time and b.start_time < a.end_time:
                        raise serializers.ValidationError(
                            f'Weekday {entry["weekday"]}: shifts "{a.name}" '
                            f'({a.start_time:%H:%M}–{a.end_time:%H:%M}) and "{b.name}" '
                            f'({b.start_time:%H:%M}–{b.end_time:%H:%M}) overlap.'
                        )
        return value