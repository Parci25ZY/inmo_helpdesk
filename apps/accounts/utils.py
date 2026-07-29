from datetime import datetime
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

""" Valida que una cédula ecuatoriana sea válida según el algoritmo del módulo 10.
 - Debe tener exactamente 10 dígitos numéricos.
 - Los dos primeros dígitos deben representar una provincia válida (01–24 o 30).
 - El último dígito debe coincidir con el dígito verificador calculado.  """
def valida_cedula(value):
    cedula = str(value).strip()

    if not cedula or cedula == 'None':
        return

    if not cedula.isdigit():
        raise ValidationError('La cédula debe contener solo números.')

    if len(cedula) != 10:
        raise ValidationError('La cédula debe tener exactamente 10 dígitos.')

    provincia = int(cedula[:2])
    if provincia < 1 or (provincia > 24 and provincia != 30):
        raise ValidationError('El código de provincia en la cédula no es válido.')

    coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = 0

    for i in range(9):
        digito = int(cedula[i])
        producto = digito * coeficientes[i]
        if producto > 9:
            producto -= 9
        total += producto

    digito_verificador = (10 - (total % 10)) % 10

    if digito_verificador != int(cedula[9]):
        raise ValidationError('La cédula ingresada no es válida.')
    
phone_validator = RegexValidator(
        regex=r'^(0[2-9]\d{7,8})$',
        message="Ingrese un número de teléfono válido (por ejemplo: 0991234567 o 042345678)."
    )

def custom_serializer(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")