"""
Serializers for the Memberships app.

Covers membership plans, and the member membership lifecycle:
create/assign, freeze, unfreeze, renew, and cancel.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.memberships.models import Membership, MembershipPlan

User = get_user_model()


# ─── Plans ──────────────────────────────────────────────────────────────────

class MembershipPlanSerializer(serializers.ModelSerializer):
    billing_cycle_display = serializers.CharField(
        source='get_billing_cycle_display', read_only=True
    )

    class Meta:
        model = MembershipPlan
        fields = [
            'id', 'name', 'description', 'billing_cycle', 'billing_cycle_display',
            'duration_days', 'price', 'features', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ─── Memberships: read ────────────────────────────────────────────────────────

class MembershipListSerializer(serializers.ModelSerializer):
    """Compact serializer used for the membership list."""
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    member_email = serializers.EmailField(source='member.email', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)

    class Meta:
        model = Membership
        fields = [
            'id', 'member', 'member_name', 'member_email',
            'plan', 'plan_name', 'status', 'status_display',
            'start_date', 'end_date', 'price_paid',
            'is_active', 'days_remaining',
            'freeze_start', 'freeze_end',
            'created_at',
        ]


class MembershipDetailSerializer(MembershipListSerializer):
    """Full serializer — adds freeze reason, notes, renewal chain."""

    class Meta(MembershipListSerializer.Meta):
        fields = MembershipListSerializer.Meta.fields + [
            'freeze_reason', 'renewed_from', 'notes', 'updated_at',
        ]


# ─── Memberships: create / assign ─────────────────────────────────────────────

class MembershipCreateSerializer(serializers.ModelSerializer):
    """
    Used by Owner/Staff to assign a plan to a member.

    end_date is always computed from plan.duration_days — it is never
    accepted directly, so a membership can't accidentally be created with
    a mismatched date range.
    """

    class Meta:
        model = Membership
        fields = ['id', 'member', 'plan', 'start_date', 'price_paid', 'notes', 'status']
        extra_kwargs = {
            'start_date': {'required': False},
            'price_paid': {'required': False},
            'status': {'required': False},
            'notes': {'required': False},
        }

    def validate_member(self, value):
        if value.role != User.Role.MEMBER:
            raise serializers.ValidationError('Selected user is not a member.')
        return value

    def validate_plan(self, value):
        if not value.is_active:
            raise serializers.ValidationError('This plan is no longer active.')
        return value

    def validate(self, data):
        member = data.get('member')
        # Only block brand-new ACTIVE assignments; an explicit PENDING/CANCELLED
        # status, etc. is fine even if the member currently has an active plan.
        requested_status = data.get('status', Membership.Status.ACTIVE)
        if member and requested_status == Membership.Status.ACTIVE:
            today = timezone.now().date()
            has_active = Membership.objects.filter(
                member=member,
                status=Membership.Status.ACTIVE,
                end_date__gte=today,
            ).exists()
            if has_active:
                raise serializers.ValidationError(
                    {'member': 'This member already has an active membership. '
                               'Freeze, cancel, or renew the existing membership before assigning a new plan.'}
                )
        return data

    def create(self, validated_data):
        plan = validated_data['plan']
        start_date = validated_data.get('start_date') or timezone.now().date()
        end_date = start_date + timedelta(days=plan.duration_days)
        price_paid = validated_data.get('price_paid', plan.price)
        status = validated_data.get('status', Membership.Status.ACTIVE)

        return Membership.objects.create(
            member=validated_data['member'],
            plan=plan,
            status=status,
            start_date=start_date,
            end_date=end_date,
            price_paid=price_paid,
            notes=validated_data.get('notes', ''),
        )


# ─── Actions ──────────────────────────────────────────────────────────────────

class FreezeSerializer(serializers.Serializer):
    freeze_start = serializers.DateField()
    freeze_end = serializers.DateField()
    freeze_reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data['freeze_end'] < data['freeze_start']:
            raise serializers.ValidationError('freeze_end must be on or after freeze_start.')
        return data


class RenewSerializer(serializers.Serializer):
    start_date = serializers.DateField(required=False)
    price_paid = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
