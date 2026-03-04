from django.urls import path
from accounts.views import (
    UserManagementView,
    CreateUserView,
    UserDetailView,
    UserToggleActiveView,
    UserChangeRoleView,
    UserListCreateView
)

urlpatterns = [
    path("users/", UserListCreateView.as_view(), name="user-management-list"),
    path("users/create/", CreateUserView.as_view(), name="user-management-create"),
    path("users/<uuid:pk>/", UserDetailView.as_view(), name="user-management-detail"),
    path("users/<uuid:pk>/toggle-active/", UserToggleActiveView.as_view(), name="user-management-toggle-active"),
    path("users/<uuid:pk>/change-role/", UserChangeRoleView.as_view(), name="user-management-change-role"),
    path("manage/", UserManagementView.as_view(), name="user-management-manage"),
]