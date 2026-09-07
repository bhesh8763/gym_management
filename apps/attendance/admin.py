from django.contrib import admin
from .models import Attendance, QRAttendanceToken, BiometricRecord


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'attendance_type', 'date', 'check_in', 'check_out', 'marked_by')
    list_filter = ('attendance_type', 'date')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    date_hierarchy = 'date'


@admin.register(QRAttendanceToken)
class QRAttendanceTokenAdmin(admin.ModelAdmin):
    list_display = ('member', 'token_preview', 'created_at', 'updated_at')
    search_fields = ('member__email', 'member__first_name', 'member__last_name', 'token')
    readonly_fields = ('token', 'created_at', 'updated_at')

    @admin.display(description='Token')
    def token_preview(self, obj):
        return obj.token[:12] + '...'


@admin.register(BiometricRecord)
class BiometricRecordAdmin(admin.ModelAdmin):
    list_display = ('member', 'biometric_type', 'biometric_id_preview', 'device_id', 'status', 'last_verified_at')
    list_filter = ('biometric_type', 'status')
    search_fields = ('member__email', 'member__first_name', 'member__last_name', 'device_id')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Biometric ID')
    def biometric_id_preview(self, obj):
        val = str(obj.biometric_id)
        return val[:20] + ('...' if len(val) > 20 else '')
