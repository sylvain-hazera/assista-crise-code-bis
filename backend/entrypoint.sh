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
    User.objects.create_superuser('admin', '', 'admin')
    print("Superuser 'admin' created successfully!")
else:
    print("'admin' superuser already exists.")
EOF


echo "Starting server..."
exec "$@"