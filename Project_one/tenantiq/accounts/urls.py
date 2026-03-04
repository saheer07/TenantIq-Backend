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
]
