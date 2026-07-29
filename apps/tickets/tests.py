from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser, HorarioTrabajo
from apps.properties.models import Edificio, Unidad
from apps.tickets.models import Notificacion, Ticket, TicketCategory, TicketPriority, TicketStatus
from apps.tickets.services.availability import find_consecutive_free_blocks, get_hour_blocks_for_day
from apps.tickets.services.transitions import transition_ticket


def _make_inquilino_con_unidad(email='residente@test.com'):
    inquilino = CustomUser.objects.create_user(
        email=email, password='clave12345', first_name='Ana', last_name='Residente',
        role=CustomUser.Roles.INQUILINO,
    )
    edificio = Edificio.objects.create(
        nombre='Torre Test', codigo=f'TT-{email[:3].upper()}', direccion='Calle Falsa 123',
    )
    Unidad.objects.create(edificio=edificio, numero='101', inquilino=inquilino)
    return inquilino


@pytest.mark.django_db
class TestTicketCreatedNotificationTiming:
    def test_creating_a_ticket_does_not_send_any_notification_yet(self):
        inquilino = _make_inquilino_con_unidad()
        client = Client()
        client.force_login(inquilino)

        with patch('apps.ai_agent.tasks.analyze_ticket.apply_async') as mock_analyze, \
             patch('apps.tickets.notifications.notify_nuevo_ticket.delay') as mock_text_email, \
             patch('apps.tickets.services.email_service.send_ticket_created_email') as mock_html_email:
            response = client.post(reverse('ticket_create'), {
                'unidad': inquilino.unidad_asignada.pk,
                'titulo': 'Falla eléctrica en mi dormitorio',
                'descripcion': 'La luz de mi cuarto parpadea y hace un ruido extraño desde hace días.',
            })

        assert response.status_code == 302
        ticket = Ticket.objects.get(inquilino=inquilino)
        assert ticket.estado == TicketStatus.CREADO_PENDIENTE_IA
        assert ticket.categoria == TicketCategory.OTRO
        assert ticket.prioridad == TicketPriority.MEDIA

        mock_analyze.assert_called_once()
        mock_text_email.assert_not_called()
        mock_html_email.assert_not_called()

    def test_pendiente_validacion_sends_notifications_with_final_classification(self):
        inquilino = _make_inquilino_con_unidad(email='residente2@test.com')
        ticket = Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño desde hace días.',
        )
        assert ticket.categoria == TicketCategory.OTRO
        assert ticket.prioridad == TicketPriority.MEDIA

        ticket.categoria = TicketCategory.ELECTRICIDAD
        ticket.prioridad = TicketPriority.ALTA
        ticket.save(update_fields=['categoria', 'prioridad'])

        with patch('apps.tickets.notifications.notify_nuevo_ticket.delay') as mock_text_email, \
             patch('apps.tickets.services.email_service.send_ticket_created_email') as mock_html_email:
            transition_ticket(ticket, nuevo_estado=TicketStatus.PENDIENTE_VALIDACION, actor_role='SYSTEM')

        mock_text_email.assert_called_once_with(ticket.pk)
        mock_html_email.assert_called_once_with(ticket.pk)

        ticket.refresh_from_db()
        assert ticket.categoria == TicketCategory.ELECTRICIDAD
        assert ticket.prioridad == TicketPriority.ALTA


def _make_tecnico_con_horario(email='tecnico@test.com'):
    tecnico = CustomUser.objects.create_user(
        email=email, password='clave12345', first_name='Gabriel', last_name='Jurado',
        role=CustomUser.Roles.TECNICO,
    )
    for dia in range(7):
        HorarioTrabajo.objects.create(
            tecnico=tecnico, dia_semana=dia,
            hora_inicio='08:00', hora_fin='18:00',
        )
    return tecnico


@pytest.mark.django_db
class TestInquilinoScheduleView:

    def test_scheduling_persists_fecha_y_hora_not_none(self):
        tecnico = _make_tecnico_con_horario()
        inquilino = _make_inquilino_con_unidad()
        ticket = Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            categoria=TicketCategory.ELECTRICIDAD,
            prioridad=TicketPriority.ALTA,
            tecnico=tecnico,
        )
        transition_ticket(ticket, nuevo_estado=TicketStatus.ANALIZADO_POR_IA, actor_role='SYSTEM')
        transition_ticket(ticket, nuevo_estado=TicketStatus.PENDIENTE_VALIDACION, actor_role='SYSTEM')
        transition_ticket(ticket, nuevo_estado=TicketStatus.APROBADO, actor_role='ADMIN')

        fecha = timezone.localdate() + timedelta(days=7)
        client = Client()
        client.force_login(inquilino)

        with patch('apps.tickets.services.email_service.send_ticket_scheduled_email'):
            response = client.post(
                reverse('ticket_schedule', kwargs={'pk': ticket.pk}),
                {
                    'fecha_programada': fecha.isoformat(),
                    'hora_programada_inicio': '09:00',
                },
            )

        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.ASIGNADO
        assert ticket.fecha_programada == fecha
        assert ticket.hora_programada_inicio.strftime('%H:%M') == '09:00'
        assert ticket.hora_programada_fin.strftime('%H:%M') == '12:00'

    def test_other_ticket_sees_the_slot_as_occupied(self):
        tecnico = _make_tecnico_con_horario(email='tecnico2@test.com')
        inquilino_a = _make_inquilino_con_unidad(email='residente_a@test.com')
        fecha = timezone.localdate() + timedelta(days=7)

        ticket_a = Ticket.objects.create(
            inquilino=inquilino_a,
            unidad=inquilino_a.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            categoria=TicketCategory.ELECTRICIDAD,
            prioridad=TicketPriority.ALTA,
            tecnico=tecnico,
        )
        transition_ticket(ticket_a, nuevo_estado=TicketStatus.ANALIZADO_POR_IA, actor_role='SYSTEM')
        transition_ticket(ticket_a, nuevo_estado=TicketStatus.PENDIENTE_VALIDACION, actor_role='SYSTEM')
        transition_ticket(ticket_a, nuevo_estado=TicketStatus.APROBADO, actor_role='ADMIN')

        client = Client()
        client.force_login(inquilino_a)
        with patch('apps.tickets.services.email_service.send_ticket_scheduled_email'):
            client.post(
                reverse('ticket_schedule', kwargs={'pk': ticket_a.pk}),
                {'fecha_programada': fecha.isoformat(), 'hora_programada_inicio': '09:00'},
            )

        bloques = get_hour_blocks_for_day(tecnico, fecha)
        estados_por_hora = {b['hora_inicio'].strftime('%H:%M'): b['estado'] for b in bloques}
        assert estados_por_hora['09:00'] == 'ocupado'
        assert estados_por_hora['10:00'] == 'ocupado'
        assert estados_por_hora['11:00'] == 'ocupado'

        grupos_2h = find_consecutive_free_blocks(bloques, cantidad=2)
        horas_inicio_libres = {g[0]['hora_inicio'].strftime('%H:%M') for g in grupos_2h}
        assert '08:00' not in horas_inicio_libres
        assert '09:00' not in horas_inicio_libres
        assert '10:00' not in horas_inicio_libres
        assert '11:00' not in horas_inicio_libres


@pytest.mark.django_db
class TestTicketTransitionViewBlocksGenericBypass:

    def test_inquilino_cannot_reach_asignado_via_generic_transition_endpoint(self):
        tecnico = _make_tecnico_con_horario(email='tecnico3@test.com')
        inquilino = _make_inquilino_con_unidad(email='residente3@test.com')
        ticket = Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            categoria=TicketCategory.ELECTRICIDAD,
            prioridad=TicketPriority.ALTA,
            tecnico=tecnico,
        )
        transition_ticket(ticket, nuevo_estado=TicketStatus.ANALIZADO_POR_IA, actor_role='SYSTEM')
        transition_ticket(ticket, nuevo_estado=TicketStatus.PENDIENTE_VALIDACION, actor_role='SYSTEM')
        transition_ticket(ticket, nuevo_estado=TicketStatus.APROBADO, actor_role='ADMIN')

        client = Client()
        client.force_login(inquilino)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.ASIGNADO}),
        )

        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.APROBADO
        assert ticket.fecha_programada is None
        assert ticket.hora_programada_inicio is None

    def test_tecnico_cannot_reach_resuelto_via_generic_transition_endpoint(self):
        tecnico = _make_tecnico_con_horario(email='tecnico4@test.com')
        inquilino = _make_inquilino_con_unidad(email='residente4@test.com')
        ticket = Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            categoria=TicketCategory.ELECTRICIDAD,
            prioridad=TicketPriority.ALTA,
            tecnico=tecnico,
            estado=TicketStatus.EN_PROGRESO,
        )

        client = Client()
        client.force_login(tecnico)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.RESUELTO}),
        )

        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.EN_PROGRESO

    def test_admin_cannot_reach_aprobado_via_generic_transition_endpoint(self):
        admin = _make_admin(email='admin-bypass@test.com')
        inquilino = _make_inquilino_con_unidad(email='residente-bypass@test.com')
        ticket = Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            estado=TicketStatus.PENDIENTE_VALIDACION,
        )

        client = Client()
        client.force_login(admin)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.APROBADO}),
        )

        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.PENDIENTE_VALIDACION
        assert ticket.tecnico_id is None


def _make_admin(email='admin@test.com'):
    return CustomUser.objects.create_user(
        email=email, password='clave12345', first_name='Ada', last_name='Admin',
        role=CustomUser.Roles.ADMIN,
    )


@pytest.mark.django_db
class TestTicketApprovalDoesNotSendDuplicateEmail:

    def test_approving_sends_exactly_one_email_to_resident_and_one_to_tecnico(self):
        admin = _make_admin()
        tecnico = _make_tecnico_con_horario(email='tecnico5@test.com')
        inquilino = _make_inquilino_con_unidad(email='residente5@test.com')
        ticket = Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
        )
        transition_ticket(ticket, nuevo_estado=TicketStatus.ANALIZADO_POR_IA, actor_role='SYSTEM')
        transition_ticket(ticket, nuevo_estado=TicketStatus.PENDIENTE_VALIDACION, actor_role='SYSTEM')

        client = Client()
        client.force_login(admin)

        with patch('apps.tickets.notifications.notify_nuevo_ticket.delay'), \
             patch('apps.tickets.services.email_service.send_ticket_created_email'), \
             patch(
                 'apps.tickets.services.email_service.send_ticket_approved_resident_email',
             ) as mock_resident_email, \
             patch(
                 'apps.tickets.services.email_service.send_ticket_approved_tech_email',
             ) as mock_tech_email:
            response = client.post(
                reverse('ticket_validate', kwargs={'pk': ticket.pk}),
                {
                    'categoria': TicketCategory.ELECTRICIDAD,
                    'prioridad': TicketPriority.ALTA,
                    'tecnico': tecnico.pk,
                },
            )

        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.APROBADO

        mock_resident_email.assert_called_once_with(ticket.pk)
        mock_tech_email.assert_called_once_with(ticket.pk)

    def test_notify_ticket_aprobado_no_longer_exists(self):
        from apps.tickets import notifications
        assert not hasattr(notifications, 'notify_ticket_aprobado')


@pytest.mark.django_db
class TestPdfReportHidesIaAnalysisFromResident:

    def _ticket_resuelto_con_analisis_ia(self):
        tecnico = _make_tecnico_con_horario(email='tecnico6@test.com')
        inquilino = _make_inquilino_con_unidad(email='residente6@test.com')
        return Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            categoria=TicketCategory.ELECTRICIDAD,
            prioridad=TicketPriority.ALTA,
            tecnico=tecnico,
            estado=TicketStatus.RESUELTO,
            ia_descripcion_tecnica='Posible falla en el balastro del fluorescente.',
            notas_resolucion='Se reemplazó el balastro dañado y se probó el circuito.',
        )

    def _render(self, ticket, *, is_audit):
        from django.template.loader import render_to_string
        return render_to_string('tickets/pdf/ticket_report.html', {
            'ticket': ticket,
            'edificio': ticket.unidad.edificio,
            'unidad': ticket.unidad,
            'inquilino': ticket.inquilino,
            'tecnico': ticket.tecnico,
            'evidencias_reporte': [],
            'evidencias_resolucion': [],
            'historial': list(ticket.historial.all()) if is_audit else [],
            'is_audit': is_audit,
            'fecha_generacion': timezone.now(),
        })

    def test_resident_pdf_does_not_include_ia_analysis(self):
        ticket = self._ticket_resuelto_con_analisis_ia()
        html = self._render(ticket, is_audit=False)
        assert 'Análisis Técnico IA' not in html
        assert ticket.ia_descripcion_tecnica not in html

    def test_admin_pdf_still_includes_ia_analysis(self):
        ticket = self._ticket_resuelto_con_analisis_ia()
        html = self._render(ticket, is_audit=True)
        assert 'Análisis Técnico IA' in html
        assert ticket.ia_descripcion_tecnica in html


@pytest.mark.django_db
class TestInquilinoSelfCancel:

    def _ticket_en_estado(self, estado, *, tecnico=None, inquilino=None):
        inquilino = inquilino or _make_inquilino_con_unidad(email='residente7@test.com')
        tecnico = tecnico or _make_tecnico_con_horario(email='tecnico7@test.com')
        return Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            categoria=TicketCategory.ELECTRICIDAD,
            prioridad=TicketPriority.MEDIA,
            tecnico=tecnico,
            estado=estado,
        ), inquilino

    def test_inquilino_can_cancel_from_creado_pendiente_ia(self):
        ticket, inquilino = self._ticket_en_estado(TicketStatus.CREADO_PENDIENTE_IA)
        client = Client()
        client.force_login(inquilino)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.CANCELADO}),
        )
        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.CANCELADO

    def test_inquilino_can_cancel_from_asignado(self):
        ticket, inquilino = self._ticket_en_estado(TicketStatus.ASIGNADO)
        client = Client()
        client.force_login(inquilino)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.CANCELADO}),
        )
        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.CANCELADO

    def test_inquilino_cannot_cancel_once_tecnico_en_camino(self):
        ticket, inquilino = self._ticket_en_estado(TicketStatus.EN_CAMINO)
        client = Client()
        client.force_login(inquilino)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.CANCELADO}),
        )
        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.EN_CAMINO

    def test_inquilino_cannot_cancel_once_en_progreso(self):
        ticket, inquilino = self._ticket_en_estado(TicketStatus.EN_PROGRESO)
        client = Client()
        client.force_login(inquilino)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.CANCELADO}),
        )
        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.EN_PROGRESO

    def test_inquilino_cannot_cancel_ticket_ajeno(self):
        ticket, _dueno = self._ticket_en_estado(TicketStatus.CREADO_PENDIENTE_IA)
        otro_inquilino = _make_inquilino_con_unidad(email='vecino8@test.com')
        client = Client()
        client.force_login(otro_inquilino)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.CANCELADO}),
        )
        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.CREADO_PENDIENTE_IA

    def test_admin_can_still_cancel_from_any_non_terminal_state(self):
        admin = _make_admin(email='admin2@test.com')
        ticket, _inquilino = self._ticket_en_estado(TicketStatus.EN_PROGRESO)
        client = Client()
        client.force_login(admin)
        response = client.post(
            reverse('ticket_transition', kwargs={'pk': ticket.pk, 'destino': TicketStatus.CANCELADO}),
        )
        assert response.status_code == 302
        ticket.refresh_from_db()
        assert ticket.estado == TicketStatus.CANCELADO


@pytest.mark.django_db
class TestChatMessageDoesNotNotifyAdmin:
    """Regresión: `notify_new_message` agregaba siempre a `_get_admins()`
    como destinatario sin importar quién escribiera, pero el chat de un
    ticket (`MensajeCreateView.puede`) es exclusivamente entre el
    inquilino y el técnico asignado — el admin nunca puede enviar ni
    debería figurar ahí. Con eso, cada mensaje del chat le generaba al
    admin una campanita de "nuevo mensaje" sobre una conversación en la
    que no participa.
    """

    def _ticket_asignado(self):
        tecnico = _make_tecnico_con_horario(email='tecnico-chat@test.com')
        inquilino = _make_inquilino_con_unidad(email='residente-chat@test.com')
        ticket = Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            categoria=TicketCategory.ELECTRICIDAD,
            prioridad=TicketPriority.ALTA,
            tecnico=tecnico,
            estado=TicketStatus.ASIGNADO,
        )
        return ticket, inquilino, tecnico

    def test_inquilino_message_notifies_tecnico_but_not_admin(self):
        admin = _make_admin(email='admin-chat@test.com')
        ticket, inquilino, tecnico = self._ticket_asignado()

        client = Client()
        client.force_login(inquilino)
        response = client.post(
            reverse('ticket_mensaje_create', kwargs={'pk': ticket.pk}),
            {'mensaje': 'Hola, ¿a qué hora llega el técnico?'},
        )

        assert response.status_code == 302
        assert Notificacion.objects.filter(usuario=tecnico, ticket=ticket).exists()
        assert not Notificacion.objects.filter(usuario=admin, ticket=ticket).exists()

    def test_tecnico_message_notifies_inquilino_but_not_admin(self):
        admin = _make_admin(email='admin-chat2@test.com')
        ticket, inquilino, tecnico = self._ticket_asignado()

        client = Client()
        client.force_login(tecnico)
        response = client.post(
            reverse('ticket_mensaje_create', kwargs={'pk': ticket.pk}),
            {'mensaje': 'Llego en 20 minutos.'},
        )

        assert response.status_code == 302
        assert Notificacion.objects.filter(usuario=inquilino, ticket=ticket).exists()
        assert not Notificacion.objects.filter(usuario=admin, ticket=ticket).exists()
