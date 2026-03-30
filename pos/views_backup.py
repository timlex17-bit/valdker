# pos/views_backup.py

from django.http import FileResponse, Http404

from rest_framework import status
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Shop
from .models_backup import BackupSetting, BackupHistory, RestoreHistory
from .serializers_backup import (
    BackupSettingSerializer,
    BackupHistoryListSerializer,
    BackupHistoryDetailSerializer,
    RestoreRequestSerializer,
    BackupSummarySerializer,
    RestoreHistorySerializer,
    BackupRunRequestSerializer,
)
from .permissions_backup import (
    BackupSettingPermission,
    BackupSummaryPermission,
    BackupHistoryPermission,
    BackupRunPermission,
    BackupRestorePermission,
    RestoreHistoryPermission,
)
from .services.backup_service import (
    ensure_backup_setting,
    run_manual_backup,
)
from .services.restore_service import (
    run_restore_validation,
)


# =========================================================
# HELPERS
# =========================================================
def _user_shop(request):
    return getattr(request.user, "shop", None)


def _require_user_shop(request):
    if request.user.is_superuser:
        raise ValueError("Platform admin has no tenant shop context for this endpoint.")

    shop = _user_shop(request)
    if not shop:
        raise ValueError("User does not have an assigned shop.")

    return shop


def _get_effective_shop(request):
    """
    Tenant user -> request.user.shop
    Superuser    -> optional ?shop_id= or body shop_id
    """
    if request.user.is_superuser:
        shop_id = request.query_params.get("shop_id") or request.data.get("shop_id")
        if not shop_id:
            raise ValueError("shop_id is required for platform admin.")

        try:
            return Shop.objects.get(pk=int(shop_id))
        except (Shop.DoesNotExist, TypeError, ValueError):
            raise ValueError("Invalid shop_id.")

    return _require_user_shop(request)


# =========================================================
# SUMMARY
# =========================================================
class BackupSummaryAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, BackupSummaryPermission]

    def get(self, request):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        setting = ensure_backup_setting(shop)
        data = BackupSummarySerializer.build(setting)
        serializer = BackupSummarySerializer(data)
        return Response(serializer.data)


# =========================================================
# SETTINGS
# =========================================================
class BackupSettingAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, BackupSettingPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self, request):
        shop = _get_effective_shop(request)
        return ensure_backup_setting(shop)

    def get(self, request):
        try:
            obj = self.get_object(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        self.check_object_permissions(request, obj)
        serializer = BackupSettingSerializer(obj, context={"request": request})
        return Response(serializer.data)

    def put(self, request):
        try:
            obj = self.get_object(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        self.check_object_permissions(request, obj)

        serializer = BackupSettingSerializer(
            obj,
            data=request.data,
            partial=False,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def patch(self, request):
        try:
            obj = self.get_object(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        self.check_object_permissions(request, obj)

        serializer = BackupSettingSerializer(
            obj,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# =========================================================
# RUN BACKUP
# =========================================================
class BackupRunAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, BackupRunPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        serializer = BackupRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        try:
            backup = run_manual_backup(
                shop=shop,
                user=request.user,
                include_media=validated.get("include_media"),
                include_users=validated.get("include_users"),
                include_settings=validated.get("include_settings"),
            )

            return Response(
                {
                    "message": "Manual backup completed successfully.",
                    "backup_id": backup.id,
                    "status": backup.status,
                    "file_name": backup.file_name,
                    "file_size": backup.file_size_label,
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            return Response(
                {
                    "message": "Backup failed.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# =========================================================
# BACKUP HISTORY LIST
# =========================================================
class BackupHistoryListAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, BackupHistoryPermission]

    def get(self, request):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        qs = BackupHistory.objects.filter(
            shop=shop,
            deleted_at__isnull=True,
        ).order_by("-started_at", "-id")

        search = (request.query_params.get("search") or "").strip()
        status_filter = (request.query_params.get("status") or "").strip().lower()
        type_filter = (request.query_params.get("type") or "").strip().lower()

        if search:
            qs = qs.filter(
                triggered_by__icontains=search
            ) | BackupHistory.objects.filter(
                shop=shop,
                deleted_at__isnull=True,
                note__icontains=search,
            ) | BackupHistory.objects.filter(
                shop=shop,
                deleted_at__isnull=True,
                status__icontains=search,
            ) | BackupHistory.objects.filter(
                shop=shop,
                deleted_at__isnull=True,
                backup_type__icontains=search,
            )
            qs = qs.order_by("-started_at", "-id")

        if status_filter in {"success", "failed", "running"}:
            qs = qs.filter(status=status_filter)

        if type_filter in {"auto", "manual"}:
            qs = qs.filter(backup_type=type_filter)

        serializer = BackupHistoryListSerializer(
            qs,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)


# =========================================================
# BACKUP HISTORY DETAIL + DELETE
# =========================================================
class BackupHistoryDetailAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, BackupHistoryPermission]

    def get_object(self, request, pk):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            raise Http404(str(e))

        try:
            obj = BackupHistory.objects.get(
                pk=pk,
                shop=shop,
                deleted_at__isnull=True,
            )
        except BackupHistory.DoesNotExist:
            raise Http404("Backup not found.")

        return obj

    def get(self, request, pk):
        obj = self.get_object(request, pk)
        self.check_object_permissions(request, obj)

        serializer = BackupHistoryDetailSerializer(
            obj,
            context={"request": request},
        )
        return Response(serializer.data)

    def delete(self, request, pk):
        obj = self.get_object(request, pk)
        self.check_object_permissions(request, obj)

        if obj.file:
            try:
                storage = obj.file.storage
                if storage.exists(obj.file.name):
                    storage.delete(obj.file.name)
            except Exception:
                pass

        obj.soft_delete()
        return Response({"message": "Backup deleted successfully."}, status=200)


# =========================================================
# DOWNLOAD BACKUP
# =========================================================
class BackupDownloadAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, BackupHistoryPermission]

    def get_object(self, request, pk):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            raise Http404(str(e))

        try:
            obj = BackupHistory.objects.get(
                pk=pk,
                shop=shop,
                deleted_at__isnull=True,
                status=BackupHistory.Status.SUCCESS,
            )
        except BackupHistory.DoesNotExist:
            raise Http404("Backup not found.")

        return obj

    def get(self, request, pk):
        obj = self.get_object(request, pk)
        self.check_object_permissions(request, obj)

        if not obj.file:
            raise Http404("Backup file not found.")

        try:
            file_path = obj.file.path
        except Exception:
            raise Http404("Backup file path not available.")

        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=obj.file_name or "backup.zip",
        )


# =========================================================
# RESTORE BACKUP
# =========================================================
class BackupRestoreAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, BackupRestorePermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_backup(self, request, pk):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            raise Http404(str(e))

        try:
            obj = BackupHistory.objects.get(
                pk=pk,
                shop=shop,
                deleted_at__isnull=True,
                status=BackupHistory.Status.SUCCESS,
            )
        except BackupHistory.DoesNotExist:
            raise Http404("Backup not found.")

        return obj

    def post(self, request, pk):
        backup = self.get_backup(request, pk)
        self.check_object_permissions(request, backup)

        serializer = RestoreRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mode = serializer.validated_data["mode"]

        try:
            restore = run_restore_validation(
                shop=backup.shop,
                backup=backup,
                mode=mode,
                user=request.user,
            )

            return Response(
                {
                    "message": f"Restore validation completed with mode: {mode}.",
                    "restore_id": restore.id,
                    "status": restore.status,
                    "note": restore.note,
                },
                status=200,
            )

        except Exception as e:
            return Response(
                {
                    "message": "Restore failed.",
                    "error": str(e),
                },
                status=500,
            )


# =========================================================
# RESTORE HISTORY LIST
# =========================================================
class RestoreHistoryListAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, RestoreHistoryPermission]

    def get(self, request):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        qs = RestoreHistory.objects.filter(shop=shop).order_by("-started_at", "-id")

        status_filter = (request.query_params.get("status") or "").strip().lower()
        if status_filter in {"success", "failed", "running"}:
            qs = qs.filter(status=status_filter)

        serializer = RestoreHistorySerializer(
            qs,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)