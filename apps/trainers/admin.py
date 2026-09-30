from django.contrib import admin
from .models import TrainerProfile, TrainerMemberAssignment


@admin.register(TrainerProfile)
class TrainerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'experience_years', 'is_available', 'joined_date')
    list_filter = ('is_available',)
    search_fields = ('user__email', 'user__first_name', 'user__last_name')


@admin.register(TrainerMemberAssignment)
class TrainerMemberAssignmentAdmin(admin.ModelAdmin):
    list_display = ('trainer', 'member', 'assigned_date', 'is_active')
    list_filter = ('is_active',)
