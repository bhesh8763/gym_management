from django.contrib import admin
from .models import StaffProfile, LeaveRequest


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'department', 'designation', 'joined_date', 'salary')
    list_filter = ('department',)
    search_fields = ('user__email', 'user__first_name', 'user__last_name')


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('requester', 'leave_type', 'start_date', 'end_date', 'status', 'reviewed_by')
    list_filter = ('status', 'leave_type')
    search_fields = ('requester__email', 'requester__first_name')
