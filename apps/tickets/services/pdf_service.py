
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

if sys.platform == 'win32':
    gtk_path = r'C:\msys64\mingw64\bin'
    if os.path.isdir(gtk_path):
        os.add_dll_directory(gtk_path)

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML

from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)


def _build_file_uri(file_path: Path) -> str:
    try:
        return file_path.as_uri()
    except Exception:
        return 'file:///' + str(file_path).replace('\\', '/')


def generate_ticket_pdf(ticket: Ticket, *, is_audit: bool = False) -> bytes:
    evidencias = ticket.evidencias.select_related('subido_por').all()
    evidencias_reporte = []
    evidencias_resolucion = []

    for ev in evidencias:
        if ev.archivo:
            abs_path = Path(settings.MEDIA_ROOT) / str(ev.archivo)
            ev.archivo_uri = _build_file_uri(abs_path)
        else:
            ev.archivo_uri = None

        if ev.momento == 'REPORTE':
            evidencias_reporte.append(ev)
        else:
            evidencias_resolucion.append(ev)

    historial = []
    if is_audit:
        historial = list(ticket.historial.select_related('actor').all())

    edificio = ticket.unidad.edificio
    unidad = ticket.unidad

    ahora = timezone.localtime(timezone.now())

    context = {
        'ticket': ticket,
        'edificio': edificio,
        'unidad': unidad,
        'inquilino': ticket.inquilino,
        'tecnico': ticket.tecnico,
        'evidencias_reporte': evidencias_reporte,
        'evidencias_resolucion': evidencias_resolucion,
        'historial': historial,
        'is_audit': is_audit,
        'fecha_generacion': ahora,
    }

    html_string = render_to_string('tickets/pdf/ticket_report.html', context)

    html = HTML(
        string=html_string,
        base_url=str(settings.MEDIA_ROOT),
    )
    pdf_bytes = html.write_pdf()

    variant = "auditoría" if is_audit else "garantía"
    logger.info(
        "Reporte PDF (%s) generado para ticket %s (%d bytes)",
        variant, ticket.codigo, len(pdf_bytes),
    )

    return pdf_bytes
