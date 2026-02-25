#!/bin/bash

set -e

echo "Applying database migrations..."
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

types_evenements = [
    'Incendie', 
    'Inondation', 
    'Accident', 
    'Catastrophe naturelle', 
    'Urgence médicale', 
    'Autre'
]

print("Creating Event Types...")
for t in types_evenements:
    TypeDemande.objects.get_or_create(type=t)

EOF

echo "Starting server..."
exec "$@"