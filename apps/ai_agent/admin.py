from django.contrib import admin
from django.utils.html import format_html

from .models import ChatMessage, ChatSession, KnowledgeChunk, KnowledgeDocument
from .tasks import index_knowledge_document


class KnowledgeChunkInline(admin.TabularInline):
    model = KnowledgeChunk
    extra = 0
    readonly_fields = ('indice', 'contenido', 'token_count', 'creado_en')
    can_delete = False
    max_num = 0


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'categoria', 'activo', 'indexado_badge', 'chunk_count', 'actualizado_en')
    list_filter = ('categoria', 'activo', 'indexado')
    search_fields = ('titulo', 'contenido')
    actions = ['reindexar_documentos']
    inlines = [KnowledgeChunkInline]

    @admin.display(description='Indexado')
    def indexado_badge(self, obj):
        color = '#059669' if obj.indexado else '#d97706'
        label = 'Sí' if obj.indexado else 'Pendiente'
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', color, label)

    @admin.display(description='Chunks')
    def chunk_count(self, obj):
        return obj.chunks.count()

    @admin.action(description='Reindexar documentos seleccionados')
    def reindexar_documentos(self, request, queryset):
        for doc in queryset:
            index_knowledge_document.delay(doc.pk)
        self.message_user(request, f'{queryset.count()} documento(s) en cola de indexación.')


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ('rol', 'contenido', 'estado_proceso', 'creado_en')
    can_delete = False
    max_num = 20


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('uuid', 'usuario', 'titulo', 'estado', 'mensaje_count', 'actualizado_en')
    list_filter = ('estado',)
    search_fields = ('titulo', 'usuario__email')
    readonly_fields = ('uuid', 'creado_en', 'actualizado_en')
    inlines = [ChatMessageInline]

    @admin.display(description='Mensajes')
    def mensaje_count(self, obj):
        return obj.mensajes.count()


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('uuid', 'sesion', 'rol', 'estado_proceso', 'preview', 'creado_en')
    list_filter = ('rol', 'estado_proceso')
    search_fields = ('contenido',)
    readonly_fields = ('uuid', 'creado_en')

    @admin.display(description='Contenido')
    def preview(self, obj):
        return obj.contenido[:80] + ('…' if len(obj.contenido) > 80 else '')
