from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UserChangeForm
from .models import CustomUser


class RequiredNameMixin:
    """Exige nombre y apellido no vacíos aunque el modelo los declare blank=True."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True

    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name', '').strip()
        if not first_name:
            raise forms.ValidationError('El nombre es obligatorio.')
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name', '').strip()
        if not last_name:
            raise forms.ValidationError('El apellido es obligatorio.')
        return last_name


class CustomUserCreationForm(RequiredNameMixin, UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'email', 'phone', 'role')

class CustomAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(widget=forms.EmailInput(attrs={
        'placeholder': 'Correo Electrónico',
        'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Contraseña',
        'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
    }))

class UserEditForm(RequiredNameMixin, UserChangeForm):
    """Formulario para editar usuarios existentes en el panel administrativo"""
    password = None  # Ocultar el campo de contraseña en la edición directa

    especialidades = forms.MultipleChoiceField(
        choices=CustomUser.Especialidad.choices,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-checkbox h-4 w-4 text-amber-500',
        }),
        required=False,
        label='Especialidades',
    )

    horario_dias = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate especialidades from M2M
        if self.instance and self.instance.pk and self.instance.is_tecnico:
            self.fields['especialidades'].initial = list(
                self.instance.especialidades_tecnico
                .values_list('especialidad', flat=True)
            )

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'cedula', 'phone', 'role', 'especialidad', 'is_active', 'is_staff']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Nombres'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Apellidos'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Correo Electrónico'
            }),
            'cedula': forms.TextInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Cédula (10 dígitos)',
                'maxlength': '10',
                'inputmode': 'numeric',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Teléfono'
            }),
            'role': forms.Select(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-primary'
            }),
            'is_staff': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-primary'
            }),
            'especialidad': forms.Select(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal'
            }),
        }

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.is_tecnico:
            self._save_especialidades(user)
            self._save_horarios(user)
        return user

    def _save_especialidades(self, user):
        from apps.accounts.models import TecnicoEspecialidad

        especialidades = self.cleaned_data.get('especialidades', [])
        TecnicoEspecialidad.objects.filter(tecnico=user).delete()
        for i, esp in enumerate(especialidades):
            TecnicoEspecialidad.objects.create(
                tecnico=user,
                especialidad=esp,
                es_principal=(i == 0),
            )
        if especialidades:
            user.especialidad = especialidades[0]
            user.save(update_fields=['especialidad'])

    def _save_horarios(self, user):
        import json
        from apps.accounts.models import HorarioTrabajo

        horario_json = self.cleaned_data.get('horario_dias', '')
        if not horario_json:
            return

        try:
            horarios = json.loads(horario_json)
        except (json.JSONDecodeError, TypeError):
            return

        HorarioTrabajo.objects.filter(tecnico=user).delete()
        for h in horarios:
            if h.get('hora_inicio') and h.get('hora_fin'):
                HorarioTrabajo.objects.create(
                    tecnico=user,
                    dia_semana=h['dia'],
                    hora_inicio=h['hora_inicio'],
                    hora_fin=h['hora_fin'],
                )

_INPUT_CLASS = (
    'w-full bg-transparent border-0 border-b-2 border-zinc-200 py-3 px-0 '
    'text-base font-medium text-zinc-900 placeholder-zinc-400 outline-none '
    'focus:border-zinc-900 transition-colors duration-200'
)
_SELECT_CLASS = (
    'w-full bg-white border border-zinc-200 rounded py-3 px-3 '
    'text-base font-medium text-zinc-900 outline-none '
    'focus:border-zinc-900 transition-colors duration-200'
)

class UserCreateForm(RequiredNameMixin, UserCreationForm):
    """Formulario para crear nuevos usuarios en el panel administrativo"""

    especialidades = forms.MultipleChoiceField(
        choices=CustomUser.Especialidad.choices,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-checkbox h-4 w-4 text-amber-500',
        }),
        required=False,
        label='Especialidades',
        help_text='Selecciona las especialidades del técnico.',
    )

    # Horarios de trabajo — campos dinámicos procesados en la vista
    horario_dias = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        help_text='JSON con los horarios semanales.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget = forms.PasswordInput(attrs={
            'class': _INPUT_CLASS,
            'placeholder': '••••••••••',
        })
        self.fields['password2'].widget = forms.PasswordInput(attrs={
            'class': _INPUT_CLASS,
            'placeholder': '••••••••••',
        })

    class Meta:
        model = CustomUser
        fields = ['email', 'first_name', 'last_name', 'cedula', 'phone', 'role', 'especialidad']
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'correo@ejemplo.com',
            }),
            'first_name': forms.TextInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'Ej. Carlos',
            }),
            'last_name': forms.TextInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'Ej. Ramírez',
            }),
            'cedula': forms.TextInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'Ej. 1712345678',
                'maxlength': '10',
                'inputmode': 'numeric',
            }),
            'phone': forms.TextInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'Ej. 0991234567',
            }),
            'role': forms.Select(attrs={
                'class': _SELECT_CLASS,
            }),
            'especialidad': forms.Select(attrs={
                'class': _SELECT_CLASS,
            }),
        }

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.is_tecnico:
            self._save_especialidades(user)
            self._save_horarios(user)
        return user

    def _save_especialidades(self, user):
        import json
        from apps.accounts.models import TecnicoEspecialidad

        especialidades = self.cleaned_data.get('especialidades', [])
        # Clear existing M2M
        TecnicoEspecialidad.objects.filter(tecnico=user).delete()
        for i, esp in enumerate(especialidades):
            TecnicoEspecialidad.objects.create(
                tecnico=user,
                especialidad=esp,
                es_principal=(i == 0),
            )
        # Update legacy field with first specialty
        if especialidades:
            user.especialidad = especialidades[0]
            user.save(update_fields=['especialidad'])

    def _save_horarios(self, user):
        import json
        from apps.accounts.models import HorarioTrabajo

        horario_json = self.cleaned_data.get('horario_dias', '')
        if not horario_json:
            return

        try:
            horarios = json.loads(horario_json)
        except (json.JSONDecodeError, TypeError):
            return

        # Clear existing schedules
        HorarioTrabajo.objects.filter(tecnico=user).delete()
        for h in horarios:
            if h.get('hora_inicio') and h.get('hora_fin'):
                HorarioTrabajo.objects.create(
                    tecnico=user,
                    dia_semana=h['dia'],
                    hora_inicio=h['hora_inicio'],
                    hora_fin=h['hora_fin'],
                )


_PROFILE_INPUT_CLASS = (
    'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden '
    'rounded-lg text-text-dark dark:text-text-light focus:outline-0 '
    'focus:ring-2 focus:ring-primary/50 border border-zinc-300 '
    'dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 '
    'placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 '
    'text-base font-normal'
)


class ProfileEditForm(RequiredNameMixin, forms.ModelForm):
    """Formulario seguro para que el usuario edite su propio perfil.

    Solo expone campos de información personal (nombre, email, teléfono).
    No incluye role, is_active, is_staff ni especialidad para evitar
    escalación de privilegios.
    """

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'phone']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': _PROFILE_INPUT_CLASS,
                'placeholder': 'Nombres',
            }),
            'last_name': forms.TextInput(attrs={
                'class': _PROFILE_INPUT_CLASS,
                'placeholder': 'Apellidos',
            }),
            'email': forms.EmailInput(attrs={
                'class': _PROFILE_INPUT_CLASS,
                'placeholder': 'Correo Electrónico',
            }),
            'phone': forms.TextInput(attrs={
                'class': _PROFILE_INPUT_CLASS,
                'placeholder': 'Teléfono',
            }),
        }

