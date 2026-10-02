from django.contrib import admin
from .models import StaffProfile, LeaveRequest, Shift, StaffShift


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'joined_date', 'salary')
    list_filter = ('role',)
    search_fields = ('user__email', 'user__first_name', 'user__last_name')


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('requester', 'leave_type', 'start_date', 'end_date', 'status', 'reviewed_by')
    list_filter = ('status', 'leave_type')
    search_fields = ('requester__email', 'requester__first_name')


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(StaffShift)
class StaffShiftAdmin(admin.ModelAdmin):
    list_display = ('staff', 'shift', 'weekday', 'created_at')
    list_filter = ('weekday', 'shift')
    search_fields = ('staff__email', 'staff__first_name', 'staff__last_name')
