"""Traçabilité des consultations dans la main courante (demande du 21/10/2026) : partir d'une
fiche et retrouver qui l'a vue, quand, depuis quelle IP et comment ; filtres cumulables avec
inclusion et exclusion ; rattachement crise / fonctionnement général ; case « Masquer les
comptes système ». Voir core/tracabilite.py, core/main_courante.py et AuditTraceMiddleware."""
import datetime
import uuid

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.audit import audit_log
from core.models import AuditAction, AuditLog, Crisis, Offer, OfferType


def _crise(nom="Crise traçabilité"):
    return Crisis.objects.create(name=nom, type="INONDATION", location="POINT (5.72 45.18)")


def _offre(titre="Groupe électrogène", crise=None, telephone="0611223344"):
    otype, _ = OfferType.objects.get_or_create(type="Traçabilité test")
    return Offer.objects.create(
        title=titre, offer_type=otype, crisis=crise, environment="PROD",
        first_name_offer="Jeanne", last_name_offer="Martin",
        email_offer="jeanne.martin@exemple.fr", phone_offer=telephone,
    )


def _derniere_ligne(utilisateur, **filtres):
    return AuditLog.objects.filter(utilisateur=utilisateur, **filtres).order_by('-date_action').first()


def _log(ip=None, utilisateur=None, objet_type="Crisis", objet_id=None, **champs):
    action, _ = AuditAction.objects.get_or_create(code="LECTURE", defaults={"libelle": "Consultation"})
    return AuditLog.objects.create(
        utilisateur=utilisateur, action=action, objet_type=objet_type, objet_id=objet_id,
        adresse_ip=ip, environment="PROD", **champs,
    )


@pytest.fixture
def admin(create_user):
    return create_user(username="enqueteur@test.fr", email="enqueteur@test.fr", type="ADMIN", is_superuser=True)


@pytest.fixture
def client_admin(admin):
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


# ── Ce que la main courante note ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTraceDesConsultations:

    def test_une_liste_note_toutes_les_fiches_renvoyees_sans_leurs_coordonnees(self, admin, client_admin):
        a, b = _offre("A"), _offre("B")

        reponse = client_admin.get(reverse('offer-list'))

        assert reponse.status_code == 200
        renvoyees = {o["id"]: o for o in reponse.data}
        assert renvoyees[str(a.id)]["email_offer"] is None and renvoyees[str(a.id)]["phone_offer"] is None
        assert renvoyees[str(a.id)]["first_name_offer"] == "Jeanne"     # le nom reste
        ligne = _derniere_ligne(admin, objet_type="Offer")
        assert {a.id, b.id} <= set(ligne.objets_ids)
        assert ligne.exposition == AuditLog.Exposition.LISTE_SANS_COORDONNEES

    def test_liste_avec_coordonnees_demandees_tracee_comme_telle(self, admin, client_admin):
        offre = _offre()

        reponse = client_admin.get(reverse('offer-list'), {"avec_coordonnees": "1"})

        assert next(o for o in reponse.data if o["id"] == str(offre.id))["phone_offer"] == "0611223344"
        assert _derniere_ligne(admin, objet_type="Offer").exposition == AuditLog.Exposition.LISTE

    def test_fiche_ouverte_tracee_avec_sa_crise(self, admin, client_admin):
        crise = _crise()
        offre = _offre(crise=crise)

        reponse = client_admin.get(reverse('offer-detail', args=[offre.id]))

        assert reponse.data["phone_offer"] == "0611223344"          # la fiche garde tout
        ligne = _derniere_ligne(admin, objet_type="Offer")
        assert ligne.exposition == AuditLog.Exposition.FICHE
        assert ligne.objet_id == offre.id and ligne.objets_ids == [offre.id]
        assert ligne.perimetre == AuditLog.Perimetre.CRISE and ligne.crise_id == crise.id

    def test_export_par_ids_trace_comme_export(self, admin, client_admin):
        AuditAction.objects.get_or_create(code="EXPORT", defaults={"libelle": "Export de données"})
        a, b, _autre = _offre("A"), _offre("B"), _offre("C")

        reponse = client_admin.get(reverse('offer-list'), {
            "ids": f"{a.id},{b.id}", "avec_coordonnees": "1", "motif": "export",
        })

        assert {o["id"] for o in reponse.data} == {str(a.id), str(b.id)}
        ligne = _derniere_ligne(admin, objet_type="Offer")
        assert ligne.exposition == AuditLog.Exposition.EXPORT
        assert ligne.action.code == "EXPORT"
        assert set(ligne.objets_ids) == {a.id, b.id}

    def test_termes_de_recherche_notes_sans_secrets_ni_pagination(self, admin, client_admin):
        client_admin.get(reverse('offer-list'), {"search": "Dupont", "page": 1, "token": "secret-abc"})

        ligne = _derniere_ligne(admin, objet_type="Offer")
        assert ligne.recherche == {"search": "Dupont"}

    def test_perimetre_general_multi_et_hors_crise(self, admin, client_admin):
        crise_a, crise_b = _crise("A"), _crise("B")
        sans = _offre("Sans crise")
        client_admin.get(reverse('offer-detail', args=[sans.id]))
        assert _derniere_ligne(admin, objet_type="Offer").perimetre == AuditLog.Perimetre.GENERAL

        _offre("En A", crise=crise_a), _offre("En B", crise=crise_b)
        client_admin.get(reverse('offer-list'))
        assert _derniere_ligne(admin, objet_type="Offer").perimetre == AuditLog.Perimetre.MULTI

        client_admin.get(reverse('offer-list'), {"crisis": str(crise_a.id)})
        ligne = _derniere_ligne(admin, objet_type="Offer")
        assert ligne.perimetre == AuditLog.Perimetre.CRISE and ligne.crise_id == crise_a.id

    def test_compte_systeme_marque_a_l_ecriture(self, create_user, rf):
        pont = create_user(username="pont-test@assista-crise.local", email="pont-test@assista-crise.local", type="ADMIN")
        humain = create_user(username="humain@test.fr", email="humain@test.fr", type="ADMIN")
        AuditAction.objects.get_or_create(code="CREATION", defaults={"libelle": "Création"})
        for compte in (pont, humain):
            requete = rf.post("/api/x/")
            requete.user = compte
            audit_log(request=requete, action_code="CREATION", objet_type="Test")

        assert _derniere_ligne(pont).compte_systeme is True
        assert _derniere_ligne(humain).compte_systeme is False

    def test_identifiant_de_crise_inconnu_ne_fait_pas_perdre_la_ligne(self, admin, client_admin):
        client_admin.get(reverse('offer-list'), {"crisis": str(uuid.uuid4())})
        assert _derniere_ligne(admin, objet_type="Offer") is not None


# ── Filtres cumulables ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestFiltresMainCourante:

    def _ids(self, client, **params):
        reponse = client.get(reverse('auditlog-list'), {"page": 1, "page_size": 100, **params})
        assert reponse.status_code == 200, reponse.data
        return {e["id"] for e in reponse.data["results"]}

    def test_reseau_inclus_sauf_une_machine(self, client_admin):
        l1, l2 = _log("10.0.0.1"), _log("10.0.0.2")
        hors = _log("192.168.1.5")

        ids = self._ids(client_admin, ip="10.0.0.0/8", ip_exclu="10.0.0.2")

        assert str(l1.id) in ids and str(l2.id) not in ids and str(hors.id) not in ids

    def test_exclure_une_ip_garde_les_lignes_sans_ip(self, client_admin):
        sans_ip, exclue = _log(None), _log("10.9.9.9")

        ids = self._ids(client_admin, ip_exclu="10.9.9.9")

        assert str(sans_ip.id) in ids and str(exclue.id) not in ids

    def test_utilisateur_et_ip_cumules(self, create_user, client_admin):
        fred = create_user(username="fred@loire.fr", email="fred@loire.fr", type="AUT_LOCALE")
        bon = _log("82.64.29.10", utilisateur=fred)
        poste_exclu = _log("82.64.29.195", utilisateur=fred)
        autre_personne = _log("82.64.29.10")

        ids = self._ids(client_admin, utilisateur="fred@loire", ip="82.64.29.0/24", ip_exclu="82.64.29.195")

        assert str(bon.id) in ids
        assert str(poste_exclu.id) not in ids and str(autre_personne.id) not in ids

    def test_exclure_un_utilisateur_garde_les_anonymes(self, create_user, client_admin):
        fred = create_user(username="fred2@loire.fr", email="fred2@loire.fr", type="AUT_LOCALE")
        anonyme, de_fred = _log("1.1.1.1"), _log("1.1.1.1", utilisateur=fred)

        ids = self._ids(client_admin, utilisateur_exclu="fred2@loire.fr")

        assert str(anonyme.id) in ids and str(de_fred.id) not in ids

    def test_objet_trouve_fiche_ouverte_et_presence_dans_une_liste(self, client_admin):
        cible, autre = uuid.uuid4(), uuid.uuid4()
        fiche = _log(objet_type="Offer", objet_id=cible)
        liste = _log(objet_type="Offer", objets_ids=[autre, cible])
        sans = _log(objet_type="Offer", objets_ids=[autre])

        ids = self._ids(client_admin, objet=str(cible))

        assert {str(fiche.id), str(liste.id)} <= ids and str(sans.id) not in ids

    def test_perimetre_avec_non_determinable(self, client_admin):
        crise = _crise()
        en_crise = _log(perimetre="CRISE", crise=crise)
        general = _log(perimetre="GENERAL")
        inconnu = _log()

        assert self._ids(client_admin, perimetre="GENERAL") & {str(en_crise.id), str(general.id), str(inconnu.id)} == {str(general.id)}
        ids = self._ids(client_admin, perimetre=["CRISE", "INCONNU"])
        assert {str(en_crise.id), str(inconnu.id)} <= ids and str(general.id) not in ids
        assert str(en_crise.id) in self._ids(client_admin, crise=str(crise.id))

    def test_masquer_les_comptes_systeme(self, client_admin):
        machine, humain = _log(compte_systeme=True), _log()

        ids = self._ids(client_admin, masquer_systeme="1")

        assert str(humain.id) in ids and str(machine.id) not in ids

    def test_terme_recherche(self, client_admin):
        cherche = _log(recherche={"search": "Dupont"})
        autre = _log(recherche={"search": "Martin"})

        ids = self._ids(client_admin, recherche="dupont")

        assert str(cherche.id) in ids and str(autre.id) not in ids

    def test_date_de_fin_seule_couvre_toute_la_journee(self, client_admin):
        ligne = _log()
        AuditLog.objects.filter(pk=ligne.pk).update(
            date_action=timezone.make_aware(datetime.datetime(2026, 10, 20, 18, 30)))

        assert str(ligne.id) in self._ids(client_admin, date_debut="2026-10-20", date_fin="2026-10-20")

    def test_saisie_invalide_refusee_plutot_qu_ignoree(self, client_admin):
        reponse = client_admin.get(reverse('auditlog-list'), {"page": 1, "ip": "pas-une-ip"})
        assert reponse.status_code == 400

    def test_libelle_de_la_fiche_et_fiche_supprimee(self, client_admin):
        offre = _offre("Groupe électrogène 5 kVA")
        ligne = _log(objet_type="Offer", objet_id=offre.id)
        disparue = _log(objet_type="Offer", objet_id=uuid.uuid4())

        reponse = client_admin.get(reverse('auditlog-list'), {"page": 1, "page_size": 100})
        par_id = {e["id"]: e for e in reponse.data["results"]}

        assert par_id[str(ligne.id)]["objet_libelle"] == "Groupe électrogène 5 kVA"
        assert par_id[str(ligne.id)]["objet_type_libelle"] == "Offre"
        assert par_id[str(disparue.id)]["objet_libelle"] == "fiche supprimée"


# ── Recherche de fiche, export navigateur, reprise de l'historique ───────────────────────

@pytest.mark.django_db
class TestOutilsEnquete:

    def test_retrouver_une_annonce_par_son_telephone(self, client_admin):
        offre = _offre(telephone="0699887766")

        reponse = client_admin.get(reverse('auditlog-fiches'), {"q": "0699887766", "type": "Offer"})

        assert reponse.status_code == 200
        assert [r["id"] for r in reponse.data["resultats"]] == [str(offre.id)]

    def test_retrouver_par_titre_ou_identifiant(self, client_admin):
        offre = _offre("Tronçonneuse thermique")
        par_titre = client_admin.get(reverse('auditlog-fiches'), {"q": "tronçonneuse"}).data["resultats"]
        par_id = client_admin.get(reverse('auditlog-fiches'), {"q": str(offre.id)}).data["resultats"]
        assert str(offre.id) in [r["id"] for r in par_titre]
        assert [r["id"] for r in par_id] == [str(offre.id)]

    def test_recherche_de_fiche_reservee_au_super_admin(self, create_user):
        user = create_user(username="mairie@test.fr", email="mairie@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=user)
        assert client.get(reverse('auditlog-fiches'), {"q": "x"}).status_code == 403

    def test_export_fabrique_dans_le_navigateur(self, admin, client_admin):
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        reponse = client_admin.post(reverse('auditlog-tracer-export'), {
            "objet_type": "RessourceMobilisee", "ids": ids, "fichier": "ressources.csv",
        }, format="json")

        assert reponse.status_code == 204
        ligne = _derniere_ligne(admin, action__code="EXPORT", objet_type="RessourceMobilisee")
        assert ligne.exposition == AuditLog.Exposition.EXPORT
        assert {str(i) for i in ligne.objets_ids} == set(ids)

    def test_reprise_de_l_historique(self, create_user):
        pont = create_user(username="pont-reprise@assista-crise.local", email="pont-reprise@assista-crise.local", type="ADMIN")
        crise = _crise()
        offre = _offre(crise=crise)
        fiche = _log(objet_type="Offer", objet_id=offre.id)
        connexion = _log(objet_type="auth_me")
        liste = _log(objet_type="Offer")
        machine = _log(utilisateur=pont, objet_type="CompagnonMeshCore")

        call_command("reprendre_main_courante", "--dry-run")
        fiche.refresh_from_db()
        assert fiche.perimetre is None                     # simulation : rien d'écrit

        call_command("reprendre_main_courante")
        for ligne in (fiche, connexion, liste, machine):
            ligne.refresh_from_db()
        assert fiche.perimetre == "CRISE" and fiche.crise_id == crise.id
        assert connexion.perimetre == "GENERAL"
        assert liste.perimetre is None                     # liste sans fiche : non déterminable
        assert machine.compte_systeme is True and machine.perimetre == "GENERAL"


@pytest.mark.django_db
class TestVerificationDeFonctionnement:
    """Sonde de connectivité des satellites (22/10/2026) : tracée comme « Vérification de
    fonctionnement » d'une source identifiée, et masquée avec les comptes système -- plus comme
    une consultation anonyme en échec de la racine /api/."""

    @pytest.fixture(autouse=True)
    def _action(self):
        AuditAction.objects.get_or_create(code="VERIFICATION", defaults={"libelle": "Vérification de fonctionnement"})

    def test_sonde_identifiee(self):
        from core.models import Institution, InstitutionType, Satellite
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(nom="Mairie sonde", type=itype)
        satellite = Satellite.objects.create(institution=institution, nom="gmc-poste-2", profil="FULL")

        reponse = APIClient().get(reverse('sonde'), HTTP_X_SONDE_SOURCE=f"satellite:{satellite.id}")

        assert reponse.status_code == 200
        ligne = AuditLog.objects.filter(action__code="VERIFICATION").latest('date_action')
        assert ligne.succes and ligne.compte_systeme and ligne.objet_id == satellite.id
        assert "gmc-poste-2" in ligne.commentaire
        assert not AuditLog.objects.filter(commentaire__icontains="api-root").exists()

    def test_ancien_satellite_sur_la_racine(self):
        APIClient().get("/api/")

        ligne = AuditLog.objects.latest('date_action')
        assert ligne.action.code == "VERIFICATION" and ligne.compte_systeme and ligne.succes

    def test_masquee_avec_les_comptes_systeme(self, client_admin):
        APIClient().get(reverse('sonde'))
        sonde = AuditLog.objects.filter(action__code="VERIFICATION").latest('date_action')

        reponse = client_admin.get(reverse('auditlog-list'), {"page": 1, "page_size": 100, "masquer_systeme": "1"})

        assert str(sonde.id) not in {e["id"] for e in reponse.data["results"]}
