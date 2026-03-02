# backend/accounts/urls.py
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

from .views import (
    SignupView,
    LoginAPIView,
    LogoutView,
    CurrentUserProfileView,
    SendOTPView,
    VerifyEmailView,
    ResendVerificationView,
    RequestPasswordResetView,
    ResetPasswordView,
    ChangePasswordView,
    TenantListCreateView,
    TenantDetailView,
    TenantStatsView,
    TenantChangePlanView,
    AuditLogListView,
    AuditLogDetailView,
    AIUsageLogListView,
    AIUsageLogDetailView,
    CheckSubscriptionStatusView,
    UserManagementView,
    CreateUserView,
    UserDetailView,
    UserToggleActiveView,
    UserChangeRoleView,
    UserListCreateView,
)
from .serializers import MyTokenObtainPairSerializer

app_name = "accounts"

urlpatterns = [
    # ================= AUTH =================
    path("signup/", SignupView.as_view(), name="signup"),
    path("login/", LoginAPIView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),

    # ================= JWT =================
    path("token/", TokenObtainPairView.as_view(serializer_class=MyTokenObtainPairSerializer), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    # ================= CURRENT USER =================
    # ✅ This is the endpoint Profile.jsx calls: GET/PUT /auth/me/
    path("me/", CurrentUserProfileView.as_view(), name="current-user-profile"),

    # ================= OTP / VERIFICATION =================
    path("send-otp/", SendOTPView.as_view(), name="send-otp"),
    path("verify-email/", VerifyEmailView.as_view(), name="verify-email"),
    path("resend-verification/", ResendVerificationView.as_view(), name="resend-verification"),

    # ================= PASSWORD =================
    path("request-password-reset/", RequestPasswordResetView.as_view(), name="request-password-reset"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),

    # ================= SUBSCRIPTION =================
    path("subscription/status/", CheckSubscriptionStatusView.as_view(), name="subscription-status"),

    # ================= USER MANAGEMENT =================
    # Short paths
    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/create/", CreateUserView.as_view(), name="user-create"),
    path("users/manage/", UserManagementView.as_view(), name="user-manage"),
    path("users/<uuid:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("users/<uuid:pk>/toggle-active/", UserToggleActiveView.as_view(), name="user-toggle-active"),
    path("users/<uuid:pk>/change-role/", UserChangeRoleView.as_view(), name="user-change-role"),

    # ✅ Prefixed paths — matches what the frontend actually calls:
    # /api/auth/user-management/users/
    path("user-management/users/", UserManagementView.as_view(), name="user-management-list"),
    path("user-management/users/create/", CreateUserView.as_view(), name="user-management-create"),
    path("user-management/users/<uuid:pk>/", UserDetailView.as_view(), name="user-management-detail"),
    path("user-management/users/<uuid:pk>/toggle-active/", UserToggleActiveView.as_view(), name="user-management-toggle"),
    path("user-management/users/<uuid:pk>/change-role/", UserChangeRoleView.as_view(), name="user-management-role"),

    # ================= TENANTS =================
    path("tenants/", TenantListCreateView.as_view(), name="tenant-list-create"),
    path("tenants/<uuid:pk>/", TenantDetailView.as_view(), name="tenant-detail"),
    path("tenants/<uuid:pk>/stats/", TenantStatsView.as_view(), name="tenant-stats"),
    path("tenants/<uuid:pk>/change-plan/", TenantChangePlanView.as_view(), name="tenant-change-plan"),

    # ================= AUDIT LOGS =================
    path("audit-logs/", AuditLogListView.as_view(), name="audit-log-list"),
    path("audit-logs/<uuid:pk>/", AuditLogDetailView.as_view(), name="audit-log-detail"),

    # ================= AI USAGE =================
    path("ai-usage/", AIUsageLogListView.as_view(), name="ai-usage-log-list"),
    path("ai-usage/<uuid:pk>/", AIUsageLogDetailView.as_view(), name="ai-usage-log-detail"),
]