from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .api_views import (
    EmailTokenObtainPairView,
    PasswordResetConfirmAPIView,
    PasswordResetRequestAPIView,
    PasswordResetVerifyAPIView,
)

app_name = 'auth_api'

urlpatterns = [
    path('token/', EmailTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('password-reset/request/', PasswordResetRequestAPIView.as_view(), name='password_reset_request'),
    path('password-reset/verify/', PasswordResetVerifyAPIView.as_view(), name='password_reset_verify'),
    path('password-reset/confirm/', PasswordResetConfirmAPIView.as_view(), name='password_reset_confirm'),
]
