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
    User.objects.create_superuser('admin', 'admin@admin.com', 'admin')
    print("Superuser 'admin' created successfully!")
else:
    print("'admin' superuser already exists.")
EOF


echo "Creating default Request Types..."
python manage.py shell <<EOF
from core.models import TypeDemande, TypeOffre, TypeInformation 

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

print("Creating TypeDemande...")
for t in types_demandes:
    TypeDemande.objects.get_or_create(type=t)
    print(f"  - {t}")

print("Creating TypeOffre...")
for t in types_offres:
    TypeOffre.objects.get_or_create(type=t)
    print(f"  - {t}")

print("Creating TypeInformation...")
for t in types_informations:
    TypeInformation.objects.get_or_create(type=t)
    print(f"  - {t}")

EOF

echo "Starting server..."
exec "$@"