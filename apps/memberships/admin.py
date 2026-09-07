from django.contrib import admin
from .models import FreezeRequest, MembershipPlan, Membership, Offer, PromoCode, PromoCodeUsage


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


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount_type', 'discount_value', 'applicability', 'is_active', 'valid_from', 'valid_until')
    list_filter = ('discount_type', 'applicability', 'is_active')
    search_fields = ('name',)
    filter_horizontal = ('plans',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'offer', 'status', 'used_count', 'max_uses', 'valid_from', 'valid_until')
    list_filter = ('status', 'offer')
    search_fields = ('code',)
    readonly_fields = ('used_count', 'created_at', 'updated_at')


@admin.register(PromoCodeUsage)
class PromoCodeUsageAdmin(admin.ModelAdmin):
    list_display = ('promo_code', 'member', 'original_price', 'discount_applied', 'final_price', 'used_at')
    search_fields = ('promo_code__code', 'member__email', 'member__first_name')
    readonly_fields = ('used_at',)
