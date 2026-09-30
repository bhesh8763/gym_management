from django.urls import path

from . import views

app_name = 'gyms'

urlpatterns = [
    path('', views.GymListView.as_view(), name='gym-list'),
    path('current/', views.CurrentGymView.as_view(), name='gym-current'),
    path('switch/', views.GymSwitchView.as_view(), name='gym-switch'),
    path('<int:pk>/', views.GymDetailView.as_view(), name='gym-detail'),
    path('<int:pk>/memberships/', views.GymMembershipListCreateView.as_view(), name='gym-memberships'),
    path('<int:pk>/memberships/<int:membership_id>/', views.GymMembershipDetailView.as_view(), name='gym-membership-detail'),
    path('<int:pk>/branches/', views.BranchListCreateView.as_view(), name='gym-branches'),
    path('<int:pk>/invitations/', views.InvitationCreateView.as_view(), name='gym-invitations'),
    path('invitations/accept/', views.InvitationAcceptView.as_view(), name='gym-invitation-accept'),
    path('<int:pk>/impersonate/', views.ImpersonationStartView.as_view(), name='gym-impersonate-start'),
    path('impersonations/<int:pk>/end/', views.ImpersonationEndView.as_view(), name='gym-impersonate-end'),
    path('<int:pk>/audit/', views.AuditLogListView.as_view(), name='gym-audit'),
    path('roles/', views.CustomRoleListCreateView.as_view(), name='role-list'),
    path('roles/catalog/', views.RoleCatalogView.as_view(), name='role-catalog'),
    path('roles/<int:pk>/', views.CustomRoleDetailView.as_view(), name='role-detail'),
    path('trash/', views.TrashSummaryView.as_view(), name='trash-summary'),
    path('trash/<slug>/', views.TrashListView.as_view(), name='trash-list'),
    path('trash/<slug>/<int:pk>/restore/', views.TrashRestoreView.as_view(), name='trash-restore'),
    path('trash/<slug>/<int:pk>/', views.TrashPurgeView.as_view(), name='trash-purge'),
]
