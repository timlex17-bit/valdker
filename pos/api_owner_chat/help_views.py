from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .help_responses import match_local_help, get_fallback_help_payload
from .help_ai_service import ask_help_ai


@api_view(["POST"])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def help_chat_api(request):
    message = (request.data.get("message") or "").strip()
    if not message:
        return Response(
            {
                "success": False,
                "message": "Field 'message' wajib diisi."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    local_result = match_local_help(message)
    if local_result:
        return Response(
            {
                "success": True,
                "data": local_result,
            },
            status=status.HTTP_200_OK,
        )

    ai_result = ask_help_ai(message, user=request.user)
    if ai_result:
        return Response(
            {
                "success": True,
                "data": ai_result,
            },
            status=status.HTTP_200_OK,
        )

    return Response(
        {
            "success": True,
            "data": get_fallback_help_payload(),
        },
        status=status.HTTP_200_OK,
    )