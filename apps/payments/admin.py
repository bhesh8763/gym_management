from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'member', 'amount_paid', 'payment_method', 'status', 'paid_at')
    list_filter = ('status', 'payment_method', 'payment_for')
    search_fields = ('member__email', 'receipt_number', 'transaction_id')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
