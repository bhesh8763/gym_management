from rest_framework.routers import DefaultRouter
from .views import LockerViewSet, LockerAssignmentViewSet

router = DefaultRouter()
router.register('lockers', LockerViewSet, basename='locker')
router.register('assignments', LockerAssignmentViewSet, basename='locker-assignment')

urlpatterns = router.urls