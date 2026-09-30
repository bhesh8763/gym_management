from rest_framework import serializers

from apps.gyms.tenancy import user_has_branch_access

from .models import Locker, LockerAssignment


class LockerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Locker
        fields = [
            'id', 'gym', 'branch', 'locker_number', 'location', 'status',
            'monthly_fee', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'created_at', 'updated_at']

    def validate(self, data):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        branch = getattr(request, 'branch', None) if request else None
        number = data.get('locker_number', getattr(self.instance, 'locker_number', None))
        if number:
            lookup = {'locker_number': number}
            lookup['gym_id'] = gym.id if gym is not None else None
            lookup['branch_id'] = branch.id if branch is not None else None
            # A soft-deleted locker still holds the unique (gym, branch,
            # number) slot — checking the live manager only would 500 on the
            # DB constraint instead of returning a friendly 400.
            queryset = Locker._base_manager.filter(**lookup)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError({'locker_number': 'This locker number is already in use.'})
        return data

    def validate_status(self, value):
        if value == Locker.LockerStatus.OCCUPIED and self.instance and self.instance.status != Locker.LockerStatus.OCCUPIED:
            raise serializers.ValidationError(
                'Cannot set status to OCCUPIED directly. '
                'Create a locker assignment instead.'
            )
        return value


class LockerAssignmentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    locker_number = serializers.CharField(source='locker.locker_number', read_only=True)
    locker_location = serializers.CharField(source='locker.location', read_only=True)
    monthly_fee = serializers.DecimalField(source='locker.monthly_fee', max_digits=8, decimal_places=2, read_only=True)
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name', read_only=True)

    class Meta:
        model = LockerAssignment
        fields = [
            'id', 'gym', 'branch', 'locker', 'locker_number', 'locker_location', 'monthly_fee',
            'member', 'member_name',
            'start_date', 'end_date', 'is_active',
            'assigned_by', 'assigned_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'assigned_by', 'created_at']

    def validate(self, data):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        member = data.get('member', getattr(self.instance, 'member', None))
        locker = data.get('locker', getattr(self.instance, 'locker', None))
        if gym is not None:
            from apps.gyms.models import GymMembership
            if member and not GymMembership.objects.filter(
                gym=gym, user=member, role=GymMembership.Role.MEMBER,
                status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError({'member': 'Member is not active in this gym.'})
            if member and not user_has_branch_access(member, gym, getattr(request, 'branch', None)):
                raise serializers.ValidationError({'member': 'Member does not have access to this branch.'})
            if locker and locker.gym_id != gym.id:
                raise serializers.ValidationError({'locker': 'Locker does not belong to this gym.'})
            branch = getattr(request, 'branch', None) if request else None
            if branch is not None and locker and locker.branch_id not in (None, branch.id):
                raise serializers.ValidationError({'locker': 'Locker does not belong to this branch.'})
        return data