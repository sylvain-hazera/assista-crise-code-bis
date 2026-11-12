"""Zone DEMO : aucune donnée nominative d'une personne réelle ne doit s'afficher.

Pourquoi ce fichier existe : `User` est **partagé** entre PROD et DEMO (un seul compte, un
`demo_role`), contrairement à tout le contenu, cloisonné par `EnvironmentScopedModel`. Les
adresses et téléphones étaient déjà masqués (`mask_email`, `mask_phone`) — **les noms, jamais**,
et plusieurs vues rendaient en plus l'adresse en clair. Les pages de démonstration affichaient
donc les noms, et parfois les coordonnées, de vraies personnes de la production (constaté par
l'exploitant le 07/11/2026).

Le masquage se fait à un seul endroit (`core/permissions.py:nom_affichable`) et jamais dans le
contenu d'un email : un message envoyé à une vraie personne doit porter son vrai nom.
"""
import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core.permissions import (
    est_son_propre_compte, mask_email, mask_phone, nom_affichable, pseudonyme,
)


class FausseRequete:
    """Le minimum que lisent nom_affichable/est_son_propre_compte."""

    def __init__(self, zone, user=None):
        self.META = {"HTTP_X_ENVIRONMENT": zone}
        self.user = user


@pytest.fixture
def personne(create_user):
    return create_user(
        username="jean.dupont@mairie-reelle.fr", email="jean.dupont@mairie-reelle.fr",
        first_name="Jean", last_name="Dupont", type="AUT_LOCALE",
    )


@pytest.fixture
def autre(create_user):
    return create_user(
        username="autre@mairie-reelle.fr", email="autre@mairie-reelle.fr",
        first_name="Marie", last_name="Durand", type="SECOURS",
    )


@pytest.mark.django_db
class TestNomAffichable:

    def test_en_prod_le_vrai_nom_est_rendu(self, personne):
        assert nom_affichable(personne, FausseRequete("PROD", personne)) == "Jean Dupont"

    def test_en_demo_le_nom_d_un_autre_est_pseudonymise(self, personne, autre):
        rendu = nom_affichable(personne, FausseRequete("DEMO", autre))
        assert "Jean" not in rendu
        assert "Dupont" not in rendu
        assert "Démo-" in rendu

    def test_en_demo_on_voit_toujours_son_propre_nom(self, personne):
        """Se masquer à soi-même ne protège personne et rend la démonstration
        incompréhensible."""
        assert nom_affichable(personne, FausseRequete("DEMO", personne)) == "Jean Dupont"

    def test_le_pseudonyme_est_stable(self, personne, autre):
        requete = FausseRequete("DEMO", autre)
        assert nom_affichable(personne, requete) == nom_affichable(personne, requete)

    def test_deux_personnes_ont_des_pseudonymes_differents(self, personne, autre, create_user):
        tiers = create_user(username="t@x.fr", email="t@x.fr", first_name="Jean", last_name="Dupont")
        requete = FausseRequete("DEMO", autre)
        # Deux homonymes restent distincts : le pseudonyme dérive de l'identifiant, pas du nom.
        assert nom_affichable(personne, requete) != nom_affichable(tiers, requete)

    def test_aucun_repli_sur_l_email(self, create_user, autre):
        """Le repli appartient à l'appelant (`or u.email`), jamais à la fonction : un repli
        interne aurait fait apparaître des adresses là où le code renvoyait None."""
        sans_nom = create_user(username="sansnom@x.fr", email="sansnom@x.fr",
                               first_name="", last_name="")
        assert nom_affichable(sans_nom, FausseRequete("PROD", autre)) == ""
        # En DEMO, le pseudonyme est toujours non vide : le repli de l'appelant ne s'applique
        # donc jamais, et aucune adresse ne fuit par ce chemin.
        assert nom_affichable(sans_nom, FausseRequete("DEMO", autre))

    def test_sans_requete_rien_n_est_masque(self, personne):
        """Appelé hors requête (tâche de fond, commande) : pas de zone, pas de masquage."""
        assert nom_affichable(personne, None) == "Jean Dupont"

    def test_un_utilisateur_absent_ne_fait_pas_tomber_la_vue(self):
        assert nom_affichable(None, FausseRequete("DEMO")) is None

    def test_le_patronyme_factice_ne_peut_pas_passer_pour_un_vrai(self, personne):
        """On ne fabrique pas un faux nom de famille crédible : il pourrait être pris pour une
        vraie personne, voire coïncider avec l'une."""
        _, patronyme = pseudonyme(personne)
        assert patronyme.startswith("Démo-")

    def test_est_son_propre_compte(self, personne, autre):
        assert est_son_propre_compte(FausseRequete("DEMO", personne), personne)
        assert not est_son_propre_compte(FausseRequete("DEMO", autre), personne)
        assert not est_son_propre_compte(None, personne)


@pytest.mark.django_db
class TestFicheUtilisateur:
    """La page Utilisateurs de l'administration."""

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_la_fiche_d_un_autre_est_pseudonymisee_en_demo(self, personne, create_user):
        admin = create_user(username="admin-anon@x.fr", email="admin-anon@x.fr", type="ADMIN",
                            demo_role="ADMIN", first_name="Ada", last_name="Admin")
        reponse = self._client(admin).get(f"/api/users/{personne.id}/", HTTP_X_ENVIRONMENT="DEMO")
        assert reponse.status_code == 200, reponse.data
        assert reponse.data["first_name"] != "Jean"
        assert reponse.data["last_name"] != "Dupont"
        assert reponse.data["email"] == mask_email(personne.email)
        assert "Démo-" in reponse.data["last_name"]

    def test_la_fiche_en_prod_reste_intacte(self, personne, create_user):
        admin = create_user(username="admin-anon2@x.fr", email="admin-anon2@x.fr", type="ADMIN")
        reponse = self._client(admin).get(f"/api/users/{personne.id}/")
        assert reponse.status_code == 200
        assert reponse.data["first_name"] == "Jean"
        assert reponse.data["last_name"] == "Dupont"
        assert reponse.data["email"] == personne.email

    def test_sa_propre_fiche_reste_lisible_en_demo(self, create_user):
        moi = create_user(username="moi-anon@x.fr", email="moi-anon@x.fr", type="ADMIN",
                          demo_role="ADMIN", first_name="Ada", last_name="Lovelace")
        reponse = self._client(moi).get(f"/api/users/{moi.id}/", HTTP_X_ENVIRONMENT="DEMO")
        assert reponse.status_code == 200
        assert reponse.data["first_name"] == "Ada"
        assert reponse.data["last_name"] == "Lovelace"


@pytest.mark.django_db
class TestSupervisionPcCrise:
    """La page signalée par l'exploitant : /admin/supervision-pc-crise.

    Elle liste, pour chaque crise active dont le PC Crise ne répond plus, les **contacts de
    secours** de la collectivité : nom, fonction, téléphone, adresse. C'est la page faite pour
    joindre un humain quand la machine est muette — et en démonstration, il n'y a personne à
    joindre, donc rien à afficher en clair."""

    def _preparer(self, create_user, personne):
        from core.models import (
            ContactInstitution, Crisis, ImplicationInstitution, Institution, InstitutionType,
            StatutImplication, TypeImplication,
        )
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(nom="Mairie Supervision", type=itype,
                                                 commune_code="42001")
        personne.phone_number = "0612345678"
        personne.institution = institution
        personne.save(update_fields=["phone_number", "institution"])
        ContactInstitution.objects.create(institution=institution, utilisateur=personne,
                                          actif=True, fonction="Adjoint", environment="PROD")
        # La page ne liste que les institutions ACTRICES d'une crise active, et seulement quand
        # leur PC Crise n'est pas actif : ici aucun satellite, donc les contacts de secours
        # s'affichent -- c'est exactement le cas où la page sert.
        for zone in ("PROD", "DEMO"):
            crise = Crisis.objects.create(
                name=f"Crue {zone}", description="x", zone_communes=["42001"], environment=zone,
                location=Point(4.0, 45.5, srid=4326),
            )
            ImplicationInstitution.objects.create(
                crise=crise, institution=institution, type_implication=TypeImplication.ACTEUR,
                statut=StatutImplication.VALIDEE, environment=zone,
            )
        return institution

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_les_contacts_de_secours_sont_masques_en_demo(self, create_user, personne):
        """Le cas exact signalé le 07/11/2026."""
        self._preparer(create_user, personne)
        admin = create_user(username="admin-sup@x.fr", email="admin-sup@x.fr", type="ADMIN",
                            demo_role="ADMIN", first_name="Ada", last_name="Admin")
        reponse = self._client(admin).get("/api/satellites/supervision/", HTTP_X_ENVIRONMENT="DEMO")
        assert reponse.status_code == 200, reponse.data
        contacts = [c for ligne in reponse.data for c in ligne["contacts_secours"]]
        assert contacts, "la page doit bien lister un contact de secours"
        for contact in contacts:
            assert "Jean" not in contact["nom"] and "Dupont" not in contact["nom"]
            assert contact["telephone"] != "0612345678"
            assert contact["email"] != "jean.dupont@mairie-reelle.fr"
            assert contact["email"].endswith("@zone.demo")
            # La fonction reste : elle dit à qui on s'adresse sans désigner personne.
            assert contact["fonction"] == "Adjoint"

    def test_en_prod_les_contacts_restent_joignables(self, create_user, personne):
        """Le but de cette page est de joindre quelqu'un : en production, rien ne doit être
        masqué, sinon elle ne sert plus à rien."""
        self._preparer(create_user, personne)
        admin = create_user(username="admin-sup2@x.fr", email="admin-sup2@x.fr", type="ADMIN")
        reponse = self._client(admin).get("/api/satellites/supervision/")
        assert reponse.status_code == 200
        contacts = [c for ligne in reponse.data for c in ligne["contacts_secours"]]
        assert contacts
        assert contacts[0]["nom"] == "Jean Dupont"
        assert contacts[0]["telephone"] == "0612345678"
        assert contacts[0]["email"] == "jean.dupont@mairie-reelle.fr"


@pytest.mark.django_db
class TestPasDeRegressionDansLeCode:
    """Garde structurel : le masquage ne doit pas dépendre de 60 endroits qui s'en souviennent.

    Sans ce test, la prochaine vue qui composera un nom à la main réintroduira la fuite en
    silence — c'est exactement ce qui s'était produit."""

    # Champs dénormalisés d'un modèle CLOISONNÉ (Request/Offer/Information) : en zone DEMO ce
    # sont des données engendrées par Faker, jamais une personne réelle.
    SUFFIXES_AUTORISES = ("_request", "_offer", "_information")

    # Une lecture directe légitime se déclare par un commentaire `# nom-reel-assume: <raison>`
    # sur la ligne ou juste au-dessus. Déclarer plutôt que lister des numéros de ligne : une
    # liste de numéros pourrit au premier déplacement de code, et surtout elle n'oblige pas à
    # écrire POURQUOI.
    MARQUEUR = "nom-reel-assume"

    def _compositions(self, chemin):
        """Lectures directes de `first_name` sur un User, non déclarées."""
        import re
        from pathlib import Path
        racine = Path(__file__).resolve().parents[3]
        lignes = (racine / chemin).read_text(encoding="utf-8").split("\n")
        trouvees = []
        for i, ligne in enumerate(lignes):
            for m in re.finditer(r"([\w.]+)\.first_name\b(\w*)", ligne):
                if m.group(2) in self.SUFFIXES_AUTORISES:
                    continue
                # Fenêtre de trois lignes : la déclaration peut précéder l'ouverture d'une
                # expression multiligne (un `lambda` ou un dictionnaire, par exemple).
                voisinage = ligne + "".join(lignes[max(0, i - 3):i])
                if self.MARQUEUR in voisinage:
                    continue
                trouvees.append((i + 1, ligne.strip()))
        return trouvees

    def test_personne_n_appelle_nom_affichable_sans_requete(self):
        """`nom_affichable(user, None)` rend le VRAI nom, même en zone de démonstration.

        C'est écrit dans sa docstring, et c'est exactement le piège : la fonction ne lève pas,
        elle ne prévient pas, elle rend simplement le nom réel. Appelée sans requête depuis un
        module qui construit une réponse d'API, elle réintroduit la fuite que tout ce fichier
        existe pour empêcher — erreur commise le 12/11/2026 en écrivant `planning_equipe.py`,
        et attrapée à la relecture, pas par un test. Celui-ci la rattraperait.

        Une lecture volontairement non masquée (un email, un journal) se déclare avec le même
        marqueur que les autres."""
        import re
        from pathlib import Path

        racine = Path(__file__).resolve().parents[2]
        fautives = []
        for chemin in sorted(racine.glob("*.py")):
            lignes = chemin.read_text(encoding="utf-8").split("\n")
            for i, ligne in enumerate(lignes):
                if not re.search(r"nom_affichable\([^)]*,\s*None\s*\)", ligne):
                    continue
                voisinage = ligne + "".join(lignes[max(0, i - 3):i])
                if self.MARQUEUR in voisinage:
                    continue
                fautives.append((chemin.name, i + 1, ligne.strip()))

        assert fautives == [], (
            "nom_affichable(..., None) rend le vrai nom en zone DEMO : passer la requête, "
            f"ou déclarer la lecture avec `# {self.MARQUEUR}: …`. {fautives}"
        )

    def test_les_serialiseurs_ne_composent_plus_de_nom_a_la_main(self):
        restantes = self._compositions("core/serializers.py")
        assert restantes == [], (
            "Composition de nom à la main dans serializers.py : utiliser "
            f"nom_affichable(user, self.context.get('request')). {restantes}"
        )

    def test_les_vues_ne_lisent_le_nom_en_direct_que_la_ou_c_est_declare(self):
        """Un email envoyé à une vraie personne doit porter son VRAI nom, et un journal d'audit
        ne doit pas mentir : ces lectures sont légitimes, mais elles doivent être DÉCLARÉES.

        Les contenus d'email sont reconnus à leur forme (« Bonjour », « Nom : »…) ; tout le
        reste doit porter un `# nom-reel-assume: <raison>`."""
        import re
        suspectes = []
        for num, ligne in self._compositions("core/views.py"):
            if re.search(r"Bonjour|Nom :|souhaite rejoindre|a confirmé|subject|\.lower\(\)|nom_complet", ligne):
                continue
            suspectes.append((num, ligne))
        assert suspectes == [], (
            "Lecture directe de first_name non déclarée dans views.py : passer par "
            f"nom_affichable(user, request), ou expliquer avec `# {self.MARQUEUR}: …`. {suspectes}"
        )
