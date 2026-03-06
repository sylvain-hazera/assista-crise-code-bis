#!/bin/bash

set -e

echo "Applying database migrations..."
python manage.py makemigrations --noinput
python manage.py migrate --noinput

echo "Creating superuser 'admin' if it does not exist..."
python manage.py shell <<EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    admin = User.objects.create_user(
        username='admin',
        email='admin@admin.com',
        password='admin',
        type='ADMIN',
        enabled=True,
        is_superuser=True,
        is_staff=True
    )
    print("Superuser 'admin' created successfully with type ADMIN!")
else:
    # Mettre à jour le type si l'utilisateur existe déjà
    admin = User.objects.get(username='admin')
    if admin.type != 'ADMIN':
        admin.type = 'ADMIN'
        admin.save()
        print("'admin' superuser type updated to ADMIN.")
    else:
        print("'admin' superuser already exists.")
EOF


echo "Creating default Request Types..."
python manage.py shell <<EOF
from core.models import RequestType, OfferType, InformationType 

types_demandes = [
    'Assistance immédiate',
    'Hébergement',
    'Nourriture et eau',
    'Soins médicaux',
    'Transport',
    'Matériel',
    'Soutien psychologique',
    'Autre'
]

types_offres = [
    'Assistance immédiate',
    'Hébergement',
    'Nourriture et eau',
    'Soins médicaux',
    'Transport',
    'Matériel',
    'Soutien psychologique',
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

echo "Starting server..."
exec "$@"