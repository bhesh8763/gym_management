from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import PaymentViewSet, khalti_webhook

router = DefaultRouter()
router.register('', PaymentViewSet, basename='payment')

urlpatterns = [
    # Khalti server-to-server webhook — must be outside DRF router
    # because it's a plain Django view (no auth required).
    path('khalti-webhook/', khalti_webhook, name='khalti-webhook'),
] + router.urls
