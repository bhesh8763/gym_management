from rest_framework.routers import DefaultRouter
from .views import EquipmentViewSet, MaintenanceRecordViewSet

router = DefaultRouter()
router.register('equipment', EquipmentViewSet, basename='equipment')
router.register('maintenance', MaintenanceRecordViewSet, basename='maintenance')

urlpatterns = router.urls