"""Un seul moteur de disponibilité, et il est cloisonné.

Demande de Sylvain du 11/11/2026 : « tu as généré un nouveau modèle de disponibilité alors que
j'ai celui des personnes ressources. Peux tu utiliser qu'un seul moteur ? »

Ce que ces tests verrouillent :

1. **`FicheBenevole` ne porte plus de disponibilité.** Le champ dit un volume annuel et
   s'appelle `frequence_engagement` ; la grille de mobilisation ne le lit jamais. Deux notions
   qui se ressemblent sans se parler, c'est mobiliser sur la mauvaise.
2. **Un bénévole importé peut déclarer.** Il lui fallait une `AffectationRoleOperationnel`,
   que l'import ne créait pas : sa ligne restait un silence permanent dans la grille, c'est-à-
   dire un effectif invisible.
3. **Trois états, pas deux.** `null` efface : revenir à « je ne sais pas encore » doit être
   possible, sinon retirer un engagement oblige à affirmer un refus.
4. **Le moteur était grand ouvert.** `DisponibiliteOperationnelleViewSet` servait
   `objects.all()` sans permission ni filtrage : tout compte connecté pouvait lire les
   disponibilités de la plateforme entière et **écrire celles de n'importe qui**. On pouvait
   déclarer un inconnu indisponible la veille d'une garde.
"""
import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    AffectationRoleOperationnel, ContactInstitution, DisponibiliteOperationnelle,
    EchelonEquipe, FicheBenevole, Institution, InstitutionType, RoleOperationnel, Team,
)

URL = "/api/mes-disponibilites/"
GRILLE = "/api/disponibilites/grille/"


@pytest.fixture
def asso(db):
    type_aasc = InstitutionType.objects.create(code="AASC", libelle="Association agréée")
    return Institution.objects.create(nom="Reserve essai dispo", type=type_aasc)


@pytest.fixture
def gironde(db, asso):
    return Team.objects.create(
        name="Coordination Departementale Gironde", institution=asso,
        echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="33",
    )


def _ids(reponse):
    """Les identifiants rendus, que la vue pagine ou non."""
    donnees = reponse.data
    lignes = donnees["results"] if isinstance(donnees, dict) else donnees
    return [str(ligne["id"]) for ligne in lignes]


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


def _membre(create_user, nom, asso, equipe=None, encadrant=False, bureau=False,
            avec_affectation=True):
    u = create_user(username=f"{nom}@dispo.test", email=f"{nom}@dispo.test",
                    type="UTIL_SIMPLE")
    ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True,
                                      membre_bureau=bureau)
    if avec_affectation:
        role, _ = RoleOperationnel.objects.get_or_create(
            code="INTERVENANT", defaults={"libelle": "Intervenant"})
        AffectationRoleOperationnel.objects.create(utilisateur=u, institution=asso, role=role)
    if equipe is not None:
        equipe.members.add(u)
        if encadrant:
            equipe.membres_encadrement.add(u)
    return u


@pytest.mark.django_db
class TestUnSeulMoteur:

    def test_la_fiche_ne_porte_plus_de_disponibilite(self):
        """Le champ existe toujours, mais sous son vrai nom et avec son vrai sens."""
        champs = {f.name for f in FicheBenevole._meta.get_fields()}
        assert "frequence_engagement" in champs
        assert "disponibilite" not in champs

    def test_la_grille_ne_lit_que_le_moteur(self, create_user, asso, gironde):
        """Une fréquence d'engagement renseignée ne remplit AUCUNE case : « environ 10 jours
        par an » ne dit rien du 5 novembre."""
        benevole = _membre(create_user, "freq", asso, gironde)
        FicheBenevole.objects.create(utilisateur=benevole, frequence_engagement="FREQUENTE")
        bureau = _membre(create_user, "bur", asso, bureau=True)

        reponse = _client(bureau).get(GRILLE, {"institution": str(asso.id)})

        assert reponse.status_code == 200, reponse.data
        ligne = next(m for m in reponse.data["membres"]
                     if str(m["utilisateur"]) == str(benevole.id))
        assert all(j["disponible"] is None for j in ligne["jours"])


@pytest.mark.django_db
class TestGuichetPersonnel:

    def test_un_benevole_declare_un_jour(self, create_user, asso, gironde):
        benevole = _membre(create_user, "dec", asso, gironde)
        demain = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()

        reponse = _client(benevole).post(URL, {"date": demain, "disponible": True},
                                         format="json")

        assert reponse.status_code == 200, reponse.data
        # Écrit dans le moteur unique, et nulle part ailleurs.
        declaration = DisponibiliteOperationnelle.objects.get()
        assert declaration.affectation.utilisateur == benevole
        assert declaration.disponible is True

    def test_la_declaration_apparait_dans_la_grille_du_bureau(self, create_user, asso,
                                                              gironde):
        """Le point de tout l'exercice : ce que le bénévole coche est ce que lit la
        constitution d'équipe."""
        benevole = _membre(create_user, "vu", asso, gironde)
        bureau = _membre(create_user, "bur2", asso, bureau=True)
        demain = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        _client(benevole).post(URL, {"date": demain, "disponible": True}, format="json")

        reponse = _client(bureau).get(GRILLE, {"institution": str(asso.id)})

        ligne = next(m for m in reponse.data["membres"]
                     if str(m["utilisateur"]) == str(benevole.id))
        case = next(j for j in ligne["jours"] if str(j["date"]) == demain)
        assert case["disponible"] is True

    def test_une_nouvelle_declaration_remplace_celle_du_jour(self, create_user, asso):
        """Empiler deux déclarations contradictoires sur le même jour rendrait la grille
        dépendante de l'ordre de lecture."""
        benevole = _membre(create_user, "rem", asso)
        demain = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        client = _client(benevole)
        client.post(URL, {"date": demain, "disponible": True}, format="json")

        reponse = client.post(URL, {"date": demain, "disponible": False}, format="json")

        assert reponse.data["remplacees"] == 1
        assert DisponibiliteOperationnelle.objects.count() == 1
        assert DisponibiliteOperationnelle.objects.get().disponible is False

    def test_null_efface_et_rend_le_silence(self, create_user, asso):
        """Trois états et non deux : sans celui-ci, retirer un engagement obligerait à
        affirmer un refus."""
        benevole = _membre(create_user, "eff", asso)
        demain = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        client = _client(benevole)
        client.post(URL, {"date": demain, "disponible": True}, format="json")

        reponse = client.post(URL, {"date": demain, "disponible": None}, format="json")

        assert reponse.status_code == 200, reponse.data
        assert DisponibiliteOperationnelle.objects.count() == 0
        grille = client.get(URL).data
        case = next(j for j in grille["jours"] if str(j["date"]) == demain)
        assert case["disponible"] is None

    def test_sans_rattachement_on_le_dit(self, create_user):
        """Un citoyen sans association n'a rien à déclarer : l'écran doit pouvoir le dire
        plutôt que d'afficher une grille vide inexpliquée."""
        citoyen = create_user(username="seul@dispo.test", email="seul@dispo.test",
                              type="UTIL_SIMPLE")

        reponse = _client(citoyen).get(URL)

        assert reponse.status_code == 200
        assert reponse.data["rattachements"] == []
        assert reponse.data["jours"] == []

    def test_on_ne_declare_pas_pour_le_rattachement_d_un_autre(self, create_user, asso):
        autre = _membre(create_user, "autre", asso)
        benevole = _membre(create_user, "moi", asso)
        affectation_autre = AffectationRoleOperationnel.objects.get(utilisateur=autre)
        demain = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()

        reponse = _client(benevole).post(
            URL, {"date": demain, "disponible": True,
                  "affectation": str(affectation_autre.id)}, format="json")

        assert reponse.status_code == 403
        assert not DisponibiliteOperationnelle.objects.exists()


@pytest.mark.django_db
class TestCloisonnementDuMoteur:
    """Le défaut corrigé le 11/11/2026 : `objects.all()` sans permission ni filtrage."""

    @pytest.fixture
    def contexte(self, create_user, asso, gironde):
        titulaire = _membre(create_user, "tit", asso, gironde)
        demain = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        _client(titulaire).post(URL, {"date": demain, "disponible": True}, format="json")
        return titulaire, DisponibiliteOperationnelle.objects.get()

    def test_un_inconnu_ne_voit_pas_les_disponibilites_des_autres(self, contexte,
                                                                  create_user):
        _, declaration = contexte
        type_mairie = InstitutionType.objects.create(code="MAIRIE_DISPO", libelle="Mairie")
        mairie = Institution.objects.create(nom="Mairie dispo", type=type_mairie,
                                            commune_code="29026")
        etranger = create_user(username="etr@dispo.test", email="etr@dispo.test",
                              type="AUT_LOCALE")
        etranger.institution = mairie
        etranger.save(update_fields=["institution"])

        reponse = _client(etranger).get("/api/disponibilites/")

        assert reponse.status_code == 200
        ids = _ids(reponse)
        assert str(declaration.id) not in ids

    def test_un_inconnu_ne_peut_PAS_declarer_quelqu_un_indisponible(self, contexte,
                                                                    create_user):
        """Le cas qui rendait la dette dangereuse : `prendre_permanence` et
        `quitter_permanence` appelaient `get_object()` sur une table non filtrée."""
        _, declaration = contexte
        etranger = create_user(username="etr2@dispo.test", email="etr2@dispo.test",
                               type="AUT_LOCALE")

        reponse = _client(etranger).post(
            f"/api/disponibilites/{declaration.id}/quitter_permanence/")

        assert reponse.status_code in (403, 404)
        declaration.refresh_from_db()
        assert declaration.disponible is True

    def test_l_encadrant_de_son_equipe_y_accede(self, contexte, create_user, asso, gironde):
        """Mêmes règles que la visibilité des comptes : une disponibilité est une information
        sur quelqu'un, et l'encadrement en a la charge."""
        _, declaration = contexte
        encadrant = _membre(create_user, "enc", asso, gironde, encadrant=True)

        reponse = _client(encadrant).get("/api/disponibilites/")

        ids = _ids(reponse)
        assert str(declaration.id) in ids

    def test_le_titulaire_voit_les_siennes(self, contexte):
        titulaire, declaration = contexte

        reponse = _client(titulaire).get("/api/disponibilites/")

        ids = _ids(reponse)
        assert str(declaration.id) in ids


@pytest.mark.django_db
class TestImportDonneLeCrochet:

    def test_l_import_cree_l_affectation_sans_laquelle_rien_n_est_declarable(
            self, create_user, asso, gironde, rf):
        """Sans `AffectationRoleOperationnel`, un bénévole importé ne pouvait RIEN déclarer :
        sa ligne restait un silence permanent, soit un effectif invisible."""
        from core.imports import importer_benevoles_association

        requete = rf.post("/api/imports/benevoles/")
        requete.user = create_user(username="imp@dispo.test", email="imp@dispo.test",
                                   type="ADMIN")
        mapping = {"email": "EMAIL", "nom": "NOM", "prenom": "PRENOM"}
        lignes = [{"EMAIL": "nouveau@dispo.test", "NOM": "Durand", "PRENOM": "Marie"}]

        importer_benevoles_association(
            lignes=lignes, mapping=mapping, institution=asso, request=requete,
            inviter=False, geolocaliser=False,
        )

        from core.models import User
        nouveau = User.objects.get(email_bidx__isnull=False, username="nouveau@dispo.test")
        affectation = AffectationRoleOperationnel.objects.filter(
            utilisateur=nouveau, institution=asso).first()
        assert affectation is not None
        assert affectation.role.code == "INTERVENANT"
