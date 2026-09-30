from django.contrib import admin
from .models import MemberProfile


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'gender', 'fitness_goal', 'fitness_level', 'bmi', 'created_at')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    list_filter = ('gender', 'fitness_goal', 'fitness_level')
    readonly_fields = ('created_at', 'updated_at')
