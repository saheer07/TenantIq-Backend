from django.urls import path
from .views import (
    UserListView,
    CreateUserView,
    UserDetailView,
    ToggleUserActiveView
)

app_name = 'user_management'

urlpatterns = [
    path('users/', UserListView.as_view(), name='user-list'),
    path('users/create/', CreateUserView.as_view(), name='user-create'),
    path('users/<uuid:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('users/<uuid:pk>/toggle-active/', ToggleUserActiveView.as_view(), name='user-toggle-active'),
]