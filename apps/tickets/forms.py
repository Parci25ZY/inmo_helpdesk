"""Formularios del módulo Tickets.

Cada formulario está pensado para un rol/contexto específico:

* :class:`TicketCreateForm` — el residente reporta un nuevo ticket.
* :class:`TicketAdminValidateForm` — el administrador valida la sugerencia
  IA y asigna técnico (transición PENDIENTE_VALIDACION → ASIGNADO).
* :class:`TicketTransitionForm` — wrapper genérico para añadir notas a
  cualquier transición de estado.
* :class:`MensajeForm` — mensaje en el hilo de comunicación técnico ↔ residente.
"""

from __future__ import annotations

from django import forms

from apps.accounts.models import CustomUser
from apps.properties.models import Unidad

from .models import MensajeTicket, Ticket, TicketCategory, TicketPriority

INPUT_CLASS = (
    'w-full bg-transparent border-0 border-b-2 border-zinc-200 py-3 px-0 '
    'text-base font-medium text-zinc-900 placeholder-zinc-300 outline-none '
    'focus:border-zinc-900 transition-colors duration-200'
)
SELECT_CLASS = (
    'w-full bg-white border border-zinc-200 rounded py-3 px-3 '
    'text-base font-medium text-zinc-900 outline-none '
    'focus:border-zinc-900 transition-colors duration-200'
)
TEXTAREA_CLASS = INPUT_CLASS + ' min-h-[140px] resize-y'


class TicketCreateForm(forms.ModelForm):
    """Formulario público para creación de tickets por parte del residente."""

    def __init__(self, *args, inquilino=None, **kwargs):
        super().__init__(*args, **kwargs)
        if inquilino is not None:
            unidad = getattr(inquilino, 'unidad_asignada', None)
            if unidad is not None:
                self.fields['unidad'].queryset = Unidad.objects.filter(pk=unidad.pk)
                self.fields['unidad'].initial = unidad.pk
            else:
                self.fields['unidad'].queryset = Unidad.objects.none()

    class Meta:
        model = Ticket
        fields = ['unidad', 'titulo', 'descripcion']
        widgets = {
            'unidad': forms.Select(attrs={'class': SELECT_CLASS}),
            'titulo': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'Ej. Fuga de agua en cocina',
                'maxlength': 200,
            }),
            'descripcion': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'placeholder': 'Describe con detalle qué ocurre, dónde y cuándo empezó.',
                'rows': 5,
            }),
        }


class TicketAdminValidateForm(forms.ModelForm):
    """Formulario que usa el administrador para validar la sugerencia IA.

    El administrador puede:
      * Ajustar categoría / prioridad si discrepa con la IA.
      * Asignar el técnico definitivo (puede aceptar el sugerido).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tecnico'].queryset = CustomUser.objects.filter(
            role=CustomUser.Roles.TECNICO,
            is_active=True,
        ).order_by('first_name')
        self.fields['tecnico'].empty_label = '— Seleccionar técnico —'

    class Meta:
        model = Ticket
        fields = ['categoria', 'prioridad', 'tecnico']
        widgets = {
            'categoria': forms.Select(attrs={'class': SELECT_CLASS}),
            'prioridad': forms.Select(attrs={'class': SELECT_CLASS}),
            'tecnico': forms.Select(attrs={'class': SELECT_CLASS}),
        }


class TicketTransitionForm(forms.Form):
    """Formulario mínimo para cualquier transición que requiera nota."""

    nota = forms.CharField(
        label='Nota (opcional)',
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Detalles relevantes para el historial…',
        }),
    )


class TicketResolutionForm(forms.ModelForm):
    """Form que el técnico envía al cerrar el ticket."""

    class Meta:
        model = Ticket
        fields = ['notas_resolucion']
        widgets = {
            'notas_resolucion': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 5,
                'placeholder': 'Resumen de la intervención, materiales, observaciones.',
            }),
        }


class MensajeForm(forms.ModelForm):
    """Mensaje en el hilo de comunicación técnico ↔ residente."""

    class Meta:
        model = MensajeTicket
        fields = ['mensaje']
        labels = {'mensaje': ''}
        widgets = {
            'mensaje': forms.Textarea(attrs={
                'class': (
                    'w-full border border-zinc-200 bg-white text-sm text-zinc-900 '
                    'px-4 py-3 outline-none focus:border-zinc-900 transition-colors '
                    'resize-none placeholder-zinc-400'
                ),
                'rows': 3,
                'placeholder': 'Escribe un mensaje…',
                'maxlength': 1000,
            }),
        }

