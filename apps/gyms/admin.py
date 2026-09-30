from django.contrib import admin

from .models import AuditLog, Branch, BranchMembership, Gym, GymMembership, ImpersonationSession, Invitation


@admin.register(Gym)
class GymAdmin(admin.ModelAdmin):
    list_display = ('public_id', 'name', 'owner', 'status', 'onboarding_complete')
    search_fields = ('public_id', 'name', 'owner__email')
    list_filter = ('status', 'onboarding_complete')


@admin.register(GymMembership)
class GymMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'gym', 'role', 'status', 'membership_number', 'is_default')
    search_fields = ('user__email', 'gym__name', 'membership_number')
    list_filter = ('gym', 'role', 'status')


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('gym', 'name', 'code', 'status', 'is_primary')
    list_filter = ('gym', 'status', 'is_primary')


@admin.register(BranchMembership)
class BranchMembershipAdmin(admin.ModelAdmin):
    list_display = ('gym_membership', 'branch', 'can_manage')
    list_filter = ('branch__gym', 'can_manage')


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'gym', 'role', 'status', 'expires_at', 'created_at')
    search_fields = ('email', 'gym__name')
    list_filter = ('gym', 'role', 'status')


@admin.register(ImpersonationSession)
class ImpersonationSessionAdmin(admin.ModelAdmin):
    list_display = ('actor', 'subject', 'gym', 'reason', 'expires_at', 'ended_at')
    search_fields = ('actor__email', 'subject__email', 'reason')
    list_filter = ('gym',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'gym', 'actor', 'target_type', 'target_id', 'created_at')
    search_fields = ('action', 'actor__email', 'target_id')
    list_filter = ('gym', 'action')
