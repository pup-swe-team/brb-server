from django.urls import path

from .views import AdminAuditLogDetailView, AdminAuditLogListView

urlpatterns = [
    path(
        "admin/audit-logs/",
        AdminAuditLogListView.as_view(),
        name="api-admin-audit-log-list",
    ),
    path(
        "admin/audit-logs/<int:pk>/",
        AdminAuditLogDetailView.as_view(),
        name="api-admin-audit-log-detail",
    ),
]
