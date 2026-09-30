from django.contrib import admin
from .models import ProgressEntry, PersonalRecord


@admin.register(ProgressEntry)
class ProgressEntryAdmin(admin.ModelAdmin):
    list_display = ('member', 'date', 'weight_kg', 'body_fat_percentage', 'bmi')
    search_fields = ('member__email', 'member__first_name')
    date_hierarchy = 'date'


@admin.register(PersonalRecord)
class PersonalRecordAdmin(admin.ModelAdmin):
    list_display = ('member', 'exercise', 'value', 'unit', 'date')
    search_fields = ('member__email', 'exercise__name')
    list_filter = ('exercise',)
