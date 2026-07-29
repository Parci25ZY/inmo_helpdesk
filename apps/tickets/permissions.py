
from rest_framework.permissions import BasePermission


class IsTicketParticipantOrAdmin(BasePermission):

    message = 'No tienes permiso para acceder a este ticket.'

    def has_object_permission(self, request, view, obj):
        user = request.user

        if getattr(user, 'is_admin', False) or user.is_superuser:
            return True

        if getattr(user, 'is_tecnico', False):
            return obj.tecnico_id == user.id

        if getattr(user, 'is_inquilino', False):
            return obj.inquilino_id == user.id

        return False
