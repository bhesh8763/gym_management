"""
URL configuration for the Memberships app.

API routes:
    /api/memberships/plans/                 GET (list) | POST (create)
    /api/memberships/plans/<id>/            GET | PUT | PATCH | DELETE (deactivate)

    /api/memberships/expiring/              GET  (?days=N)
    /api/memberships/                       GET (list) | POST (assign)
    /api/memberships/<id>/                  GET | PATCH | DELETE (cancel)
    /api/memberships/<id>/freeze/           POST
    /api/memberships/<id>/unfreeze/         POST
    /api/memberships/<id>/renew/            POST
"""
from django.urls import path

from apps.memberships.views import (
    ExpiringMembershipsView,
    MembershipDetailView,
    MembershipFreezeView,
    MembershipListCreateView,
    MembershipRenewView,
    MembershipUnfreezeView,
    PlanDetailView,
    PlanListCreateView,
)

app_name = 'memberships'

urlpatterns = [
    path('plans/', PlanListCreateView.as_view(), name='plan-list-create'),
    path('plans/<int:pk>/', PlanDetailView.as_view(), name='plan-detail'),

    path('expiring/', ExpiringMembershipsView.as_view(), name='membership-expiring'),

    path('', MembershipListCreateView.as_view(), name='membership-list-create'),
    path('<int:pk>/', MembershipDetailView.as_view(), name='membership-detail'),
    path('<int:pk>/freeze/', MembershipFreezeView.as_view(), name='membership-freeze'),
    path('<int:pk>/unfreeze/', MembershipUnfreezeView.as_view(), name='membership-unfreeze'),
    path('<int:pk>/renew/', MembershipRenewView.as_view(), name='membership-renew'),
]
