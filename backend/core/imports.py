"""Import CSV/XLS de listes pour une institution — personnel communal et élus dans un premier
temps (voir ImportPersonnelCommunalView/ImportApercuView, core/views.py). Toujours ré-analysé à
chaque appel plutôt que mis en cache côté serveur entre l'aperçu et l'import réel (fichiers de
quelques centaines de lignes au plus pour une commune, coût de re-parsing négligeable — évite
toute gestion d'état serveur entre les deux étapes).

Garde-fou volontaire : cette app ne doit JAMAIS héberger de donnée de santé (voir le même principe
déjà posé sur DeclarationSecurite). Les champs cibles d'un import sont une liste FERMÉE
(CHAMPS_PERSONNEL_COMMUNAL) — aucune colonne du fichier source au-delà de ceux mappés
explicitement n'est jamais lue ni stockée, quelle que soit sa présence dans le fichier."""
import codecs
import csv
import io

import openpyxl

CHAMPS_PERSONNEL_COMMUNAL = ["prenom", "nom", "email", "telephone", "fonction"]

LABELS_PERSONNEL_COMMUNAL = {
    "prenom": "Prénom",
    "nom": "Nom",
    "email": "Email",
    "telephone": "Téléphone",
    "fonction": "Fonction (ex: Maire, 1er adjoint, DGS, agent technique...)",
}


def parse_fichier(fichier):
    """Retourne (colonnes, lignes) où colonnes est la liste des en-têtes dans l'ordre du
    fichier et lignes une liste de dict {colonne: valeur}. Détecte CSV vs XLSX par extension ;
    lève ValueError si le format n'est pas reconnu."""
    nom = (fichier.name or "").lower()
    if nom.endswith(".xlsx"):
        return _parse_xlsx(fichier)
    if nom.endswith(".csv"):
        return _parse_csv(fichier)
    raise ValueError("Format de fichier non reconnu — utilisez un fichier .csv ou .xlsx.")


# Encodages essayés dans l'ordre pour un CSV. utf-8 d'abord (le bon cas), puis cp1252 :
# c'est ce qu'écrit Excel sous Windows avec « CSV (séparateur point-virgule) », de loin le
# chemin le plus courant pour une mairie, et le seul caractère accentué suffit à faire échouer
# un décodage utf-8 strict. latin-1 en dernier ne peut jamais lever (tout octet y est valide) :
# il sert de filet pour ne JAMAIS rejeter un fichier sur son encodage -- au pire un accent
# s'affiche de travers dans l'aperçu, ce que l'utilisateur voit et peut corriger, au lieu d'une
# erreur technique incompréhensible (constat terrain du 2026-10-25 : trois tentatives d'import
# refusées avec « 'utf-8' codec can't decode byte 0xe9 »).
ENCODAGES_CSV = ("utf-8", "cp1252", "latin-1")

# Séparateurs candidats, départagés sur la seule ligne d'en-têtes : compter sur tout le fichier
# faisait choisir la virgule dès qu'une seule cellule de données en contenait une (« Dupont,
# Jean » dans un commentaire, un montant « 1,5 »...).
SEPARATEURS_CSV = (";", ",", "\t")


def _decoder_csv(octets):
    """Texte décodé sans BOM, quel que soit l'encodage d'origine (voir ENCODAGES_CSV)."""
    if octets.startswith(codecs.BOM_UTF8):
        octets = octets[len(codecs.BOM_UTF8):]
    for encodage in ENCODAGES_CSV:
        try:
            return octets.decode(encodage)
        except UnicodeDecodeError:
            continue
    # Inatteignable tant que latin-1 est dans la liste, gardé pour que la fonction reste
    # correcte si ENCODAGES_CSV change un jour.
    raise ValueError(
        "Impossible de lire le texte de ce fichier — réenregistrez-le depuis votre tableur "
        "au format « CSV UTF-8 »."
    )


def _separateur_csv(premiere_ligne):
    occurrences = {sep: premiere_ligne.count(sep) for sep in SEPARATEURS_CSV}
    meilleur = max(occurrences, key=lambda sep: occurrences[sep])
    # Une seule colonne (aucun séparateur trouvé) : le choix est sans effet, on garde le
    # point-virgule, convention française.
    return meilleur if occurrences[meilleur] else ";"


def _parse_csv(fichier):
    contenu = _decoder_csv(fichier.read())
    premiere_ligne = contenu.splitlines()[0] if contenu else ""
    reader = csv.reader(io.StringIO(contenu), delimiter=_separateur_csv(premiere_ligne))
    try:
        entetes = next(reader)
    except StopIteration:
        raise ValueError("Ce fichier est vide — la première ligne doit contenir les en-têtes de colonnes.")
    # En-têtes nettoyées : un espace de fin invisible (« Email » / « Email ») empêchait la
    # pré-sélection de la colonne et obligeait à tout remapper à la main.
    colonnes = [str(c).strip() for c in entetes]
    lignes = []
    for row in reader:
        if not any((v or "").strip() for v in row):
            continue
        lignes.append({colonnes[i]: row[i] if i < len(row) else None for i in range(len(colonnes))})
    return colonnes, lignes


def _parse_xlsx(fichier):
    classeur = openpyxl.load_workbook(fichier, read_only=True, data_only=True)
    feuille = classeur.active
    lignes_brutes = feuille.iter_rows(values_only=True)
    entetes = next(lignes_brutes, [])
    colonnes = [str(c).strip() if c is not None else "" for c in entetes]
    lignes = []
    for row in lignes_brutes:
        if all(v is None for v in row):
            continue
        lignes.append({colonnes[i]: row[i] if i < len(row) else None for i in range(len(colonnes))})
    return colonnes, lignes


def _valeur(ligne, mapping, champ):
    colonne_source = mapping.get(champ)
    if not colonne_source:
        return ""
    valeur = ligne.get(colonne_source)
    return str(valeur).strip() if valeur is not None else ""


def importer_personnel_communal(request, institution, lignes, mapping, cle_invitation=None,
                                premiere_ligne=2):
    """mapping : {champ_cible: colonne_source}, champ_cible parmi CHAMPS_PERSONNEL_COMMUNAL.
    Crée ou rattache un compte complet par ligne (User + ContactInstitution +
    AffectationRoleOperationnel REFERENT + accès démo, voir
    institution_attachment.grant_institution_and_demo_access) — email et nom obligatoires, les
    lignes sans l'un des deux sont ignorées et reportées en erreur plutôt que d'échouer tout
    l'import. Un email déjà existant dans le système est simplement rattaché à `institution`
    (jamais recréé), pour que ré-importer le même fichier après correction soit sans risque.

    `cle_invitation` : nom d'une clé booléenne portée par chaque ligne, qui décide de l'envoi du
    mail d'invitation (None = on invite toujours, comportement d'un import de fichier).
    `premiere_ligne` : numéro de la première ligne de données dans les messages d'erreur (2 pour
    un fichier à en-têtes, 1 pour une saisie à la main)."""
    from .audit import audit_log
    from .crypto_fields import blind_index
    from .institution_attachment import grant_institution_and_demo_access
    from .models import AffectationRoleOperationnel, ContactInstitution, RoleOperationnel, User, UserRole
    from .views import send_institution_account_email

    role_referent = RoleOperationnel.objects.filter(code="REFERENT").first()

    crees, rattaches, erreurs = [], [], []
    for numero, ligne in enumerate(lignes, start=premiere_ligne):
        email = _valeur(ligne, mapping, "email").lower()
        nom = _valeur(ligne, mapping, "nom")
        prenom = _valeur(ligne, mapping, "prenom")
        telephone = _valeur(ligne, mapping, "telephone")
        fonction = _valeur(ligne, mapping, "fonction")

        if not email or not nom:
            erreurs.append({"ligne": numero, "message": "Email et nom sont obligatoires."})
            continue

        inviter = True if cle_invitation is None else bool(ligne.get(cle_invitation, True))

        # email chiffré (voir core/crypto_fields.py) -- recherche exacte par index aveugle.
        user = User.objects.filter(email_bidx=blind_index(email)).first()
        if user is None:
            user = User.objects.create_user(
                username=email, email=email, password=None,
                first_name=prenom, last_name=nom, phone_number=telephone or None,
                type=UserRole.LOCAL_AUTHORITY, enabled=True, is_active=False,
            )
            crees.append(email)
            if inviter:
                try:
                    send_institution_account_email(request, user)
                except Exception:
                    pass
        else:
            rattaches.append(email)
            if user.type == UserRole.SIMPLE_USER:
                # Compte déjà existant, inscrit en simple utilisateur (ex: élu avec son adresse
                # personnelle, une mairie ne pouvant pas toujours payer des boîtes pro -- demande
                # utilisateur du 08/10) : promu AUT_LOCALE comme pour une création, sinon le
                # rattachement ci-dessous reste sans effet (les permissions institutionnelles se
                # basent sur user.type, pas sur ContactInstitution). Jamais de rétrogradation
                # d'un compte déjà ADMIN/SECOURS/AUT_LOCALE/REGULATEUR.
                user.type = UserRole.LOCAL_AUTHORITY
                user.save(update_fields=['type'])

        ContactInstitution.objects.get_or_create(
            institution=institution, utilisateur=user,
            defaults={"fonction": fonction or "Membre", "actif": True},
        )
        grant_institution_and_demo_access(user, institution, request)
        if role_referent:
            AffectationRoleOperationnel.objects.get_or_create(
                utilisateur=user, institution=institution, competence=None, role=role_referent,
                defaults={"actif": True},
            )

    audit_log(
        request=request,
        action_code="IMPORT_LISTE",
        objet_type="Institution",
        objet_id=institution.id,
        commentaire=(
            f"Import personnel/élus pour {institution.nom} : "
            f"{len(crees)} compte(s) créé(s), {len(rattaches)} rattaché(s), {len(erreurs)} erreur(s)"
        ),
    )
    return {"crees": len(crees), "rattaches": len(rattaches), "erreurs": erreurs}


def importer_personnel_communal_saisie(request, institution, personnes):
    """Saisie à la main, ligne par ligne, du personnel communal — même traitement exactement
    qu'un import de fichier (importer_personnel_communal : compte complet, rattachement à
    l'institution, rôle REFERENT, accès démo), pour quelques personnes seulement : refaire un
    CSV pour deux agents n'a aucun sens (demande Nicolas Larvor du 2026-10-26).

    `personnes` : liste de dicts {prenom, nom, email, telephone, fonction, inviter}. `inviter`
    (vrai par défaut) décide du seul envoi du mail d'invitation : la personne est de toute façon
    rattachée à la collectivité, c'est le propre de cette page — on peut simplement l'enregistrer
    d'abord et lui écrire plus tard (bouton « Renvoyer l'activation » de la page Utilisateurs).
    Seuls les champs de CHAMPS_PERSONNEL_COMMUNAL sont lus, comme pour un fichier : aucune autre
    clé envoyée par le client n'est jamais regardée (même garde-fou « aucune donnée de santé »)."""
    lignes = []
    for personne in personnes:
        ligne = {champ: personne.get(champ) or "" for champ in CHAMPS_PERSONNEL_COMMUNAL}
        ligne["inviter"] = personne.get("inviter", True) is not False
        lignes.append(ligne)
    # mapping identité : les clés des lignes construites ci-dessus SONT les champs cibles.
    mapping = {champ: champ for champ in CHAMPS_PERSONNEL_COMMUNAL}
    return importer_personnel_communal(
        request, institution, lignes, mapping, cle_invitation="inviter", premiere_ligne=1,
    )


def exemple_csv_personnel_communal() -> str:
    """Fichier exemple téléchargeable à côté du formulaire d'import — mêmes en-têtes que
    LABELS_PERSONNEL_COMMUNAL, avec deux lignes d'exemple réalistes."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(list(LABELS_PERSONNEL_COMMUNAL.values()))
    writer.writerow(["Jeanne", "Martin", "jeanne.martin@mairie-exemple.fr", "0600000000", "Maire"])
    writer.writerow(["Paul", "Durand", "paul.durand@mairie-exemple.fr", "0600000001", "Secrétaire de mairie"])
    return buffer.getvalue()


CHAMPS_INSTITUTIONS = ["nom", "type", "description", "telephone", "email", "adresse"]

LABELS_INSTITUTIONS = {
    "nom": "Nom de l'institution",
    "type": "Type (libellé exact déjà existant, ex: Mairie)",
    "description": "Description",
    "telephone": "Téléphone",
    "email": "Email",
    "adresse": "Adresse",
}


def importer_institutions(request, lignes, mapping):
    """mapping : {champ_cible: colonne_source}, champ_cible parmi CHAMPS_INSTITUTIONS. nom et
    type sont obligatoires ; type doit correspondre exactement (insensible à la casse) au
    libellé d'un InstitutionType déjà existant — jamais créé à la volée depuis un import,
    contrairement à Competence/InformationType : un type d'institution structure les
    permissions/le niveau de secteur (voir SECTEUR_NIVEAU_PAR_TYPE_INSTITUTION), pas un simple
    mot-clé. Une institution du même nom déjà existante (contrainte unique) est ignorée et
    reportée en erreur plutôt que dupliquée ou écrasée silencieusement. La commune n'est
    volontairement pas importable ici (pas de colonne dédiée) : trop fragile à résoudre en
    masse depuis un simple nom sans confirmation humaine — se renseigne après coup dans le
    formulaire d'édition de l'institution (autocomplete, même mécanisme que l'équipe)."""
    from .audit import audit_log
    from .models import Institution, InstitutionType
    from .notifications_admin import notifications_institution_suspendues, notifier_administrateurs
    from .permissions import get_active_environment

    environment = get_active_environment(request)
    types_par_libelle = {t.libelle.strip().lower(): t for t in InstitutionType.objects.all()}

    # Alerte "nouvelle institution" (voir core/notifications_admin.py) suspendue pendant la
    # boucle : un seul récapitulatif après, plutôt qu'un email par ligne importée.
    with notifications_institution_suspendues():
        crees, erreurs = _importer_lignes_institutions(lignes, mapping, types_par_libelle, environment)

    if crees:
        notifier_administrateurs(
            f"{len(crees)} institution(s) importée(s)",
            "Import CSV d'institutions :\n\n" + "\n".join(f"- {nom}" for nom in crees),
            request=request,
        )

    audit_log(
        request=request,
        action_code="IMPORT_LISTE",
        objet_type="Institution",
        objet_id=None,
        commentaire=f"Import d'institutions : {len(crees)} créée(s), {len(erreurs)} erreur(s)",
    )
    return {"crees": len(crees), "erreurs": erreurs}


def _importer_lignes_institutions(lignes, mapping, types_par_libelle, environment):
    from .models import Institution

    crees, erreurs = [], []
    for numero, ligne in enumerate(lignes, start=2):  # ligne 1 = en-têtes, données à partir de 2
        nom = _valeur(ligne, mapping, "nom")
        type_libelle = _valeur(ligne, mapping, "type")

        if not nom or not type_libelle:
            erreurs.append({"ligne": numero, "message": "Nom et type sont obligatoires."})
            continue

        itype = types_par_libelle.get(type_libelle.strip().lower())
        if itype is None:
            erreurs.append({"ligne": numero, "message": f"Type d'institution inconnu : « {type_libelle} »."})
            continue

        if Institution.objects.filter(nom__iexact=nom).exists():
            erreurs.append({"ligne": numero, "message": f"Une institution « {nom} » existe déjà."})
            continue

        Institution.objects.create(
            nom=nom, type=itype,
            description=_valeur(ligne, mapping, "description") or None,
            telephone=_valeur(ligne, mapping, "telephone") or None,
            email=_valeur(ligne, mapping, "email") or None,
            adresse=_valeur(ligne, mapping, "adresse") or None,
            environment=environment,
        )
        crees.append(nom)
    return crees, erreurs


def exemple_csv_institutions() -> str:
    """Fichier exemple téléchargeable à côté du formulaire d'import d'institutions."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(list(LABELS_INSTITUTIONS.values()))
    writer.writerow(["Mairie d'Exemple-sur-Loire", "Mairie", "", "0100000000", "mairie@exemple.fr", "1 place de la Mairie"])
    writer.writerow(["Croix-Rouge locale", "Association", "Antenne locale", "0100000001", "contact@croix-rouge-exemple.fr", ""])
    return buffer.getvalue()


CHAMPS_HABITATIONS = ["adresse", "latitude", "longitude", "parcelle_cadastrale", "commune_code", "commune_nom"]

LABELS_HABITATIONS = {
    "adresse": "Adresse postale",
    "latitude": "Latitude (optionnel, géocodée via la BAN si absente)",
    "longitude": "Longitude (optionnel, géocodée via la BAN si absente)",
    "parcelle_cadastrale": "Parcelle cadastrale (optionnel, complétée via le cadastre IGN si absente)",
    "commune_code": "Code commune INSEE (optionnel)",
    "commune_nom": "Commune (optionnel)",
}


def _geocoder_adresse(adresse: str):
    """Géocodage ponctuel d'une adresse texte via la BAN -- utilisé uniquement quand le CSV
    fourni n'a pas déjà latitude/longitude (cas normal : le partenaire fournit un export déjà
    géolocalisé). Best-effort : ne lève jamais, renvoie (None, None, None, None) en échec."""
    import json
    import urllib.parse
    import urllib.request

    try:
        url = "https://api-adresse.data.gouv.fr/search/?q=" + urllib.parse.quote(adresse) + "&limit=1"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        feature = (data.get("features") or [None])[0]
        if not feature:
            return None, None, None, None
        lon, lat = feature["geometry"]["coordinates"]
        props = feature.get("properties", {})
        return lat, lon, props.get("citycode"), props.get("city")
    except Exception:
        return None, None, None, None


def _parcelle_cadastrale_via_point(lat, lon):
    """Identifiant de parcelle (ex: 33333000BK0034) via IGN APICarto cadastre, par point GPS --
    best-effort, ne lève jamais."""
    import json
    import urllib.request

    try:
        payload = json.dumps({"geom": {"type": "Point", "coordinates": [lon, lat]}}).encode("utf-8")
        req = urllib.request.Request(
            "https://apicarto.ign.fr/api/cadastre/parcelle",
            data=payload, headers={"Content-Type": "application/json"}, method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        feature = (data.get("features") or [None])[0]
        if not feature:
            return None
        return feature["properties"].get("idu")
    except Exception:
        return None


def importer_habitations(request, lignes, mapping, crise=None, zone=None):
    """mapping : {champ_cible: colonne_source}, champ_cible parmi CHAMPS_HABITATIONS. adresse
    obligatoire ; latitude/longitude/parcelle_cadastrale géocodés au besoin (voir
    _geocoder_adresse/_parcelle_cadastrale_via_point) quand absents du fichier -- coûteux
    (appel externe par ligne manquante), mais un import se fait une fois pour quelques centaines
    de lignes au plus, pas à chaque lecture."""
    from django.contrib.gis.geos import Point

    from .audit import audit_log
    from .models import Habitation
    from .permissions import get_active_environment

    crees, erreurs = [], []
    for numero, ligne in enumerate(lignes, start=2):
        adresse = _valeur(ligne, mapping, "adresse")
        if not adresse:
            erreurs.append({"ligne": numero, "message": "L'adresse est obligatoire."})
            continue

        lat_brut = _valeur(ligne, mapping, "latitude")
        lon_brut = _valeur(ligne, mapping, "longitude")
        commune_code = _valeur(ligne, mapping, "commune_code") or None
        commune_nom = _valeur(ligne, mapping, "commune_nom") or None
        parcelle = _valeur(ligne, mapping, "parcelle_cadastrale") or None

        try:
            lat = float(lat_brut) if lat_brut else None
            lon = float(lon_brut) if lon_brut else None
        except ValueError:
            lat, lon = None, None

        if lat is None or lon is None:
            lat, lon, geocode_commune_code, geocode_commune_nom = _geocoder_adresse(adresse)
            commune_code = commune_code or geocode_commune_code
            commune_nom = commune_nom or geocode_commune_nom

        if lat is None or lon is None:
            erreurs.append({"ligne": numero, "message": "Coordonnées introuvables (ni fournies, ni géocodées)."})
            continue

        if not parcelle:
            parcelle = _parcelle_cadastrale_via_point(lat, lon)

        habitation = Habitation.objects.create(
            adresse=adresse,
            location=Point(lon, lat, srid=4326),
            commune_code=commune_code,
            commune_nom=commune_nom,
            parcelle_cadastrale=parcelle,
            crise=crise,
            zone=zone,
            environment=get_active_environment(request),
        )
        crees.append(habitation.adresse)

    audit_log(
        request=request,
        action_code="IMPORT_LISTE",
        objet_type="Habitation",
        objet_id=None,
        commentaire=f"Import référencement des dégâts : {len(crees)} habitation(s) créée(s), {len(erreurs)} erreur(s)",
    )
    return {"crees": len(crees), "erreurs": erreurs}


def exemple_csv_habitations() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(list(LABELS_HABITATIONS.values()))
    writer.writerow(["12 rue des Halliers, 33680 Le Porge", "44.874028", "-1.103645", "", "33333", "Le Porge"])
    writer.writerow(["4 lotissement Plein Soleil, 33680 Le Porge", "", "", "", "", ""])
    return buffer.getvalue()


CHAMPS_CORRESPONDANTS_PCS = ["prenom", "nom", "email", "telephone", "role", "responsabilite"]

LABELS_CORRESPONDANTS_PCS = {
    "prenom": "Prénom",
    "nom": "Nom",
    "email": "Email",
    "telephone": "Téléphone",
    "role": "Rôle PCS (libellé exact déjà existant, ex: Correspondant logistique — voir l'onglet « Rôles opérationnels »)",
    "responsabilite": "Titulaire ou Suppléant",
}


def importer_correspondants_pcs(request, institution, lignes, mapping):
    """mapping : {champ_cible: colonne_source}, champ_cible parmi CHAMPS_CORRESPONDANTS_PCS --
    même logique que importer_personnel_communal (get-or-create User par email,
    ContactInstitution) mais résout `role` contre les RoleOperationnel déjà existants (comme
    importer_institutions résout `type` contre InstitutionType -- jamais créé à la volée, un
    rôle PCS se crée depuis l'onglet « Rôles opérationnels », pas en masse par erreur de frappe)
    et crée l'AffectationRoleOperationnel correspondante, avec `responsabilite` (ex: "Titulaire"/
    "Suppléant") -- champ déjà existant sur ce modèle, jamais utilisé jusqu'ici."""
    from .audit import audit_log
    from .crypto_fields import blind_index
    from .institution_attachment import grant_institution_and_demo_access
    from .models import AffectationRoleOperationnel, ContactInstitution, RoleOperationnel, User, UserRole
    from .views import send_institution_account_email

    roles_par_libelle = {r.libelle.strip().lower(): r for r in RoleOperationnel.objects.all()}

    crees, rattaches, erreurs = [], [], []
    for numero, ligne in enumerate(lignes, start=2):
        email = _valeur(ligne, mapping, "email").lower()
        nom = _valeur(ligne, mapping, "nom")
        prenom = _valeur(ligne, mapping, "prenom")
        telephone = _valeur(ligne, mapping, "telephone")
        role_libelle = _valeur(ligne, mapping, "role")
        responsabilite = _valeur(ligne, mapping, "responsabilite")

        if not email or not nom:
            erreurs.append({"ligne": numero, "message": "Email et nom sont obligatoires."})
            continue

        role = roles_par_libelle.get(role_libelle.strip().lower()) if role_libelle else None
        if role_libelle and role is None:
            erreurs.append({"ligne": numero, "message": f"Rôle PCS inconnu : « {role_libelle} » (à créer d'abord dans « Rôles opérationnels »)."})
            continue

        user = User.objects.filter(email_bidx=blind_index(email)).first()
        if user is None:
            user = User.objects.create_user(
                username=email, email=email, password=None,
                first_name=prenom, last_name=nom, phone_number=telephone or None,
                type=UserRole.LOCAL_AUTHORITY, enabled=True, is_active=False,
            )
            crees.append(email)
            try:
                send_institution_account_email(request, user)
            except Exception:
                pass
        else:
            rattaches.append(email)
            if user.type == UserRole.SIMPLE_USER:
                user.type = UserRole.LOCAL_AUTHORITY
                user.save(update_fields=['type'])

        ContactInstitution.objects.get_or_create(
            institution=institution, utilisateur=user,
            defaults={"fonction": role.libelle if role else "Correspondant PCS", "actif": True},
        )
        grant_institution_and_demo_access(user, institution, request)
        if role:
            AffectationRoleOperationnel.objects.get_or_create(
                utilisateur=user, institution=institution, competence=None, role=role,
                defaults={"actif": True, "responsabilite": responsabilite or ""},
            )

    audit_log(
        request=request,
        action_code="IMPORT_LISTE",
        objet_type="Institution",
        objet_id=institution.id,
        commentaire=(
            f"Import correspondants PCS pour {institution.nom} : "
            f"{len(crees)} compte(s) créé(s), {len(rattaches)} rattaché(s), {len(erreurs)} erreur(s)"
        ),
    )
    return {"crees": len(crees), "rattaches": len(rattaches), "erreurs": erreurs}


def exemple_csv_correspondants_pcs() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(list(LABELS_CORRESPONDANTS_PCS.values()))
    writer.writerow(["Jeanne", "Martin", "jeanne.martin@mairie-exemple.fr", "0600000000", "Correspondant logistique", "Titulaire"])
    writer.writerow(["Paul", "Durand", "paul.durand@mairie-exemple.fr", "0600000001", "Correspondant logistique", "Suppléant"])
    return buffer.getvalue()


CHAMPS_INTERLOCUTEURS_PCS = ["nom", "organisme", "categorie", "email", "telephone", "mode_alerte"]

LABELS_INTERLOCUTEURS_PCS = {
    "nom": "Nom du contact",
    "organisme": "Organisme (ex: Préfecture de la Gironde)",
    "categorie": "Catégorie (ex: Préfecture, Gendarmerie / Police, SDIS, ARS, Élu ou personnel communal...)",
    "email": "Email",
    "telephone": "Téléphone",
    "mode_alerte": "Mode d'alerte (Email, Téléphone (manuel uniquement), Aucun envoi automatique)",
}


def importer_interlocuteurs_pcs(request, institution, lignes, mapping):
    """mapping : {champ_cible: colonne_source}, champ_cible parmi CHAMPS_INTERLOCUTEURS_PCS --
    crée/rattache un InterlocuteurAlertePCS (même esprit que
    InterlocuteurAlertePCSViewSet.perform_create : departement_code depuis l'institution,
    rattachement M2M direct -- jamais de doublon si le même nom+organisme existe déjà pour une
    autre commune, on le rattache au lieu d'en recréer un). `categorie`/`mode_alerte` résolus
    par libellé français (insensible à la casse), jamais par code technique -- une mairie ne
    connaît pas les codes internes."""
    from .audit import audit_log
    from .models import CategorieInterlocuteurPCS, InterlocuteurAlertePCS, ModeAlertePCS

    categories_par_libelle = {c.label.strip().lower(): c.value for c in CategorieInterlocuteurPCS}
    modes_par_libelle = {m.label.strip().lower(): m.value for m in ModeAlertePCS}

    crees, rattaches, erreurs = [], [], []
    for numero, ligne in enumerate(lignes, start=2):
        nom = _valeur(ligne, mapping, "nom")
        organisme = _valeur(ligne, mapping, "organisme")
        categorie_libelle = _valeur(ligne, mapping, "categorie")
        email = _valeur(ligne, mapping, "email")
        telephone = _valeur(ligne, mapping, "telephone")
        mode_libelle = _valeur(ligne, mapping, "mode_alerte")

        if not nom:
            erreurs.append({"ligne": numero, "message": "Le nom du contact est obligatoire."})
            continue

        categorie = categories_par_libelle.get(categorie_libelle.strip().lower(), CategorieInterlocuteurPCS.AUTRE) if categorie_libelle else CategorieInterlocuteurPCS.AUTRE
        mode_alerte = modes_par_libelle.get(mode_libelle.strip().lower(), ModeAlertePCS.EMAIL) if mode_libelle else ModeAlertePCS.EMAIL

        existant = None
        if organisme:
            existant = InterlocuteurAlertePCS.objects.filter(nom__iexact=nom, organisme__iexact=organisme).first()
        if existant:
            existant.institutions.add(institution)
            rattaches.append(nom)
            continue

        interlocuteur = InterlocuteurAlertePCS.objects.create(
            nom=nom, organisme=organisme, categorie=categorie,
            email=email or None, telephone=telephone or None, mode_alerte=mode_alerte,
            departement_code=institution.departement_code,
            environment=institution.environment,
        )
        interlocuteur.institutions.add(institution)
        crees.append(nom)

    audit_log(
        request=request,
        action_code="IMPORT_LISTE",
        objet_type="Institution",
        objet_id=institution.id,
        commentaire=(
            f"Import annuaire PCS pour {institution.nom} : "
            f"{len(crees)} créé(s), {len(rattaches)} rattaché(s), {len(erreurs)} erreur(s)"
        ),
    )
    return {"crees": len(crees), "rattaches": len(rattaches), "erreurs": erreurs}


def exemple_csv_interlocuteurs_pcs() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(list(LABELS_INTERLOCUTEURS_PCS.values()))
    writer.writerow(["SIDPC", "Préfecture de la Gironde", "Préfecture", "sidpc@gironde.gouv.fr", "0500000000", "Email"])
    writer.writerow(["Standard", "SDIS 33", "SDIS (secours)", "", "0500000001", "Téléphone (manuel uniquement)"])
    return buffer.getvalue()


CHAMPS_MATERIEL_POINT = ["nom_item", "niveau_stock", "quantite", "unite", "commentaire"]

LABELS_MATERIEL_POINT = {
    "nom_item": "Nom du matériel (ex: Tatamis, Lits de camp, Couvertures...)",
    "niveau_stock": "Niveau de stock (Nul, Faible, OK, En trop)",
    "quantite": "Quantité",
    "unite": "Unité (ex: unité, kg, L...)",
    "commentaire": "Précision (ex: utilisable comme lit d'urgence)",
}

_NIVEAUX_STOCK_PAR_LIBELLE = {"nul": "NUL", "faible": "FAIBLE", "ok": "OK", "en trop": "EN_TROP"}


def importer_materiel_point(request, point, lignes, mapping):
    """mapping : {champ_cible: colonne_source}, champ_cible parmi CHAMPS_MATERIEL_POINT -- cible
    TOUJOURS un seul point (passé en paramètre, jamais une colonne du fichier) : importer le
    matériel d'une salle omnisports déclarée comme centre d'accueil potentiel, par exemple.
    Résout/crée l'item catalogue par nom (même dédoublonnage casse-insensible que
    TagLikeViewSetMixin.create, voir views.py) puis crée/MAJ la ligne MaterielPoint."""
    from .audit import audit_log
    from .models import MaterielCatalogue, MaterielPoint, NiveauStock
    from .permissions import get_active_environment

    environment = get_active_environment(request)
    crees, maj, erreurs = [], [], []
    for numero, ligne in enumerate(lignes, start=2):
        nom_item = _valeur(ligne, mapping, "nom_item")
        if not nom_item:
            erreurs.append({"ligne": numero, "message": "Le nom du matériel est obligatoire."})
            continue

        niveau_libelle = _valeur(ligne, mapping, "niveau_stock")
        niveau = _NIVEAUX_STOCK_PAR_LIBELLE.get(niveau_libelle.strip().lower(), NiveauStock.NUL) if niveau_libelle else NiveauStock.NUL
        quantite_brut = _valeur(ligne, mapping, "quantite")
        try:
            quantite = int(float(quantite_brut)) if quantite_brut else 1
        except ValueError:
            quantite = 1
        unite = _valeur(ligne, mapping, "unite") or "unité"
        commentaire = _valeur(ligne, mapping, "commentaire") or None

        item = MaterielCatalogue.objects.filter(nom__iexact=nom_item).first()
        if item is None:
            item = MaterielCatalogue.objects.create(nom=nom_item)

        materiel_point, created = MaterielPoint.objects.update_or_create(
            point=point, item=item,
            defaults={
                "niveau_stock": niveau, "quantite": quantite, "unite": unite,
                "commentaire": commentaire, "environment": environment,
            },
        )
        (crees if created else maj).append(nom_item)

    audit_log(
        request=request,
        action_code="IMPORT_LISTE",
        objet_type="PointOperationnel",
        objet_id=point.id,
        commentaire=f"Import matériel pour {point.nom} : {len(crees)} créé(s), {len(maj)} mis à jour, {len(erreurs)} erreur(s)",
    )
    return {"crees": len(crees), "rattaches": len(maj), "erreurs": erreurs}


def exemple_csv_materiel_point() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(list(LABELS_MATERIEL_POINT.values()))
    writer.writerow(["Tatamis", "OK", "40", "unité", "utilisables comme lits d'urgence"])
    writer.writerow(["Couvertures", "Faible", "15", "unité", ""])
    return buffer.getvalue()
