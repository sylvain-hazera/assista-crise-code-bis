"""Données publiques à renouvellement rapide en UNLOGGED (26/11/2026).

Météo, radar, hydrométrie, carburants, trafic, séismes... : Météo-France et les autres sources
les republient ; inutile de les sauvegarder. Une table UNLOGGED ne produit aucun WAL et
pg_basebackup ne copie pas ses données (pg_dump les ignore avec --no-unlogged-table-data).
Après un plantage ou une restauration, elle repart vide et l'import suivant la remplit.

Restent journalisées : les référentiels qui changent peu et seraient longs à réimporter (BAN,
défibrillateurs, PPR, urbanisme, communes, points d'eau), tout ce qui est propre à la plateforme
(journal d'audit, radio, simulations), et les traces de diffusion (vigilance/séisme diffusés) qui
évitent de renvoyer une alerte. Aucune de ces tables n'a de clé étrangère (vérifié en prod).
La conversion réécrit chaque table une fois, ce qui supprime aussi son gonflement.
"""
from django.db import migrations

TABLES = [
    # Météo et radar
    "core_observationmeteo", "core_imageradarestimee", "core_imagepluie", "core_previsionpluiecommune",
    "core_imagerafales", "core_vignettevigilancemeteo", "core_imageradarorage", "core_pluiecommunesimage",
    "core_celluleorage", "core_champvent", "core_imageprecipitationhiver", "core_vigilancemeteo",
    "core_cumulpluiecommune", "core_potentieloragefeu", "core_risqueavalanche", "core_impactblitzortung",
    "core_impactfoudre",
    # Eau
    "core_stationhydrometrique", "core_tronconvigilancecrues", "core_maregraphe",
    # Autres données publiques
    "core_stationcarburant", "core_seisme", "core_evenementroutier", "core_stationcirculation",
    "core_arretecirculation", "core_antenneindisponible",
]


def _sql(persistance):
    return ";\n".join(f'ALTER TABLE "{t}" SET {persistance}' for t in TABLES) + ";"


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0391_noeuds_equipe'),
    ]

    operations = [
        migrations.RunSQL(_sql("UNLOGGED"), reverse_sql=_sql("LOGGED")),
    ]
