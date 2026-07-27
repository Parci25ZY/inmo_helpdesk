"""Tests para apps/properties.

Cubre la corrección de un bug real: `EdificioDeleteView`/`UnidadDeleteView`
no capturaban `ProtectedError`. `Ticket.unidad` usa `on_delete=PROTECT`,
así que borrar una unidad (o un edificio cuya cascada llega a esa unidad)
con al menos un ticket histórico lanzaba una excepción no controlada →
error 500 para una acción común de administración.
"""
from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import CustomUser
from apps.properties.models import Edificio, Unidad
from apps.tickets.models import Ticket


def _make_admin(email='admin@test.com'):
    return CustomUser.objects.create_user(
        email=email, password='clave12345', first_name='Ada', last_name='Admin',
        role=CustomUser.Roles.ADMIN,
    )


def _make_inquilino_con_unidad(unidad, email='residente@test.com'):
    inquilino = CustomUser.objects.create_user(
        email=email, password='clave12345', first_name='Ana', last_name='Residente',
        role=CustomUser.Roles.INQUILINO,
    )
    unidad.inquilino = inquilino
    unidad.save(update_fields=['inquilino'])
    return inquilino


@pytest.mark.django_db
class TestDeleteWithLinkedTickets:
    def test_unidad_delete_with_ticket_shows_error_instead_of_500(self):
        admin = _make_admin()
        edificio = Edificio.objects.create(
            nombre='Torre Test', codigo='TT-01', direccion='Calle Falsa 123',
        )
        unidad = Unidad.objects.create(edificio=edificio, numero='101')
        inquilino = _make_inquilino_con_unidad(unidad)
        Ticket.objects.create(
            inquilino=inquilino,
            unidad=unidad,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
        )

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('unidad_delete', kwargs={'pk': unidad.pk}))

        assert response.status_code == 302
        # La unidad debe seguir existiendo: el borrado se bloqueó, no crasheó.
        assert Unidad.objects.filter(pk=unidad.pk).exists()

    def test_edificio_delete_with_ticket_in_its_unidad_shows_error_instead_of_500(self):
        admin = _make_admin(email='admin2@test.com')
        edificio = Edificio.objects.create(
            nombre='Torre Test 2', codigo='TT-02', direccion='Calle Falsa 456',
        )
        unidad = Unidad.objects.create(edificio=edificio, numero='201')
        inquilino = _make_inquilino_con_unidad(unidad, email='residente2@test.com')
        Ticket.objects.create(
            inquilino=inquilino,
            unidad=unidad,
            titulo='Fuga de agua en el baño',
            descripcion='Hay una fuga constante bajo el lavamanos.',
        )

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('edificio_delete', kwargs={'pk': edificio.pk}))

        assert response.status_code == 302
        assert Edificio.objects.filter(pk=edificio.pk).exists()

    def test_unidad_delete_without_tickets_still_works(self):
        """El fix no debe romper el caso feliz: sin tickets, sí se borra."""
        admin = _make_admin(email='admin3@test.com')
        edificio = Edificio.objects.create(
            nombre='Torre Test 3', codigo='TT-03', direccion='Calle Falsa 789',
        )
        unidad = Unidad.objects.create(edificio=edificio, numero='301')

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('unidad_delete', kwargs={'pk': unidad.pk}))

        assert response.status_code == 302
        assert not Unidad.objects.filter(pk=unidad.pk).exists()
