from django.contrib import admin
from .models import Equipment, MaintenanceRecord


class MaintenanceInline(admin.TabularInline):
    model = MaintenanceRecord
    extra = 0


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'brand', 'quantity', 'condition', 'location')
    list_filter = ('condition', 'category')
    search_fields = ('name', 'serial_number', 'brand')
    inlines = [MaintenanceInline]


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ('equipment', 'maintenance_type', 'status', 'scheduled_date', 'cost')
    list_filter = ('status', 'maintenance_type')
    date_hierarchy = 'scheduled_date'
