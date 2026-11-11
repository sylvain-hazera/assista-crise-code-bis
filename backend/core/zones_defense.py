"""Zones de défense et de sécurité, régions et départements : table de référence.

Sert à bâtir l'arborescence de coordination d'une association nationale
(`manage.py creer_arborescence_coordination`). Rien d'autre dans le projet n'avait besoin de
cette découpe : `Commune` porte `departement_code` et `region_code`, mais la zone de défense
n'existe nulle part ailleurs.

**Table écrite à la main, et c'est assumé.** Il n'existe pas d'API publique stable qui serve
cette découpe ; elle est fixée par le décret du 10 décembre 2015 et ne bouge qu'avec un décret.
Une table figée qu'on relit vaut mieux qu'un appel réseau qui échoue au moment où l'on crée
l'arborescence.

**Contrôle de cohérence intégré** (`verifier_coherence`) : la somme des départements par zone
doit valoir 96 en métropole, et chaque code de département doit être unique sur tout le pays.
C'est ce recoupement qui a servi à vérifier la composition zone par zone — les comptes
officiels par zone (Nord 5, Est 18, Ouest 20, Sud 21) tombent juste.

Les zones outre-mer sont incluses : le projet a déjà un satellite à La Réunion, et les omettre
aurait fait une arborescence « nationale » sans l'outre-mer.
"""

# (code, libellé, siège, [(code région, libellé région, [(code dépt, libellé dépt)])])
#
# Les codes de zone sont les nôtres : une zone de défense n'a pas de code INSEE. Préfixés
# « ZD- » pour qu'on ne les confonde jamais avec un code région (« 84 ») ou département.
ZONES_DEFENSE = [
    ("ZD-NORD", "Nord", "Lille", [
        ("32", "Hauts-de-France", [
            ("02", "Aisne"), ("59", "Nord"), ("60", "Oise"), ("62", "Pas-de-Calais"),
            ("80", "Somme"),
        ]),
    ]),
    ("ZD-OUEST", "Ouest", "Rennes", [
        ("53", "Bretagne", [
            ("22", "Côtes-d'Armor"), ("29", "Finistère"), ("35", "Ille-et-Vilaine"),
            ("56", "Morbihan"),
        ]),
        ("28", "Normandie", [
            ("14", "Calvados"), ("27", "Eure"), ("50", "Manche"), ("61", "Orne"),
            ("76", "Seine-Maritime"),
        ]),
        ("52", "Pays de la Loire", [
            ("44", "Loire-Atlantique"), ("49", "Maine-et-Loire"), ("53", "Mayenne"),
            ("72", "Sarthe"), ("85", "Vendée"),
        ]),
        ("24", "Centre-Val de Loire", [
            ("18", "Cher"), ("28", "Eure-et-Loir"), ("36", "Indre"), ("37", "Indre-et-Loire"),
            ("41", "Loir-et-Cher"), ("45", "Loiret"),
        ]),
    ]),
    ("ZD-EST", "Est", "Metz", [
        ("44", "Grand Est", [
            ("08", "Ardennes"), ("10", "Aube"), ("51", "Marne"), ("52", "Haute-Marne"),
            ("54", "Meurthe-et-Moselle"), ("55", "Meuse"), ("57", "Moselle"),
            ("67", "Bas-Rhin"), ("68", "Haut-Rhin"), ("88", "Vosges"),
        ]),
        ("27", "Bourgogne-Franche-Comté", [
            ("21", "Côte-d'Or"), ("25", "Doubs"), ("39", "Jura"), ("58", "Nièvre"),
            ("70", "Haute-Saône"), ("71", "Saône-et-Loire"), ("89", "Yonne"),
            ("90", "Territoire de Belfort"),
        ]),
    ]),
    ("ZD-SUD-EST", "Sud-Est", "Lyon", [
        ("84", "Auvergne-Rhône-Alpes", [
            ("01", "Ain"), ("03", "Allier"), ("07", "Ardèche"), ("15", "Cantal"),
            ("26", "Drôme"), ("38", "Isère"), ("42", "Loire"), ("43", "Haute-Loire"),
            ("63", "Puy-de-Dôme"), ("69", "Rhône"), ("73", "Savoie"), ("74", "Haute-Savoie"),
        ]),
    ]),
    ("ZD-SUD", "Sud", "Marseille", [
        ("93", "Provence-Alpes-Côte d'Azur", [
            ("04", "Alpes-de-Haute-Provence"), ("05", "Hautes-Alpes"), ("06", "Alpes-Maritimes"),
            ("13", "Bouches-du-Rhône"), ("83", "Var"), ("84", "Vaucluse"),
        ]),
        ("76", "Occitanie", [
            ("09", "Ariège"), ("11", "Aude"), ("12", "Aveyron"), ("30", "Gard"),
            ("31", "Haute-Garonne"), ("32", "Gers"), ("34", "Hérault"), ("46", "Lot"),
            ("48", "Lozère"), ("65", "Hautes-Pyrénées"), ("66", "Pyrénées-Orientales"),
            ("81", "Tarn"), ("82", "Tarn-et-Garonne"),
        ]),
        ("94", "Corse", [
            ("2A", "Corse-du-Sud"), ("2B", "Haute-Corse"),
        ]),
    ]),
    ("ZD-SUD-OUEST", "Sud-Ouest", "Bordeaux", [
        ("75", "Nouvelle-Aquitaine", [
            ("16", "Charente"), ("17", "Charente-Maritime"), ("19", "Corrèze"),
            ("23", "Creuse"), ("24", "Dordogne"), ("33", "Gironde"), ("40", "Landes"),
            ("47", "Lot-et-Garonne"), ("64", "Pyrénées-Atlantiques"), ("79", "Deux-Sèvres"),
            ("86", "Vienne"), ("87", "Haute-Vienne"),
        ]),
    ]),
    ("ZD-IDF", "Île-de-France", "Paris", [
        ("11", "Île-de-France", [
            ("75", "Paris"), ("77", "Seine-et-Marne"), ("78", "Yvelines"), ("91", "Essonne"),
            ("92", "Hauts-de-Seine"), ("93", "Seine-Saint-Denis"), ("94", "Val-de-Marne"),
            ("95", "Val-d'Oise"),
        ]),
    ]),
]

# Outre-mer. Les DROM sont à la fois région et département : l'échelon régional et l'échelon
# départemental y désigneraient le même territoire, et empiler deux équipes pour un seul
# territoire créerait deux salons pour les mêmes personnes. L'arborescence s'arrête donc à
# l'échelon régional pour eux — voir la commande, qui le dit aussi à l'écran.
ZONES_DEFENSE_OUTRE_MER = [
    ("ZD-ANTILLES", "Antilles", "Fort-de-France", [
        ("01", "Guadeloupe", []),
        ("02", "Martinique", []),
    ]),
    ("ZD-GUYANE", "Guyane", "Cayenne", [
        ("03", "Guyane", []),
    ]),
    ("ZD-OCEAN-INDIEN", "Sud de l'océan Indien", "Saint-Denis", [
        ("04", "La Réunion", []),
        ("06", "Mayotte", []),
    ]),
]

# Nombre de départements de métropole, Corse comptée pour deux. Sert de garde-fou : une erreur
# de recopie dans la table ci-dessus change ce total.
DEPARTEMENTS_METROPOLE = 96


def departements_de_zone(code_zone):
    """Tous les départements d'une zone, régions confondues."""
    for code, _libelle, _siege, regions in ZONES_DEFENSE + ZONES_DEFENSE_OUTRE_MER:
        if code == code_zone:
            return [dept for _rc, _rl, depts in regions for dept in depts]
    return []


def verifier_coherence():
    """Renvoie la liste des incohérences de la table. Vide = table saine.

    Appelée par la commande avant d'écrire quoi que ce soit, et par un test. Une table de
    référence recopiée à la main se vérifie, sinon on crée une arborescence fausse qui a l'air
    juste — et dont l'erreur ne se verra qu'à l'usage, dans un département manquant."""
    problemes = []

    vus_departements = {}
    vus_regions = {}
    for code_zone, libelle_zone, _siege, regions in ZONES_DEFENSE + ZONES_DEFENSE_OUTRE_MER:
        for code_region, libelle_region, departements in regions:
            # Les codes de région des DROM se répètent entre métropole et outre-mer
            # (« 01 » = Guadeloupe, mais aussi un code de département de l'Ain) : la clé
            # d'unicité d'une région est donc (code, libellé), pas le seul code.
            cle_region = (code_region, libelle_region)
            if cle_region in vus_regions:
                problemes.append(
                    f"Région « {libelle_region} » ({code_region}) dans deux zones : "
                    f"{vus_regions[cle_region]} et {libelle_zone}."
                )
            vus_regions[cle_region] = libelle_zone
            for code_dept, libelle_dept in departements:
                if code_dept in vus_departements:
                    problemes.append(
                        f"Département {code_dept} ({libelle_dept}) dans deux régions : "
                        f"{vus_departements[code_dept]} et {libelle_region}."
                    )
                vus_departements[code_dept] = libelle_region

    total_metropole = sum(
        len(depts) for _c, _l, _s, regions in ZONES_DEFENSE for _rc, _rl, depts in regions
    )
    if total_metropole != DEPARTEMENTS_METROPOLE:
        problemes.append(
            f"{total_metropole} départements de métropole dans la table, "
            f"{DEPARTEMENTS_METROPOLE} attendus — une ligne a été perdue ou dupliquée."
        )
    return problemes
