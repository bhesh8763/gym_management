from django.contrib import admin
from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'attendance_type', 'date', 'check_in', 'check_out', 'marked_by')
    list_filter = ('attendance_type', 'date')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    date_hierarchy = 'date'
