"""Tests para apps/tickets.

Cubre la corrección de un bug real: las notificaciones de "nuevo ticket"
(in-app + los dos correos) se enviaban al crear el ticket, cuando
`categoria`/`prioridad` todavía eran el default del modelo (OTRO/MEDIA)
porque la IA aún no lo había clasificado — el correo mostraba una
prioridad distinta a la que luego se veía en el detalle del ticket.
Ahora esas notificaciones se disparan en PENDIENTE_VALIDACION, cuando ya
reflejan la clasificación final.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser, HorarioTrabajo
from apps.properties.models import Edificio, Unidad
from apps.tickets.models import Ticket, TicketCategory, TicketPriority, TicketStatus
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
        # En este punto la IA todavía no corrió: valores por defecto del modelo.
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

        # Simula lo que hace _run_ticket_analysis: clasifica y luego transiciona.
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
    # Horario amplio los 7 días para no depender de en qué día de la
    # semana caiga "mañana" al correr el test.
    for dia in range(7):
        HorarioTrabajo.objects.create(
            tecnico=tecnico, dia_semana=dia,
            hora_inicio='08:00', hora_fin='18:00',
        )
    return tecnico


@pytest.mark.django_db
class TestInquilinoScheduleView:
    """Regresión: al agendar, el ticket quedaba en ASIGNADO pero con
    fecha_programada/hora_programada_inicio/hora_programada_fin en None
    (confirmado en la base de datos real: TKT-0001). La causa era que
    form.save(commit=False) devuelve la MISMA instancia de `ticket`, así
    que el ticket.refresh_from_db() posterior borraba esos valores antes
    de poder persistirlos — y como quedaban en None, ningún otro ticket
    con el mismo técnico detectaba el conflicto de horario.
    """

    def test_scheduling_persists_fecha_y_hora_not_none(self):
        tecnico = _make_tecnico_con_horario()
        inquilino = _make_inquilino_con_unidad()
        ticket = Ticket.objects.create(
            inquilino=inquilino,
            unidad=inquilino.unidad_asignada,
            titulo='Falla eléctrica en mi dormitorio',
            descripcion='La luz de mi cuarto parpadea y hace un ruido extraño.',
            categoria=TicketCategory.ELECTRICIDAD,
            prioridad=TicketPriority.ALTA,  # duración 3h
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
        # Antes del fix, estos tres quedaban en None a pesar de que el
        # historial ya mostraba el texto con la fecha/hora correctas.
        assert ticket.fecha_programada == fecha
        assert ticket.hora_programada_inicio.strftime('%H:%M') == '09:00'
        assert ticket.hora_programada_fin.strftime('%H:%M') == '12:00'  # ALTA = 3h

    def test_other_ticket_sees_the_slot_as_occupied(self):
        """El escenario reportado: un segundo ticket con el mismo técnico
        debe ver el horario ya agendado como ocupado, no como libre."""
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

        # Ticket A agendado 09:00-12:00. Un segundo ticket (otro inquilino,
        # mismo técnico, prioridad MEDIA → 2h) consulta la disponibilidad
        # de ese mismo día.
        bloques = get_hour_blocks_for_day(tecnico, fecha)
        estados_por_hora = {b['hora_inicio'].strftime('%H:%M'): b['estado'] for b in bloques}
        assert estados_por_hora['09:00'] == 'ocupado'
        assert estados_por_hora['10:00'] == 'ocupado'
        assert estados_por_hora['11:00'] == 'ocupado'

        grupos_2h = find_consecutive_free_blocks(bloques, cantidad=2)
        horas_inicio_libres = {g[0]['hora_inicio'].strftime('%H:%M') for g in grupos_2h}
        # Ninguno de estos slots debería ofrecerse: todos se solapan con 09:00-12:00.
        assert '08:00' not in horas_inicio_libres
        assert '09:00' not in horas_inicio_libres
        assert '10:00' not in horas_inicio_libres
        assert '11:00' not in horas_inicio_libres


@pytest.mark.django_db
class TestTicketTransitionViewBlocksGenericBypass:
    """Regresión: `TicketTransitionView` es un endpoint genérico
    (`/tickets/<pk>/transicion/<destino>/`) y `_ROLE_RULES` permite a
    INQUILINO ejecutar APROBADO→ASIGNADO — pero esa transición solo debe
    hacerse vía `InquilinoScheduleView`, que exige fecha/hora. La plantilla
    ocultaba el botón genérico solo para el admin (`request.user.is_admin`),
    así que un inquilino SÍ veía y podía enviar el formulario genérico,
    dejando el ticket en ASIGNADO con fecha_programada/hora_programada_inicio
    en None (el mismo bug de datos que TestInquilinoScheduleView, pero
    alcanzable directamente sin pasar por el schedule picker).
    """

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
        # El bloqueo debe impedir la transición por completo, sin dejar
        # el ticket a medio agendar.
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
        # Sin este bloqueo, el ticket pasaría a RESUELTO sin evidencia
        # ni notas de resolución (solo exigidas por TicketResolveView).
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
        # transition_ticket() solo valida técnico/carga de trabajo para el
        # destino ASIGNADO, no para APROBADO — sin este bloqueo, este POST
        # dejaría el ticket en APROBADO sin categoría, prioridad ni técnico
        # asignado, saltándose por completo TicketAdminValidateForm.
        assert ticket.estado == TicketStatus.PENDIENTE_VALIDACION
        assert ticket.tecnico_id is None


def _make_admin(email='admin@test.com'):
    return CustomUser.objects.create_user(
        email=email, password='clave12345', first_name='Ada', last_name='Admin',
        role=CustomUser.Roles.ADMIN,
    )


@pytest.mark.django_db
class TestTicketApprovalDoesNotSendDuplicateEmail:
    """Regresión: al aprobar un ticket, `TicketValidateView` disparaba DOS
    correos distintos al mismo residente para el mismo evento —
    `notify_ticket_aprobado` (Celery, texto plano) y
    `send_ticket_approved_resident_email` (HTML) — porque ambos se llamaban
    desde el mismo `form_valid()`. Se eliminó el primero (era exactamente
    el mismo aviso, solo que sin formato) dejando un único envío por evento.
    """

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

        # Exactamente una vez cada uno — no dos correos por el mismo evento.
        mock_resident_email.assert_called_once_with(ticket.pk)
        mock_tech_email.assert_called_once_with(ticket.pk)

    def test_notify_ticket_aprobado_no_longer_exists(self):
        """La tarea duplicada se eliminó por completo, no solo se dejó de llamar."""
        from apps.tickets import notifications
        assert not hasattr(notifications, 'notify_ticket_aprobado')


@pytest.mark.django_db
class TestPdfReportHidesIaAnalysisFromResident:
    """Regresión: `ticket_report.html` mostraba la sección "Análisis Técnico
    IA" (``ticket.ia_descripcion_tecnica``) sin condicionar a ``is_audit`` —
    el residente veía en su PDF de garantía exactamente el análisis interno
    de la IA que la web le oculta deliberadamente (panel "Análisis IA").
    """

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
    """El residente ahora puede cancelar su propio ticket, pero solo hasta
    ASIGNADO — una vez que el técnico está en camino o trabajando
    (EN_CAMINO/EN_PROGRESO), cancelar requiere coordinarse con el admin.
    """

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
        # El bloqueo debe impedir la cancelación por completo.
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
        """El chequeo de pertenencia sigue vigente: no puede cancelar el
        ticket de OTRO residente aunque el estado sí sea cancelable."""
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
        """Regresión: el admin sigue pudiendo cancelar sin importar el
        estado (comportamiento previo, no debe romperse)."""
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
