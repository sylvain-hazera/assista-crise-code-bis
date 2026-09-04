#!/bin/bash

set -e

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Creating initial superuser from DJANGO_SUPERUSER_EMAIL/DJANGO_SUPERUSER_PASSWORD if provided..."
python manage.py shell <<EOF
import os
from django.contrib.auth import get_user_model
User = get_user_model()

email = os.environ.get('DJANGO_SUPERUSER_EMAIL')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

if not email or not password:
    print("DJANGO_SUPERUSER_EMAIL/DJANGO_SUPERUSER_PASSWORD non fournis : aucun admin "
          "par défaut créé. Utilisez 'manage.py createsuperuser' pour créer le premier "
          "compte administrateur.")
elif User.objects.filter(email__iexact=email).exists():
    print(f"Un compte existe déjà pour {email}, aucune création.")
else:
    User.objects.create_user(
        username=email,
        email=email,
        password=password,
        type='ADMIN',
        enabled=True,
        is_superuser=True,
        is_staff=True
    )
    print(f"Superuser '{email}' created successfully with type ADMIN!")
EOF


echo "Creating default Request Types..."
python manage.py shell <<EOF
from core.models import RequestType, OfferType, InformationType 

types_demandes = [
    'Assistance à évacuation',
    'Hébergement',
    'Nourriture et eau',
    'Transport',
    'Matériel',
    'Soutien psychologique',
    'Autre'
]

types_offres = [
    'Hébergement',
    'Nourriture et eau',
    'Soins médicaux et paramédicaux',
    'Transport',
    'Matériel',
    'Soutien psychologique',
    'Bénévolat',
    'Autre'
]

types_informations = [
    'Information utile',
    'Danger imminent',
    'Autre'
]

print("Creating RequestType...")
for t in types_demandes:
    RequestType.objects.get_or_create(type=t)
    print(f"  - {t}")

print("Creating OfferType...")
for t in types_offres:
    OfferType.objects.get_or_create(type=t)
    print(f"  - {t}")

print("Creating InformationType...")
for t in types_informations:
    InformationType.objects.get_or_create(type=t)
    print(f"  - {t}")

EOF

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting server..."
exec "$@"
