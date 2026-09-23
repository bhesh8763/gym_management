from django.urls import path

from . import views

urlpatterns = [
    path('', views.ImportView.as_view(), name='import-run'),
    path('template/', views.ImportTemplateView.as_view(), name='import-template'),
]
