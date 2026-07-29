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


@pytest.mark.django_db
class TestDeleteBlockedByResidente:
    """Regresión: antes solo los tickets vinculados bloqueaban el borrado
    de una unidad/edificio — una unidad con residente asignado pero sin
    tickets se borraba sin ningún aviso, dejando al residente huérfano
    (su `unidad_asignada` desaparecía en silencio). Ahora se bloquea
    igual que con los tickets.
    """

    def test_unidad_delete_with_residente_and_no_tickets_is_blocked(self):
        admin = _make_admin(email='admin6@test.com')
        edificio = Edificio.objects.create(
            nombre='Torre Test 6', codigo='TT-06', direccion='Calle Falsa 333',
        )
        unidad = Unidad.objects.create(edificio=edificio, numero='601')
        _make_inquilino_con_unidad(unidad, email='residente6@test.com')

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('unidad_delete', kwargs={'pk': unidad.pk}))

        assert response.status_code == 302
        assert Unidad.objects.filter(pk=unidad.pk).exists()

    def test_unidad_delete_without_residente_still_works(self):
        admin = _make_admin(email='admin7@test.com')
        edificio = Edificio.objects.create(
            nombre='Torre Test 7', codigo='TT-07', direccion='Calle Falsa 444',
        )
        unidad = Unidad.objects.create(edificio=edificio, numero='701')

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('unidad_delete', kwargs={'pk': unidad.pk}))

        assert response.status_code == 302
        assert not Unidad.objects.filter(pk=unidad.pk).exists()

    def test_edificio_delete_with_residente_in_its_unidad_is_blocked(self):
        admin = _make_admin(email='admin8@test.com')
        edificio = Edificio.objects.create(
            nombre='Torre Test 8', codigo='TT-08', direccion='Calle Falsa 555',
        )
        unidad = Unidad.objects.create(edificio=edificio, numero='801')
        _make_inquilino_con_unidad(unidad, email='residente8b@test.com')

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('edificio_delete', kwargs={'pk': edificio.pk}))

        assert response.status_code == 302
        assert Edificio.objects.filter(pk=edificio.pk).exists()
        assert Unidad.objects.filter(pk=unidad.pk).exists()

    def test_edificio_delete_without_residentes_still_works(self):
        admin = _make_admin(email='admin9@test.com')
        edificio = Edificio.objects.create(
            nombre='Torre Test 9', codigo='TT-09', direccion='Calle Falsa 666',
        )
        Unidad.objects.create(edificio=edificio, numero='901')

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('edificio_delete', kwargs={'pk': edificio.pk}))

        assert response.status_code == 302
        assert not Edificio.objects.filter(pk=edificio.pk).exists()


@pytest.mark.django_db
class TestUnidadCreatableSinResidente:
    """Regresión: UnidadForm forzaba `inquilino` como obligatorio, aunque
    el modelo (`inquilino = OneToOneField(..., null=True, blank=True)`) y
    las plantillas (`unidad_list.html` ya maneja "Sin asignar") siempre
    soportaron unidades vacantes — el KPI "Libres" del catálogo de
    edificios no tenía forma de dejar de ser 0 salvo que un residente
    fuera eliminado después. Se relaja el formulario para que coincida
    con lo que el modelo ya permitía.
    """

    def test_admin_can_create_unidad_without_assigning_resident(self):
        admin = _make_admin(email='admin4@test.com')
        edificio = Edificio.objects.create(
            nombre='Torre Test 4', codigo='TT-04', direccion='Calle Falsa 111',
        )

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('unidad_create'), {
            'edificio': edificio.pk,
            'numero': '401',
            'piso': '4',
            'tipo': Unidad.Tipo.DEPARTAMENTO,
            'area_m2': '75.5',
            'inquilino': '',
            'activo': 'on',
        })

        assert response.status_code == 302
        unidad = Unidad.objects.get(edificio=edificio, numero='401')
        assert unidad.inquilino_id is None
        assert edificio.unidades.filter(inquilino__isnull=True).count() == 1

    def test_admin_can_unassign_resident_from_existing_unidad(self):
        admin = _make_admin(email='admin5@test.com')
        edificio = Edificio.objects.create(
            nombre='Torre Test 5', codigo='TT-05', direccion='Calle Falsa 222',
        )
        unidad = Unidad.objects.create(edificio=edificio, numero='501', piso=5, area_m2='60')
        _make_inquilino_con_unidad(unidad, email='residente5@test.com')

        client = Client()
        client.force_login(admin)
        response = client.post(reverse('unidad_edit', kwargs={'pk': unidad.pk}), {
            'edificio': edificio.pk,
            'numero': '501',
            'piso': '5',
            'tipo': unidad.tipo,
            'area_m2': '60',
            'inquilino': '',
            'activo': 'on',
        })

        assert response.status_code == 302
        unidad.refresh_from_db()
        assert unidad.inquilino_id is None
