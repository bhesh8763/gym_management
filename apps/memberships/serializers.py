"""
Serializers for the Memberships app.

Covers membership plans, and the member membership lifecycle:
create/assign, freeze, unfreeze, renew, and cancel.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.memberships.models import FreezeRequest, Membership, MembershipPlan, Offer, PromoCode, PromoCodeUsage

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
    promo_code = serializers.CharField(max_length=50, required=False, write_only=True)

    class Meta:
        model = Membership
        fields = ['id', 'member', 'plan', 'start_date', 'price_paid', 'notes', 'status', 'promo_code']
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
        promo_code_str = validated_data.pop('promo_code', None)
        plan = validated_data['plan']
        start_date = validated_data.get('start_date') or timezone.now().date()
        end_date = start_date + timedelta(days=plan.duration_days)
        price_paid = validated_data.get('price_paid', plan.price)
        membership_status = validated_data.get('status', Membership.Status.PENDING)

        # Apply promo code discount if provided
        promo_code_obj = None
        if promo_code_str:
            try:
                promo_code_obj = PromoCode.objects.select_related('offer').get(
                    code=promo_code_str.upper().strip()
                )
                if promo_code_obj.is_valid and promo_code_obj.offer.applies_to_plan(plan):
                    discount = promo_code_obj.calculate_discount(price_paid)
                    price_paid = max(price_paid - discount, Decimal('0'))
                    # Record usage
                    PromoCodeUsage.objects.create(
                        promo_code=promo_code_obj,
                        member=validated_data['member'],
                        original_price=validated_data.get('price_paid', plan.price),
                        discount_applied=discount,
                        final_price=price_paid,
                    )
                    promo_code_obj.redeem()
            except PromoCode.DoesNotExist:
                pass  # Invalid promo code, proceed without discount

        return Membership.objects.create(
            member=validated_data['member'],
            plan=plan,
            status=membership_status,
            start_date=start_date,
            end_date=end_date,
            price_paid=price_paid,
            promo_code=promo_code_obj,
            notes=validated_data.get('notes', ''),
        )


# ─── Memberships: update (patch) ──────────────────────────────────────────────

class MembershipUpdateSerializer(serializers.ModelSerializer):
    """
    Used by Owner/Staff for direct PATCH edits (dates, price, notes, and a
    manual status override). Freeze/unfreeze/renew go through their own
    endpoints — this is the fallback for everything else, including forcing
    a status like CANCELLED → ACTIVE from the edit modal.
    """

    class Meta:
        model = Membership
        fields = ['notes', 'price_paid', 'end_date', 'status']
        extra_kwargs = {
            'notes': {'required': False},
            'price_paid': {'required': False},
            'end_date': {'required': False},
            'status': {'required': False},
        }


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


# ─── Freeze Requests ──────────────────────────────────────────────────────────

class FreezeRequestCreateSerializer(serializers.ModelSerializer):
    """Used by members to submit a freeze request."""

    class Meta:
        model = FreezeRequest
        fields = ['id', 'membership', 'freeze_start', 'freeze_end', 'reason']
        read_only_fields = ['id']

    def validate_membership(self, value):
        if value.status != Membership.Status.ACTIVE:
            raise serializers.ValidationError('Only active memberships can be frozen.')
        if value.member != self.context['request'].user:
            raise serializers.ValidationError('You can only request a freeze for your own membership.')
        return value

    def validate(self, data):
        if data['freeze_end'] < data['freeze_start']:
            raise serializers.ValidationError('freeze_end must be on or after freeze_start.')
        today = timezone.now().date()
        if data['freeze_start'] < today:
            raise serializers.ValidationError('freeze_start cannot be in the past.')
        # Check for pending request on same membership
        if FreezeRequest.objects.filter(
            membership=data['membership'],
            status=FreezeRequest.Status.PENDING,
        ).exists():
            raise serializers.ValidationError('You already have a pending freeze request for this membership.')
        return data


class FreezeRequestListSerializer(serializers.ModelSerializer):
    """Read serializer for freeze requests (staff view + member history)."""
    member_name = serializers.CharField(source='requested_by.get_full_name', read_only=True)
    member_email = serializers.EmailField(source='requested_by.email', read_only=True)
    plan_name = serializers.CharField(source='membership.plan.name', read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = FreezeRequest
        fields = [
            'id', 'membership', 'member_name', 'member_email', 'plan_name',
            'freeze_start', 'freeze_end', 'reason',
            'status', 'status_display',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'rejection_reason',
            'created_at',
        ]

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name()
        return None


# ─── Offers & Promo Codes ─────────────────────────────────────────────────────


class OfferSerializer(serializers.ModelSerializer):
    """CRUD serializer for Offers (Owner/Staff only)."""
    discount_type_display = serializers.CharField(source='get_discount_type_display', read_only=True)
    applicability_display = serializers.CharField(source='get_applicability_display', read_only=True)
    total_uses = serializers.IntegerField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Offer
        fields = [
            'id', 'name', 'description',
            'discount_type', 'discount_type_display', 'discount_value',
            'applicability', 'applicability_display', 'plans',
            'max_uses', 'max_uses_per_member',
            'valid_from', 'valid_until',
            'is_active', 'total_uses', 'is_available',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        valid_from = data.get('valid_from', getattr(self.instance, 'valid_from', None))
        valid_until = data.get('valid_until', getattr(self.instance, 'valid_until', None))
        if valid_from and valid_until and valid_until <= valid_from:
            raise serializers.ValidationError({'valid_until': 'Must be after valid_from.'})
        discount_type = data.get('discount_type', getattr(self.instance, 'discount_type', None))
        discount_value = data.get('discount_value', getattr(self.instance, 'discount_value', None))
        if discount_type == Offer.DiscountType.PERCENTAGE and discount_value > 100:
            raise serializers.ValidationError({'discount_value': 'Percentage cannot exceed 100.'})
        applicability = data.get('applicability', getattr(self.instance, 'applicability', None))
        plans = data.get('plans', None)
        if applicability == Offer.Applicability.SPECIFIC_PLANS and not plans:
            raise serializers.ValidationError({'plans': 'At least one plan is required when applicability is SPECIFIC_PLANS.'})
        return data


class PromoCodeSerializer(serializers.ModelSerializer):
    """CRUD serializer for Promo Codes (Owner/Staff only)."""
    offer_name = serializers.CharField(source='offer.name', read_only=True)
    offer_discount_type = serializers.CharField(source='offer.discount_type', read_only=True)
    offer_discount_value = serializers.DecimalField(source='offer.discount_value', max_digits=10, decimal_places=2, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default=None)
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = PromoCode
        fields = [
            'id', 'code', 'offer', 'offer_name', 'offer_discount_type', 'offer_discount_value',
            'status', 'status_display',
            'max_uses', 'used_count',
            'valid_from', 'valid_until',
            'created_by', 'created_by_name',
            'is_valid',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'used_count', 'created_at', 'updated_at']

    def validate_code(self, value):
        value = value.upper().strip()
        if self.instance and self.instance.code == value:
            return value
        if PromoCode.objects.filter(code=value).exists():
            raise serializers.ValidationError('A promo code with this code already exists.')
        return value

    def validate(self, data):
        valid_from = data.get('valid_from', getattr(self.instance, 'valid_from', None))
        valid_until = data.get('valid_until', getattr(self.instance, 'valid_until', None))
        if valid_from and valid_until and valid_until <= valid_from:
            raise serializers.ValidationError({'valid_until': 'Must be after valid_from.'})
        return data


class ValidatePromoCodeSerializer(serializers.Serializer):
    """Used by members to validate and apply a promo code during purchase."""
    code = serializers.CharField(max_length=50)
    plan_id = serializers.IntegerField()

    def validate_code(self, value):
        value = value.upper().strip()
        try:
            promo = PromoCode.objects.select_related('offer').get(code=value)
        except PromoCode.DoesNotExist:
            raise serializers.ValidationError('Invalid promo code.')
        if not promo.is_valid:
            raise serializers.ValidationError('This promo code is no longer valid.')
        return promo

    def validate_plan_id(self, value):
        try:
            plan = MembershipPlan.objects.get(pk=value, is_active=True)
        except MembershipPlan.DoesNotExist:
            raise serializers.ValidationError('Invalid or inactive plan.')
        return plan

    def validate(self, data):
        promo = data['code']
        plan = data['plan_id']
        if not promo.offer.applies_to_plan(plan):
            raise serializers.ValidationError('This promo code does not apply to the selected plan.')
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            user = request.user
            # Check per-member usage limit
            member_uses = PromoCodeUsage.objects.filter(
                promo_code=promo, member=user
            ).count()
            if member_uses >= promo.offer.max_uses_per_member:
                raise serializers.ValidationError('You have already used this promo code the maximum number of times.')
        return data