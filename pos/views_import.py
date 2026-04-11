# pos/views_import.py

from django.http import FileResponse, Http404
from django.utils.text import slugify

from rest_framework import status
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Shop
from .models_import import ImportJob
from .serializers_import import (
    ImportUploadSerializer,
    ImportJobListSerializer,
    ImportJobDetailSerializer,
    ImportValidateResponseSerializer,
    ImportConfirmSerializer,
    ImportTemplateInfoSerializer,
)
from .permissions_import import (
    ImportTemplatePermission,
    ImportJobPermission,
)
from .services.import_service import (
    build_template_workbook,
    template_info,
    validate_import_workbook,
    run_import,
)


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
    if request.user.is_superuser:
        shop_id = request.query_params.get("shop_id") or request.data.get("shop_id")
        if not shop_id:
            raise ValueError("shop_id is required for platform admin.")

        try:
            return Shop.objects.get(pk=int(shop_id))
        except (Shop.DoesNotExist, TypeError, ValueError):
            raise ValueError("Invalid shop_id.")

    return _require_user_shop(request)


class ImportTemplateDownloadAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, ImportTemplatePermission]

    def get(self, request):
        workbook_stream = build_template_workbook()
        filename = template_info()["filename"]

        return FileResponse(
            workbook_stream,
            as_attachment=True,
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


class ImportTemplateInfoAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, ImportTemplatePermission]

    def get(self, request):
        serializer = ImportTemplateInfoSerializer(template_info())
        return Response(serializer.data)


class ImportJobListCreateAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, ImportJobPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    action_name = "list_create"

    def get(self, request):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        qs = ImportJob.objects.filter(shop=shop).order_by("-created_at", "-id")
        serializer = ImportJobListSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    def post(self, request):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        serializer = ImportUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        upload = serializer.validated_data["file"]
        upload.seek(0, 2)
        file_size_bytes = upload.tell()
        upload.seek(0)

        import_job = ImportJob.objects.create(
            shop=shop,
            file=upload,
            original_filename=getattr(upload, "name", "") or "master_import.xlsx",
            file_size_bytes=file_size_bytes,
            uploaded_by=request.user if not request.user.is_superuser else None,
            status=ImportJob.Status.UPLOADED,
            metadata={},
        )

        out = ImportJobDetailSerializer(import_job, context={"request": request})
        return Response(out.data, status=status.HTTP_201_CREATED)


class ImportJobDetailAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, ImportJobPermission]
    action_name = "detail"

    def get_object(self, request, pk):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            raise Http404(str(e))

        try:
            obj = ImportJob.objects.get(pk=pk, shop=shop)
        except ImportJob.DoesNotExist:
            raise Http404("Import job not found.")
        return obj

    def get(self, request, pk):
        obj = self.get_object(request, pk)
        self.check_object_permissions(request, obj)

        serializer = ImportJobDetailSerializer(obj, context={"request": request})
        return Response(serializer.data)


class ImportJobValidateAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, ImportJobPermission]
    action_name = "validate"

    def get_object(self, request, pk):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            raise Http404(str(e))

        try:
            obj = ImportJob.objects.get(pk=pk, shop=shop)
        except ImportJob.DoesNotExist:
            raise Http404("Import job not found.")
        return obj

    def post(self, request, pk):
        obj = self.get_object(request, pk)
        self.check_object_permissions(request, obj)

        try:
            result = validate_import_workbook(obj)
            return Response(result)
        except Exception as e:
            import traceback
            traceback.print_exc()

            obj.mark_failed(str(e))
            return Response(
                {"message": "Validation failed.", "error": str(e)},
                status=500,
            )

class ImportJobConfirmAPIView(APIView):
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, ImportJobPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    action_name = "confirm"

    def get_object(self, request, pk):
        try:
            shop = _get_effective_shop(request)
        except ValueError as e:
            raise Http404(str(e))

        try:
            obj = ImportJob.objects.get(pk=pk, shop=shop)
        except ImportJob.DoesNotExist:
            raise Http404("Import job not found.")
        return obj

    def post(self, request, pk):
        obj = self.get_object(request, pk)
        self.check_object_permissions(request, obj)

        serializer = ImportConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            job = run_import(
                obj,
                confirm_import=serializer.validated_data["confirm_import"],
                skip_backup_check=serializer.validated_data.get("skip_backup_check", False),
            )
            out = ImportJobDetailSerializer(job, context={"request": request})
            return Response(out.data)
        except Exception as e:
            obj.mark_failed(str(e))
            return Response(
                {"message": "Import failed.", "error": str(e)},
                status=500,
            )