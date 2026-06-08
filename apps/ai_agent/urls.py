from django.urls import path

from .views import ActiveChatSessionView, ChatMessageDetailView, ChatMessageSendView

app_name = 'ai_agent'

urlpatterns = [
    path('chat/session/', ActiveChatSessionView.as_view(), name='chat_session'),
    path('chat/messages/', ChatMessageSendView.as_view(), name='chat_send'),
    path('chat/messages/<uuid:uuid>/', ChatMessageDetailView.as_view(), name='chat_message_detail'),
]
