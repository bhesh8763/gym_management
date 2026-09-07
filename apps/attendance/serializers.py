from rest_framework import serializers
from django.utils import timezone
from .models import Attendance, QRAttendanceToken, BiometricRecord


class AttendanceSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    marked_by_name = serializers.CharField(source='marked_by.get_full_name', read_only=True)
    duration_minutes = serializers.ReadOnlyField()
    membership = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = [
            'id', 'user', 'user_name', 'attendance_type', 'date',
            'status', 'check_in', 'check_out', 'duration_minutes',
            'membership', 'marked_by', 'marked_by_name', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'marked_by']

    def get_membership(self, obj):
        # Use the prefetched list from the viewset when available (avoids
        # one query per row); fall back to a direct query otherwise.
        memberships = getattr(obj.user, 'prefetched_active_memberships', None)
        if memberships is None:
            memberships = obj.user.memberships.filter(
                status='ACTIVE', end_date__gte=timezone.now().date()
            )
        else:
            today = timezone.now().date()
            memberships = [m for m in memberships if m.end_date and m.end_date >= today]
        membership = max(memberships, key=lambda m: m.start_date, default=None)
        return membership.plan.name if membership else None


class QRTokenSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    qr_token_preview = serializers.SerializerMethodField()

    class Meta:
        model = QRAttendanceToken
        fields = [
            'id', 'member', 'member_name', 'qr_token_preview', 'created_at', 'updated_at'
        ]
        read_only_fields = ['qr_token', 'created_at', 'updated_at']

    def get_qr_token_preview(self, obj):
        return obj.token[:8] + '...' + obj.token[-4:]


class BiometricRecordSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)

    class Meta:
        model = BiometricRecord
        fields = [
            'id', 'member', 'member_name',
            'biometric_type', 'biometric_id', 'device_id',
            'status', 'enrolled_by', 'enrolled_at',
            'last_verified_at', 'last_verified_device', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        if data.get('status') == BiometricRecord.BiometricStatus.FAILED and not data.get('notes'):
            raise serializers.ValidationError({'notes': 'Notes are required when marking enrollment as failed.'})
        return data


class BiometricAttendanceSerializer(serializers.Serializer):
    """Serializer for biometric scanner check-in requests."""
    biometric_id = serializers.CharField(max_length=128)
    device_id = serializers.CharField(max_length=50, required=False)
    biometric_type = serializers.CharField(max_length=15, required=False)
    timestamp = serializers.DateTimeField(required=False)

    def validate_biometric_id(self, value):
        try:
            record = BiometricRecord.objects.select_related('member').get(
                biometric_id=value,
                status=BiometricRecord.BiometricStatus.ENROLLED,
            )
        except BiometricRecord.DoesNotExist:
            raise serializers.ValidationError('No registered member found with this biometric ID.')
        self.context['biometric_record'] = record
        return value