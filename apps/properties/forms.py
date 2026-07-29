from django import forms

from apps.accounts.models import CustomUser

from .models import Edificio, Unidad

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
TEXTAREA_CLASS = INPUT_CLASS + ' min-h-[120px] resize-y'


class EdificioForm(forms.ModelForm):

    class Meta:
        model = Edificio
        fields = ['nombre', 'codigo', 'direccion', 'ciudad', 'descripcion', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Ej. Torres del Norte'}),
            'codigo': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'EDI-A01'}),
            'direccion': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Av. Principal 123'}),
            'ciudad': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Guayaquil'}),
            'descripcion': forms.Textarea(attrs={'class': TEXTAREA_CLASS, 'rows': 3}),
            'activo': forms.CheckboxInput(attrs={'class': 'h-5 w-5 accent-amber-500'}),
        }


class UnidadForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instancia = kwargs.get('instance') or self.instance
        qs = CustomUser.objects.filter(role=CustomUser.Roles.INQUILINO, is_active=True, unidad_asignada__isnull=True)
        if instancia and instancia.pk and instancia.inquilino_id:
            qs = qs | CustomUser.objects.filter(pk=instancia.inquilino_id)
        self.fields['inquilino'].queryset = qs.distinct().order_by('first_name')
        self.fields['inquilino'].empty_label = '— Selecciona un residente —'
        self.fields['inquilino'].required = True
        self.fields['inquilino'].error_messages['required'] = 'Debes asignar un residente a la unidad.'
        self.fields['area_m2'].required = True
        self.fields['area_m2'].error_messages['required'] = 'El área en metros cuadrados es obligatoria.'
        self.fields['piso'].required = True
        self.fields['piso'].error_messages['required'] = 'El piso es obligatorio.'

    class Meta:
        model = Unidad
        fields = ['edificio', 'numero', 'piso', 'tipo', 'area_m2', 'inquilino', 'activo']
        widgets = {
            'edificio': forms.Select(attrs={'class': SELECT_CLASS}),
            'numero': forms.TextInput(attrs={'class': INPUT_CLASS, 'placeholder': 'Ej. 4B'}),
            'piso': forms.NumberInput(attrs={'class': INPUT_CLASS, 'min': 0, 'placeholder': '0'}),
            'tipo': forms.Select(attrs={'class': SELECT_CLASS}),
            'area_m2': forms.NumberInput(attrs={'class': INPUT_CLASS, 'step': '0.01', 'placeholder': '85.50'}),
            'inquilino': forms.Select(attrs={'class': SELECT_CLASS}),
            'activo': forms.CheckboxInput(attrs={'class': 'h-5 w-5 accent-amber-500'}),
        }
