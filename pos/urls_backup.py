from django.urls import path
from .views_backup import (
    BackupSummaryAPIView,
    BackupSettingAPIView,
    BackupRunAPIView,
    BackupHistoryListAPIView,
    BackupHistoryDetailAPIView,
    BackupDownloadAPIView,
    BackupRestoreAPIView,
    RestoreHistoryListAPIView,
)

urlpatterns = [
    path("backup-center/summary/", BackupSummaryAPIView.as_view(), name="backup_center_summary"),
    path("backup-settings/", BackupSettingAPIView.as_view(), name="backup_settings"),

    path("backups/", BackupHistoryListAPIView.as_view(), name="backup_history_list"),
    path("backups/run/", BackupRunAPIView.as_view(), name="backup_run"),
    path("backups/<int:pk>/", BackupHistoryDetailAPIView.as_view(), name="backup_history_detail"),
    path("backups/<int:pk>/download/", BackupDownloadAPIView.as_view(), name="backup_download"),
    path("backups/<int:pk>/restore/", BackupRestoreAPIView.as_view(), name="backup_restore"),

    path("restores/", RestoreHistoryListAPIView.as_view(), name="restore_history_list"),
]