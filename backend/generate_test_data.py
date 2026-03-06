#!/usr/bin/env python
"""
Script pour générer des données de test pour l'application Assista-Crise
Crée des crises, demandes, offres et informations réparties sur toute la France
"""
import os
import sys
import django
import random
from datetime import datetime, timedelta

# Configuration Django
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.gis.geos import Point
from core.models import User, Crisis, Request, Offer, Information, RequestType, OfferType, InformationType, Status

# Villes françaises avec coordonnées GPS (latitude, longitude)
CITIES_FRANCE = [
    # Grandes villes
    {'name': 'Paris', 'lat': 48.8566, 'lon': 2.3522},
    {'name': 'Marseille', 'lat': 43.2965, 'lon': 5.3698},
    {'name': 'Lyon', 'lat': 45.7640, 'lon': 4.8357},
    {'name': 'Toulouse', 'lat': 43.6047, 'lon': 1.4442},
    {'name': 'Nice', 'lat': 43.7102, 'lon': 7.2620},
    {'name': 'Nantes', 'lat': 47.2184, 'lon': -1.5536},
    {'name': 'Strasbourg', 'lat': 48.5734, 'lon': 7.7521},
    {'name': 'Montpellier', 'lat': 43.6108, 'lon': 3.8767},
    {'name': 'Bordeaux', 'lat': 44.8378, 'lon': -0.5792},
    {'name': 'Lille', 'lat': 50.6292, 'lon': 3.0573},
    {'name': 'Rennes', 'lat': 48.1173, 'lon': -1.6778},
    {'name': 'Reims', 'lat': 49.2583, 'lon': 4.0317},
    {'name': 'Le Havre', 'lat': 49.4944, 'lon': 0.1079},
    {'name': 'Saint-Étienne', 'lat': 45.4397, 'lon': 4.3872},
    {'name': 'Toulon', 'lat': 43.1242, 'lon': 5.9280},
    {'name': 'Grenoble', 'lat': 45.1885, 'lon': 5.7245},
    {'name': 'Dijon', 'lat': 47.3220, 'lon': 5.0415},
    {'name': 'Angers', 'lat': 47.4784, 'lon': -0.5632},
    {'name': 'Nîmes', 'lat': 43.8367, 'lon': 4.3601},
    {'name': 'Villeurbanne', 'lat': 45.7667, 'lon': 4.8833},
    {'name': 'Clermont-Ferrand', 'lat': 45.7772, 'lon': 3.0870},
    {'name': 'Le Mans', 'lat': 48.0077, 'lon': 0.1984},
    {'name': 'Aix-en-Provence', 'lat': 43.5297, 'lon': 5.4474},
    {'name': 'Brest', 'lat': 48.3905, 'lon': -4.4861},
    {'name': 'Limoges', 'lat': 45.8336, 'lon': 1.2611},
    {'name': 'Tours', 'lat': 47.3941, 'lon': 0.6848},
    {'name': 'Amiens', 'lat': 49.8941, 'lon': 2.2958},
    {'name': 'Perpignan', 'lat': 42.6886, 'lon': 2.8948},
    {'name': 'Metz', 'lat': 49.1193, 'lon': 6.1757},
    {'name': 'Besançon', 'lat': 47.2380, 'lon': 6.0243},
    {'name': 'Orléans', 'lat': 47.9029, 'lon': 1.9093},
    {'name': 'Rouen', 'lat': 49.4432, 'lon': 1.0993},
    {'name': 'Mulhouse', 'lat': 47.7508, 'lon': 7.3359},
    {'name': 'Caen', 'lat': 49.1829, 'lon': -0.3707},
    {'name': 'Nancy', 'lat': 48.6921, 'lon': 6.1844},
]

# Types de crises
CRISIS_TYPES = [
    'Inondation', 'Incendie', 'Tempête', 'Accident', 'Pollution',
    'Séisme', 'Canicule', 'Froid extrême', 'Panne électrique'
]

# Noms et prénoms français
FIRST_NAMES = [
    'Jean', 'Marie', 'Pierre', 'Sophie', 'Luc', 'Anne', 'Paul', 'Claire',
    'Thomas', 'Julie', 'Nicolas', 'Emma', 'Antoine', 'Camille', 'Alexandre',
    'Laura', 'Julien', 'Sarah', 'Maxime', 'Charlotte', 'Mathieu', 'Léa',
    'Lucas', 'Manon', 'Hugo', 'Chloé', 'Louis', 'Marine', 'Arthur', 'Pauline'
]

LAST_NAMES = [
    'Martin', 'Bernard', 'Dubois', 'Thomas', 'Robert', 'Richard', 'Petit',
    'Durand', 'Leroy', 'Moreau', 'Simon', 'Laurent', 'Lefebvre', 'Michel',
    'Garcia', 'David', 'Bertrand', 'Roux', 'Vincent', 'Fournier', 'Morel',
    'Girard', 'André', 'Lefèvre', 'Mercier', 'Dupont', 'Lambert', 'Bonnet'
]

def random_date_recent(days_back=30):
    """Génère une date aléatoire dans les N derniers jours"""
    now = datetime.now()
    random_days = random.randint(0, days_back)
    return now - timedelta(days=random_days)

def random_date_future(days_ahead=60):
    """Génère une date aléatoire dans les N prochains jours"""
    now = datetime.now()
    random_days = random.randint(1, days_ahead)
    return now + timedelta(days=random_days)

def create_admin_user():
    """Crée ou récupère l'utilisateur admin"""
    admin_email = 'admin@admin.com'
    try:
        user = User.objects.get(email=admin_email)
        print(f"[OK] Utilisateur admin existant: {admin_email}")
    except User.DoesNotExist:
        user = User.objects.create_user(
            username='admin',
            email=admin_email,
            password='admin',
            first_name='Admin',
            last_name='System',
            type='ADMIN',
            enabled=True
        )
        print(f"[OK] Utilisateur admin créé: {admin_email}")
    return user

def create_test_users(count=10):
    """Crée des utilisateurs de test"""
    users = [create_admin_user()]
    
    for i in range(count):
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        username = f"{first_name.lower()}{i}"
        email = f"{username}@test.fr"
        
        # Essayer de récupérer par username plutôt que par email
        user = User.objects.filter(username=username).first()
        if not user:
            user = User.objects.create_user(
                username=username,
                email=email,
                password='test123',
                first_name=first_name,
                last_name=last_name,
                type=random.choice(['SIMPLE_USER', 'LOCAL_AUTH', 'RESCUE']),
                enabled=True,
                phone_number=f"06{random.randint(10000000, 99999999)}"
            )
        users.append(user)
    
    print(f"[OK] {len(users)} utilisateurs disponibles")
    return users

def create_crises(users, count=15):
    """Crée des crises réparties en France"""
    crises = []
    
    for i in range(count):
        city = random.choice(CITIES_FRANCE)
        # Ajouter un peu de variation aux coordonnées (rayon de ~5km)
        lat = city['lat'] + random.uniform(-0.05, 0.05)
        lon = city['lon'] + random.uniform(-0.05, 0.05)
        
        crisis_type = random.choice(CRISIS_TYPES)
        
        crisis = Crisis.objects.create(
            name=f"{crisis_type} - {city['name']}",
            type=crisis_type,
            description=f"Situation d'urgence nécessitant une intervention. {crisis_type} signalé dans la région de {city['name']}.",
            location=Point(lon, lat),
            start_date=random_date_recent(10),
            end_date=random_date_future(30) if random.random() > 0.3 else None,
            author=random.choice(users)
        )
        crises.append(crisis)
    
    print(f"[OK] {len(crises)} crises créées")
    return crises

def create_requests(users, crises, count=50):
    """Crée des demandes d'aide"""
    request_types = list(RequestType.objects.all())
    if not request_types:
        print("[WARN] Aucun type de demande trouvé")
        return []
    
    requests = []
    
    request_templates = [
        "Besoin urgent de {} pour une famille de {} personnes",
        "{} nécessaire pour {} personnes bloquées",
        "Recherche {} pour {} personnes en détresse",
        "Demande d'aide: {} pour {} personnes",
        "{} requis d'urgence pour {} personnes",
    ]
    
    for i in range(count):
        city = random.choice(CITIES_FRANCE)
        lat = city['lat'] + random.uniform(-0.05, 0.05)
        lon = city['lon'] + random.uniform(-0.05, 0.05)
        
        req_type = random.choice(request_types)
        nb_people = random.randint(1, 8)
        
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        
        title = random.choice(request_templates).format(req_type.type, nb_people)
        
        request = Request.objects.create(
            title=title,
            location=Point(lon, lat),
            request_type=req_type,
            first_name_request=first_name,
            last_name_request=last_name,
            email_request=f"{first_name.lower()}.{last_name.lower()}@email.fr",
            phone_request=f"06{random.randint(10000000, 99999999)}",
            status=Status.UNPROCESSED,
            created_at=random_date_recent(20),
            expires_at=random_date_future(40),
            author=random.choice(users),
            crisis=random.choice(crises) if crises and random.random() > 0.3 else None
        )
        requests.append(request)
    
    print(f"[OK] {len(requests)} demandes créées")
    return requests

def create_offers(users, crises, count=50):
    """Crée des offres d'aide"""
    offer_types = list(OfferType.objects.all())
    if not offer_types:
        print("[WARN] Aucun type d'offre trouvé")
        return []
    
    offers = []
    
    offer_templates = [
        "Je propose {} - Disponible immédiatement",
        "Offre de {} dans ma région",
        "{} disponible - Contactez-moi",
        "Aide proposée: {}",
        "Je peux fournir {} pour les personnes dans le besoin",
    ]
    
    for i in range(count):
        city = random.choice(CITIES_FRANCE)
        lat = city['lat'] + random.uniform(-0.05, 0.05)
        lon = city['lon'] + random.uniform(-0.05, 0.05)
        
        off_type = random.choice(offer_types)
        
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        
        title = random.choice(offer_templates).format(off_type.type)
        
        offer = Offer.objects.create(
            title=title,
            location=Point(lon, lat),
            offer_type=off_type,
            first_name_offer=first_name,
            last_name_offer=last_name,
            email_offer=f"{first_name.lower()}.{last_name.lower()}@email.fr",
            status=Status.UNPROCESSED,
            created_at=random_date_recent(20),
            author=random.choice(users),
            crisis=random.choice(crises) if crises and random.random() > 0.3 else None
        )
        offers.append(offer)
    
    print(f"[OK] {len(offers)} offres créées")
    return offers

def create_informations(users, crises, count=30):
    """Crée des informations"""
    info_types = list(InformationType.objects.all())
    if not info_types:
        print("[WARN] Aucun type d'information trouvé")
        return []
    
    informations = []
    
    info_templates = [
        "Information importante: {}",
        "Alerte: {}",
        "Mise à jour: {}",
        "Avis à la population: {}",
        "Communication urgente: {}",
    ]
    
    for i in range(count):
        city = random.choice(CITIES_FRANCE)
        lat = city['lat'] + random.uniform(-0.05, 0.05)
        lon = city['lon'] + random.uniform(-0.05, 0.05)
        
        info_type = random.choice(info_types)
        
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        
        title = random.choice(info_templates).format(info_type.type)
        
        info = Information.objects.create(
            title=title,
            location=Point(lon, lat),
            information_type=info_type,
            first_name_information=first_name,
            last_name_information=last_name,
            email_information=f"{first_name.lower()}.{last_name.lower()}@email.fr",
            phone_information=f"06{random.randint(10000000, 99999999)}",
            status=Status.UNPROCESSED,
            created_at=random_date_recent(15),
            author=random.choice(users),
            crisis=random.choice(crises) if crises and random.random() > 0.4 else None
        )
        informations.append(info)
    
    print(f"[OK] {len(informations)} informations créées")
    return informations

def main():
    print("\n" + "="*60)
    print("Génération de données de test pour Assista-Crise")
    print("="*60 + "\n")
    
    # Créer les utilisateurs
    print("[1/5] Création des utilisateurs...")
    users = create_test_users(10)
    
    # Créer les crises
    print("\n[2/5] Création des crises...")
    crises = create_crises(users, 15)
    
    # Créer les demandes
    print("\n[3/5] Création des demandes d'aide...")
    requests = create_requests(users, crises, 50)
    
    # Créer les offres
    print("\n[4/5] Création des offres d'aide...")
    offers = create_offers(users, crises, 50)
    
    # Créer les informations
    print("\n[5/5] Création des informations...")
    informations = create_informations(users, crises, 30)
    
    print("\n" + "="*60)
    print("[SUCCESS] GÉNÉRATION TERMINÉE !")
    print("="*60)
    print(f"\nRésumé:")
    print(f"  • {len(users)} utilisateurs")
    print(f"  • {len(crises)} crises")
    print(f"  • {len(requests)} demandes")
    print(f"  • {len(offers)} offres")
    print(f"  • {len(informations)} informations")
    print(f"\n  TOTAL: {len(crises) + len(requests) + len(offers) + len(informations)} éléments créés")
    print("\nLes données sont réparties sur toute la France!")
    print("Rechargez votre application pour voir les nouvelles données\n")

if __name__ == '__main__':
    main()
