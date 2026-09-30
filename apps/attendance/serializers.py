from rest_framework import serializers
from django.utils import timezone

from apps.gyms.tenancy import user_has_branch_access

from .models import Attendance, QRAttendanceToken, BiometricRecord


class AttendanceSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    marked_by_name = serializers.CharField(source='marked_by.get_full_name', read_only=True)
    duration_minutes = serializers.ReadOnlyField()
    membership = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = [
            'id', 'gym', 'branch', 'user', 'user_name', 'attendance_type', 'date',
            'status', 'check_in', 'check_out', 'duration_minutes',
            'membership', 'marked_by', 'marked_by_name', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'created_at', 'marked_by']

    def validate(self, attrs):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        user = attrs.get('user', getattr(self.instance, 'user', None))
        date = attrs.get('date', getattr(self.instance, 'date', None))
        if gym is not None and user is not None:
            from apps.gyms.models import GymMembership
            if not GymMembership.objects.filter(
                gym=gym,
                user=user,
                role__in=[
                    GymMembership.Role.MEMBER,
                    GymMembership.Role.STAFF,
                    GymMembership.Role.TRAINER,
                ],
                status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError({'user': 'User is not active in this gym.'})
            if not user_has_branch_access(user, gym, getattr(request, 'branch', None)):
                raise serializers.ValidationError({'user': 'User does not have access to this branch.'})
        if user and date:
            lookup = {
                'user': user,
                'date': date,
                'gym_id': gym.id if gym is not None else getattr(self.instance, 'gym_id', None),
            }
            queryset = Attendance._base_manager.filter(**lookup)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError('Attendance already exists for this member, gym, and date.')
        return attrs

    def get_membership(self, obj):
        # Use the prefetched list from the viewset when available (avoids
        # one query per row); fall back to a direct query otherwise.
        memberships = getattr(obj.user, 'prefetched_active_memberships', None)
        if memberships is None:
            memberships = obj.user.memberships.filter(
                gym_id=obj.gym_id,
                status='ACTIVE', end_date__gte=timezone.now().date()
            )
        else:
            today = timezone.now().date()
            memberships = [m for m in memberships if m.end_date and m.end_date >= today]
        request = self.context.get('request')
        profile_gym_id = getattr(obj, 'gym_id', None) or getattr(request, 'gym_id', None)
        memberships = [m for m in memberships if m.gym_id == profile_gym_id]
        membership = max(memberships, key=lambda m: m.start_date, default=None)
        return membership.plan.name if membership else None


class QRTokenSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    qr_token_preview = serializers.SerializerMethodField()

    class Meta:
        model = QRAttendanceToken
        fields = [
            'id', 'gym', 'branch', 'member', 'member_name', 'qr_token_preview', 'created_at', 'updated_at'
        ]
        read_only_fields = ['gym', 'branch', 'qr_token', 'created_at', 'updated_at']

    def get_qr_token_preview(self, obj):
        return obj.token[:8] + '...' + obj.token[-4:]


class BiometricRecordSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)

    class Meta:
        model = BiometricRecord
        fields = [
            'id', 'gym', 'branch', 'member', 'member_name',
            'biometric_type', 'biometric_id', 'device_id',
            'status', 'enrolled_by', 'enrolled_at',
            'last_verified_at', 'last_verified_device', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'created_at', 'updated_at']

    def validate(self, data):
        if data.get('status') == BiometricRecord.BiometricStatus.FAILED and not data.get('notes'):
            raise serializers.ValidationError({'notes': 'Notes are required when marking enrollment as failed.'})
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        member = data.get('member', getattr(self.instance, 'member', None))
        if gym is not None and member is not None:
            from apps.gyms.models import GymMembership
            if not GymMembership.objects.filter(
                gym=gym, user=member, role=GymMembership.Role.MEMBER,
                status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError({'member': 'Member is not active in this gym.'})
            if not user_has_branch_access(member, gym, getattr(request, 'branch', None)):
                raise serializers.ValidationError({'member': 'Member does not have access to this branch.'})
            duplicate = BiometricRecord._base_manager.filter(gym=gym, member=member)
            if self.instance:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError({'member': 'This member already has a biometric enrollment in this gym.'})
        return data


class BiometricAttendanceSerializer(serializers.Serializer):
    """Serializer for biometric scanner check-in requests."""
    biometric_id = serializers.CharField(max_length=128)
    gym_id = serializers.IntegerField(required=False)
    device_id = serializers.CharField(max_length=50, required=False)
    biometric_type = serializers.CharField(max_length=15, required=False)
    timestamp = serializers.DateTimeField(required=False)

    def validate_biometric_id(self, value):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        lookup = {
            'biometric_id': value,
            'status': BiometricRecord.BiometricStatus.ENROLLED,
        }
        if gym is not None:
            lookup['gym_id'] = gym.id
        else:
            supplied_gym_id = self.initial_data.get('gym_id')
            if supplied_gym_id:
                try:
                    lookup['gym_id'] = int(supplied_gym_id)
                except (TypeError, ValueError):
                    raise serializers.ValidationError({'gym_id': 'Enter a valid gym ID.'})
        try:
            record = BiometricRecord.objects.select_related('member', 'gym').get(**lookup)
        except BiometricRecord.DoesNotExist:
            raise serializers.ValidationError('No registered member found with this biometric ID.')
        except BiometricRecord.MultipleObjectsReturned:
            raise serializers.ValidationError('gym_id is required for this biometric ID.')
        if record.branch_id:
            from apps.gyms.models import GymMembership
            if not GymMembership.objects.filter(
                gym=record.gym,
                user=record.member,
                branch_memberships__branch=record.branch,
            ).exists():
                raise serializers.ValidationError('Member is not active in this branch.')
        self.context['biometric_record'] = record
        return value