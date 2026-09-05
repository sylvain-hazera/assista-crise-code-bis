"""Import CSV/XLS de listes pour une institution — personnel communal et élus dans un premier
temps (voir ImportPersonnelCommunalView/ImportApercuView, core/views.py). Toujours ré-analysé à
chaque appel plutôt que mis en cache côté serveur entre l'aperçu et l'import réel (fichiers de
quelques centaines de lignes au plus pour une commune, coût de re-parsing négligeable — évite
toute gestion d'état serveur entre les deux étapes).

Garde-fou volontaire : cette app ne doit JAMAIS héberger de donnée de santé (voir le même principe
déjà posé sur DeclarationSecurite). Les champs cibles d'un import sont une liste FERMÉE
(CHAMPS_PERSONNEL_COMMUNAL) — aucune colonne du fichier source au-delà de ceux mappés
explicitement n'est jamais lue ni stockée, quelle que soit sa présence dans le fichier."""
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


def _parse_csv(fichier):
    # utf-8-sig : tolère le BOM ajouté par Excel à l'export CSV, sinon la première colonne
    # serait lue avec un caractère invisible en préfixe (ex: "﻿Prénom" au lieu de "Prénom").
    contenu = fichier.read().decode("utf-8-sig")
    delimiteur = ";" if contenu.count(";") >= contenu.count(",") else ","
    reader = csv.DictReader(io.StringIO(contenu), delimiter=delimiteur)
    lignes = [dict(row) for row in reader]
    colonnes = list(reader.fieldnames or [])
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


def importer_personnel_communal(request, institution, lignes, mapping):
    """mapping : {champ_cible: colonne_source}, champ_cible parmi CHAMPS_PERSONNEL_COMMUNAL.
    Crée ou rattache un compte complet par ligne (User + ContactInstitution +
    AffectationRoleOperationnel REFERENT + accès démo, voir
    institution_attachment.grant_institution_and_demo_access) — email et nom obligatoires, les
    lignes sans l'un des deux sont ignorées et reportées en erreur plutôt que d'échouer tout
    l'import. Un email déjà existant dans le système est simplement rattaché à `institution`
    (jamais recréé), pour que ré-importer le même fichier après correction soit sans risque."""
    from .audit import audit_log
    from .institution_attachment import grant_institution_and_demo_access
    from .models import AffectationRoleOperationnel, ContactInstitution, RoleOperationnel, User, UserRole
    from .views import send_institution_account_email

    role_referent = RoleOperationnel.objects.filter(code="REFERENT").first()

    crees, rattaches, erreurs = [], [], []
    for numero, ligne in enumerate(lignes, start=2):  # ligne 1 = en-têtes, données à partir de 2
        email = _valeur(ligne, mapping, "email").lower()
        nom = _valeur(ligne, mapping, "nom")
        prenom = _valeur(ligne, mapping, "prenom")
        telephone = _valeur(ligne, mapping, "telephone")
        fonction = _valeur(ligne, mapping, "fonction")

        if not email or not nom:
            erreurs.append({"ligne": numero, "message": "Email et nom sont obligatoires."})
            continue

        user = User.objects.filter(email__iexact=email).first()
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

        ContactInstitution.objects.get_or_create(
            institution=institution, utilisateur=user,
            defaults={"fonction": fonction or "Membre", "actif": True},
        )
        grant_institution_and_demo_access(user, institution)
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


def exemple_csv_personnel_communal() -> str:
    """Fichier exemple téléchargeable à côté du formulaire d'import — mêmes en-têtes que
    LABELS_PERSONNEL_COMMUNAL, avec deux lignes d'exemple réalistes."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(list(LABELS_PERSONNEL_COMMUNAL.values()))
    writer.writerow(["Jeanne", "Martin", "jeanne.martin@mairie-exemple.fr", "0600000000", "Maire"])
    writer.writerow(["Paul", "Durand", "paul.durand@mairie-exemple.fr", "0600000001", "Secrétaire de mairie"])
    return buffer.getvalue()
