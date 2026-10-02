from rest_framework.routers import DefaultRouter
from .views import StaffProfileViewSet, LeaveRequestViewSet, ShiftViewSet, StaffShiftViewSet

router = DefaultRouter()
router.register('profiles', StaffProfileViewSet, basename='staff-profile')
router.register('leave-requests', LeaveRequestViewSet, basename='leave-request')
router.register('shifts', ShiftViewSet, basename='shift')
router.register('schedules', StaffShiftViewSet, basename='staff-shift')

urlpatterns = router.urls