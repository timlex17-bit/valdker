from django.urls import path
from .help_views import help_chat_api

urlpatterns = [
    path("api/help/chat/", help_chat_api, name="help-chat-api"),
]