from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'', views.TrainerProfileViewSet, basename='trainer-profile')
router.register(r'assignments', views.TrainerMemberAssignmentViewSet, basename='trainer-assignment')

urlpatterns = [
    path('my-members/', views.MyAssignedMembersView.as_view(), name='trainer-my-members'),
    path('', include(router.urls)),
]
