from django.contrib import admin
from .models import Locker, LockerAssignment


@admin.register(Locker)
class LockerAdmin(admin.ModelAdmin):
    list_display = ('locker_number', 'location', 'status', 'monthly_fee')
    list_filter = ('status', 'location')
    search_fields = ('locker_number',)


@admin.register(LockerAssignment)
class LockerAssignmentAdmin(admin.ModelAdmin):
    list_display = ('locker', 'member', 'start_date', 'end_date', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('member__email', 'locker__locker_number')
