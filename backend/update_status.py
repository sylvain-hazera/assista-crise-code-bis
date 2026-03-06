#!/usr/bin/env python
"""
Script pour mettre à jour tous les statuts des données existantes en "Non traitée"
"""
import os
import sys
import django

# Configuration Django
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Request, Offer, Information, Status

def main():
    print("\n" + "="*60)
    print("Mise à jour des statuts en base de données")
    print("="*60 + "\n")
    
    # Mettre à jour les demandes
    requests_updated = Request.objects.exclude(status=Status.UNPROCESSED).update(status=Status.UNPROCESSED)
    print(f"[OK] {requests_updated} demandes mises à jour vers 'Non traitée'")
    
    # Mettre à jour les offres
    offers_updated = Offer.objects.exclude(status=Status.UNPROCESSED).update(status=Status.UNPROCESSED)
    print(f"[OK] {offers_updated} offres mises à jour vers 'Non traitée'")
    
    # Mettre à jour les informations
    infos_updated = Information.objects.exclude(status=Status.UNPROCESSED).update(status=Status.UNPROCESSED)
    print(f"[OK] {infos_updated} informations mises à jour vers 'Non traitée'")
    
    print("\n" + "="*60)
    print("[SUCCESS] MISE À JOUR TERMINÉE !")
    print("="*60)
    print(f"\nTotal: {requests_updated + offers_updated + infos_updated} éléments mis à jour\n")

if __name__ == '__main__':
    main()
