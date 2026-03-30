# pos/urls_import.py

from django.urls import path

from .views_import import (
    ImportTemplateDownloadAPIView,
    ImportTemplateInfoAPIView,
    ImportJobListCreateAPIView,
    ImportJobDetailAPIView,
    ImportJobValidateAPIView,
    ImportJobConfirmAPIView,
)

urlpatterns = [
    path("import-master-data/template/", ImportTemplateDownloadAPIView.as_view(), name="import_master_template_download"),
    path("import-master-data/template/info/", ImportTemplateInfoAPIView.as_view(), name="import_master_template_info"),

    path("import-master-data/jobs/", ImportJobListCreateAPIView.as_view(), name="import_job_list_create"),
    path("import-master-data/jobs/<int:pk>/", ImportJobDetailAPIView.as_view(), name="import_job_detail"),
    path("import-master-data/jobs/<int:pk>/validate/", ImportJobValidateAPIView.as_view(), name="import_job_validate"),
    path("import-master-data/jobs/<int:pk>/confirm/", ImportJobConfirmAPIView.as_view(), name="import_job_confirm"),
]