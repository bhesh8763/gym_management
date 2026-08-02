from django.urls import path

from apps.members.views import MemberDetailView, MemberListCreateView, MemberReactivateView, MyProfileView
from apps.members import template_views

app_name = 'members'

urlpatterns = [
    # ── API ──────────────────────────────────────────────────────────────────
    path('', MemberListCreateView.as_view(), name='member-list-create'),
    path('me/', MyProfileView.as_view(), name='my-profile'),
    path('<int:pk>/reactivate/', MemberReactivateView.as_view(), name='member-reactivate'),
    path('<int:pk>/', MemberDetailView.as_view(), name='member-detail'),

    # ── UI (template views) ───────────────────────────────────────────────────
    path('ui/', template_views.MemberListTemplateView.as_view(), name='ui-list'),
    path('ui/add/', template_views.MemberCreateTemplateView.as_view(), name='ui-create'),
    path('ui/<int:pk>/', template_views.MemberDetailTemplateView.as_view(), name='ui-detail'),
    path('ui/<int:pk>/edit/', template_views.MemberEditTemplateView.as_view(), name='ui-edit'),
]