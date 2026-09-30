from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'profiles', views.TrainerProfileViewSet, basename='trainer-profile')
router.register(r'assignments', views.TrainerMemberAssignmentViewSet, basename='trainer-assignment')

urlpatterns = [
    path('', include(router.urls)),
    path('my-members/', views.MyAssignedMembersView.as_view(), name='trainer-my-members'),
]
