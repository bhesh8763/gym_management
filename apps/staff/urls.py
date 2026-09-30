from rest_framework.routers import DefaultRouter
from .views import StaffProfileViewSet, LeaveRequestViewSet

router = DefaultRouter()
router.register('profiles', StaffProfileViewSet, basename='staff-profile')
router.register('leave-requests', LeaveRequestViewSet, basename='leave-request')

urlpatterns = router.urls