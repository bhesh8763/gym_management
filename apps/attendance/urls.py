from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AttendanceViewSet,
    MemberQRCodeView,
    MemberProfileQRView,
    QRScanCheckInView,
    RegenerateQRView,
    PublicMemberProfileView,
    SharedCheckinQRView,
)

router = DefaultRouter()
router.register('records', AttendanceViewSet, basename='attendance')

urlpatterns = [
    # Shared check-in QR (encodes checkin.html URL — print & post at entrance)
    path('checkin-qr/', SharedCheckinQRView.as_view(), name='attendance-checkin-qr'),

    # Check-in QR (encodes attendance token — used at kiosk)
    path('qr/my/', MemberQRCodeView.as_view(), name='attendance-qr-my'),
    path('qr/<int:member_id>/', MemberQRCodeView.as_view(), name='attendance-qr-member'),

    # Profile QR (encodes public URL — scanning shows member info)
    path('qr/<int:member_id>/profile/', MemberProfileQRView.as_view(), name='attendance-qr-profile'),

    # Scan endpoint (open — for kiosk/tablet)
    path('qr/scan/', QRScanCheckInView.as_view(), name='attendance-qr-scan'),

    # Regenerate token
    path('qr/regenerate/', RegenerateQRView.as_view(), name='attendance-qr-regenerate-my'),
    path('qr/<int:member_id>/regenerate/', RegenerateQRView.as_view(), name='attendance-qr-regenerate'),

    # Public member profile (open — no auth needed, called when QR is scanned)
    path('member-profile/<int:member_id>/', PublicMemberProfileView.as_view(), name='public-member-profile'),
] + router.urls
