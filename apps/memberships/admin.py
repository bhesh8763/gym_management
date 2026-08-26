from django.contrib import admin
from .models import FreezeRequest, MembershipPlan, Membership


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'billing_cycle', 'duration_days', 'price', 'is_active')
    list_filter = ('billing_cycle', 'is_active')
    search_fields = ('name',)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('member', 'plan', 'status', 'start_date', 'end_date', 'price_paid')
    list_filter = ('status', 'plan')
    search_fields = ('member__email', 'member__first_name', 'member__last_name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FreezeRequest)
class FreezeRequestAdmin(admin.ModelAdmin):
    list_display = ('requested_by', 'membership', 'status', 'freeze_start', 'freeze_end', 'created_at')
    list_filter = ('status',)
    search_fields = ('requested_by__email', 'requested_by__first_name', 'requested_by__last_name')
