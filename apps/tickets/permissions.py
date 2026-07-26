"""Object-Level Permissions para tickets.

Implementa permisos a nivel de objeto para que:
- Admin/Superuser: acceso total a todos los tickets.
- Técnico: solo tickets asignados a él.
- Inquilino: solo tickets creados por él.
"""

from rest_framework.permissions import BasePermission


class IsTicketParticipantOrAdmin(BasePermission):
    """Permite acceso solo a participantes del ticket o administradores.

    Se evalúa a nivel de objeto (``has_object_permission``) y requiere
    que la vista invoque ``self.check_object_permissions(request, obj)``
    después de obtener el objeto.
    """

    message = 'No tienes permiso para acceder a este ticket.'

    def has_object_permission(self, request, view, obj):
        user = request.user

        # Admin y superusuarios tienen acceso total
        if getattr(user, 'is_admin', False) or user.is_superuser:
            return True

        # Técnico solo ve tickets asignados a él
        if getattr(user, 'is_tecnico', False):
            return obj.tecnico_id == user.id

        # Inquilino solo ve tickets que él creó
        if getattr(user, 'is_inquilino', False):
            return obj.inquilino_id == user.id

        return False
