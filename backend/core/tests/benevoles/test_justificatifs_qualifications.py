"""Justificatifs des qualifications : dépôt, protection, vérification, notification.

Demande du 11/11/2026. Ce que ces tests verrouillent :

1. **Un bénévole peut déposer sa pièce.** Il est `UTIL_SIMPLE`, et le viewset exigeait
   `IsInstitutionalActor` — il ne pouvait donc rien déposer, c'est-à-dire rien faire de ce que
   cette page lui demande.
2. **La règle d'accès aux PIÈCES est plus étroite que celle des comptes.** Un collègue d'une
   institution sans hiérarchie peut voir qu'un titre existe ; voir le diplôme suppose une
   responsabilité sur la personne. Seules la personne, le bureau de son association et
   l'encadrement de ses équipes (ou d'une équipe au-dessus) y accèdent.
3. **Le statut ne se pose jamais par PATCH.** Sans cela, quelqu'un passerait sa propre
   qualification en « vérifiée » et viderait de son sens la vérification par l'encadrement.
4. **Un refus exige un motif**, et un nouveau dépôt remet le titre à instruire : sinon le refus
   resterait affiché sur un justificatif corrigé.
5. **Le fichier n'est jamais servi comme URL** : seule l'action dédiée le rend, avec une trace
   de qui l'a consulté.
"""
import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core.models import (
    AuditLog, ContactInstitution, EchelonEquipe, Institution, InstitutionType, Qualification,
    QualificationMembre, StatutQualification, Team, User,
)

URL = "/api/qualifications-membres/"


def piece(nom="PSC1-2024.pdf"):
    """Un PDF minimal : le validateur reconnaît l'en-tête %PDF-."""
    return SimpleUploadedFile(nom, b"%PDF-1.4 contenu", content_type="application/pdf")


@pytest.fixture
def asso(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_JUST',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom="Association Justificatifs", type=itype)


@pytest.fixture
def arbre(asso):
    national = Team.objects.create(name="Nationale", institution=asso,
                                   echelon=EchelonEquipe.NATIONAL, territoire_code="FR")
    gironde = Team.objects.create(name="Gironde", institution=asso,
                                  echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="33",
                                  equipe_parente=national)
    savoie = Team.objects.create(name="Savoie", institution=asso,
                                 echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="73",
                                 equipe_parente=national)
    return national, gironde, savoie


@pytest.fixture
def psc1(db):
    return Qualification.objects.create(nom="PSC1 (justificatifs test)")


def _membre(create_user, nom, asso, equipe=None, bureau=False, encadrant=False,
            type_compte='UTIL_SIMPLE'):
    u = create_user(username=f'{nom}@just.test', email=f'{nom}@just.test', type=type_compte)
    ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True,
                                      membre_bureau=bureau)
    if equipe is not None:
        equipe.members.add(u)
        if encadrant:
            equipe.membres_encadrement.add(u)
    return u


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.mark.django_db
class TestCatalogueDesTitres:
    """Le catalogue (`/api/qualifications/`) doit être LISIBLE par un bénévole.

    Même défaut que sur `QualificationMembreViewSet`, trouvé en construisant l'écran de dépôt :
    `IsInstitutionalActor` fermait le catalogue à un `UTIL_SIMPLE`, donc la page n'avait aucun
    titre à proposer — inutilisable pour exactement les gens à qui elle est destinée.

    « PSE1 », « permis C » sont un vocabulaire partagé, pas une donnée personnelle. Ce qui est
    personnel est de DÉTENIR un titre, et cela vit dans `QualificationMembre`, qui garde son
    cloisonnement."""

    def test_un_benevole_lit_le_catalogue(self, create_user, asso, psc1):
        benevole = _membre(create_user, 'cat', asso)

        reponse = _client(benevole).get("/api/qualifications/")

        assert reponse.status_code == 200, reponse.data
        assert str(psc1.id) in [t["id"] for t in reponse.data]

    def test_un_benevole_n_ecrit_PAS_dans_le_catalogue(self, create_user, asso):
        """Lecture ouverte, écriture non : le vocabulaire partagé reste tenu par les
        institutions. Un bénévole qui ne trouve pas son titre le demande, il ne l'invente pas
        — sinon le catalogue se peuple de doublons personnels."""
        benevole = _membre(create_user, 'cat2', asso)

        reponse = _client(benevole).post("/api/qualifications/", {"nom": "Brevet maison"})

        assert reponse.status_code == 403
        assert not Qualification.objects.filter(nom="Brevet maison").exists()

    def test_un_anonyme_n_y_accede_pas(self):
        """Ouvert aux comptes CONNECTÉS, pas au public : le catalogue dit quelles compétences
        l'organisation suit, ce qui n'a pas à être lisible de l'extérieur."""
        assert APIClient().get("/api/qualifications/").status_code in (401, 403)


@pytest.mark.django_db
class TestDepotParLeMembre:

    def test_un_benevole_UTIL_SIMPLE_peut_deposer_sa_piece(self, create_user, asso, arbre,
                                                            psc1):
        """Le viewset exigeait `IsInstitutionalActor` : un bénévole ne pouvait rien déposer."""
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'ben', asso, gironde)

        reponse = _client(benevole).post(URL, {
            "qualification": str(psc1.id), "justificatif": piece(),
        }, format='multipart')

        assert reponse.status_code == 201, reponse.data
        titre = QualificationMembre.objects.get()
        assert titre.utilisateur == benevole
        assert titre.statut == StatutQualification.DECLAREE
        assert titre.justificatif_depose_le is not None

    def test_le_titulaire_par_defaut_est_l_appelant(self, create_user, asso, arbre, psc1):
        """Il n'a pas à désigner son propre compte, et surtout ne doit pas pouvoir en désigner
        un autre."""
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'ben2', asso, gironde)
        autre = _membre(create_user, 'autre2', asso, gironde)

        reponse = _client(benevole).post(URL, {
            "qualification": str(psc1.id), "utilisateur": str(autre.id),
        }, format='multipart')
        assert reponse.status_code == 403

    def test_le_nom_du_fichier_depose_est_conserve(self, create_user, asso, arbre, psc1):
        """Le nom réel est un UUID : l'écran afficherait « a3f2….pdf »."""
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'ben3', asso, gironde)
        _client(benevole).post(URL, {"qualification": str(psc1.id),
                                     "justificatif": piece("Mon-PSC1.pdf")},
                               format='multipart')
        assert QualificationMembre.objects.get().justificatif_nom == "Mon-PSC1.pdf"

    def test_le_fichier_n_est_jamais_servi_dans_la_reponse(self, create_user, asso, arbre,
                                                            psc1):
        """Servir une URL contournerait le contrôle d'accès."""
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'ben4', asso, gironde)
        reponse = _client(benevole).post(URL, {"qualification": str(psc1.id),
                                               "justificatif": piece()},
                                         format='multipart')
        assert 'justificatif' not in reponse.data
        assert reponse.data['a_justificatif'] is True


@pytest.mark.django_db
class TestQuiPeutVoirLaPiece:

    @pytest.fixture
    def titre(self, create_user, asso, arbre, psc1):
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'titulaire', asso, gironde)
        _client(benevole).post(URL, {"qualification": str(psc1.id), "justificatif": piece()},
                               format='multipart')
        return QualificationMembre.objects.get()

    def test_le_titulaire_telecharge_la_sienne(self, titre):
        reponse = _client(titre.utilisateur).get(f"{URL}{titre.id}/justificatif/")
        assert reponse.status_code == 200
        assert 'attachment' in reponse['Content-Disposition']

    def test_l_encadrant_de_son_equipe_y_accede(self, titre, create_user, asso, arbre):
        _, gironde, _ = arbre
        chef = _membre(create_user, 'chef33', asso, gironde, encadrant=True,
                       type_compte='SECOURS')
        assert _client(chef).get(f"{URL}{titre.id}/justificatif/").status_code == 200

    def test_l_encadrant_national_y_accede_aussi(self, titre, create_user, asso, arbre):
        """La hiérarchie descend : le national a la charge de tout le monde."""
        national, _, _ = arbre
        chef = _membre(create_user, 'chefnat', asso, national, encadrant=True,
                       type_compte='SECOURS')
        assert _client(chef).get(f"{URL}{titre.id}/justificatif/").status_code == 200

    def test_l_encadrant_d_un_AUTRE_departement_est_refuse(self, titre, create_user, asso,
                                                            arbre):
        """« Seules les hiérarchies spécifiques » : la Savoie n'a pas la charge de la Gironde."""
        _, _, savoie = arbre
        chef = _membre(create_user, 'chef73', asso, savoie, encadrant=True,
                       type_compte='SECOURS')
        assert _client(chef).get(f"{URL}{titre.id}/justificatif/").status_code == 403

    def test_un_simple_collegue_de_la_meme_equipe_est_refuse(self, titre, create_user, asso,
                                                              arbre):
        """La règle des PIÈCES est plus étroite que celle des comptes : être dans la même
        équipe ne donne aucune charge sur la personne."""
        _, gironde, _ = arbre
        collegue = _membre(create_user, 'collegue', asso, gironde)
        assert _client(collegue).get(f"{URL}{titre.id}/justificatif/").status_code == 403

    def test_le_bureau_y_accede(self, titre, create_user, asso):
        bureau = _membre(create_user, 'bureau', asso, bureau=True, type_compte='SECOURS')
        assert _client(bureau).get(f"{URL}{titre.id}/justificatif/").status_code == 200

    def test_un_refus_est_journalise(self, titre, create_user, asso, arbre):
        _, _, savoie = arbre
        chef = _membre(create_user, 'chef73b', asso, savoie, encadrant=True,
                       type_compte='SECOURS')
        _client(chef).get(f"{URL}{titre.id}/justificatif/")

        echecs = AuditLog.objects.filter(objet_type="QualificationMembre", succes=False)
        assert echecs.exists()

    def test_chaque_consultation_est_journalisee(self, titre, create_user, asso, arbre):
        """Savoir QUI a consulté le diplôme de quelqu'un fait partie de la protection."""
        _, gironde, _ = arbre
        chef = _membre(create_user, 'chef33b', asso, gironde, encadrant=True,
                       type_compte='SECOURS')
        _client(chef).get(f"{URL}{titre.id}/justificatif/")

        assert AuditLog.objects.filter(
            objet_type="QualificationMembre", objet_id=titre.id, succes=True,
        ).exists()


@pytest.mark.django_db
class TestVerification:

    @pytest.fixture
    def contexte(self, create_user, asso, arbre, psc1):
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'titu2', asso, gironde)
        chef = _membre(create_user, 'chef2', asso, gironde, encadrant=True,
                       type_compte='SECOURS')
        _client(benevole).post(URL, {"qualification": str(psc1.id), "justificatif": piece()},
                               format='multipart')
        return QualificationMembre.objects.get(), benevole, chef

    def test_l_encadrant_verifie(self, contexte):
        titre, _, chef = contexte
        reponse = _client(chef).post(f"{URL}{titre.id}/verifier/", {}, format='json')
        assert reponse.status_code == 200, reponse.data

        titre.refresh_from_db()
        assert titre.statut == StatutQualification.VERIFIEE
        assert titre.verifie_par == chef
        assert titre.verifie_le is not None

    def test_personne_ne_verifie_son_propre_titre(self, contexte):
        titre, benevole, _ = contexte
        assert _client(benevole).post(f"{URL}{titre.id}/verifier/", {},
                                      format='json').status_code == 403

    def test_le_statut_ne_se_pose_PAS_par_PATCH(self, contexte):
        """Sans cette garde, quelqu'un passerait sa propre qualification en « vérifiée »."""
        titre, benevole, _ = contexte
        _client(benevole).patch(f"{URL}{titre.id}/", {"statut": "VERIFIEE"}, format='json')
        titre.refresh_from_db()
        assert titre.statut == StatutQualification.DECLAREE

    def test_le_refus_exige_un_motif(self, contexte):
        """Sans motif, le membre voit « refusé » sans savoir quoi corriger, et redéposera la
        même pièce."""
        titre, _, chef = contexte
        assert _client(chef).post(f"{URL}{titre.id}/refuser/", {},
                                  format='json').status_code == 400

        reponse = _client(chef).post(f"{URL}{titre.id}/refuser/",
                                     {"motif": "Attestation illisible"}, format='json')
        assert reponse.status_code == 200
        titre.refresh_from_db()
        assert titre.statut == StatutQualification.REFUSEE
        assert titre.motif_refus == "Attestation illisible"

    def test_le_membre_est_prevenu_du_refus(self, contexte):
        """Un refus découvert par hasard en rouvrant sa page ne serait pas corrigé."""
        titre, benevole, chef = contexte
        mail.outbox.clear()
        _client(chef).post(f"{URL}{titre.id}/refuser/", {"motif": "Illisible"}, format='json')

        pour_lui = [m for m in mail.outbox if benevole.email in m.to]
        assert pour_lui and "Illisible" in pour_lui[0].body

    def test_un_nouveau_depot_remet_le_titre_a_instruire(self, contexte):
        """Sinon le refus resterait affiché sur un justificatif corrigé, et le membre croirait
        avoir fait le nécessaire sans que personne ne le relise."""
        titre, benevole, chef = contexte
        _client(chef).post(f"{URL}{titre.id}/refuser/", {"motif": "Illisible"}, format='json')

        _client(benevole).patch(f"{URL}{titre.id}/", {"justificatif": piece("corrige.pdf")},
                                format='multipart')
        titre.refresh_from_db()
        assert titre.statut == StatutQualification.DECLAREE
        assert titre.motif_refus == ""
        assert titre.verifie_par is None


@pytest.mark.django_db
class TestNotificationEtCompteur:

    def test_l_encadrement_LE_PLUS_PROCHE_est_prevenu(self, create_user, asso, arbre, psc1):
        """Prévenir tout le monde jusqu'au national ferait de chaque dépôt de PSC1 une
        notification pour quatre échelons, et la notification cesserait d'être lue."""
        national, gironde, _ = arbre
        benevole = _membre(create_user, 'titu3', asso, gironde)
        chef_33 = _membre(create_user, 'chef33c', asso, gironde, encadrant=True,
                          type_compte='SECOURS')
        chef_nat = _membre(create_user, 'chefnatc', asso, national, encadrant=True,
                           type_compte='SECOURS')
        mail.outbox.clear()

        _client(benevole).post(URL, {"qualification": str(psc1.id), "justificatif": piece()},
                               format='multipart')

        destinataires = {adresse for m in mail.outbox for adresse in m.to}
        assert chef_33.email in destinataires
        assert chef_nat.email not in destinataires

    def test_sans_encadrement_le_bureau_est_prevenu(self, create_user, asso, arbre, psc1):
        """Sinon personne ne saurait qu'une pièce attend."""
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'titu4', asso, gironde)
        bureau = _membre(create_user, 'bureau4', asso, bureau=True, type_compte='SECOURS')
        mail.outbox.clear()

        _client(benevole).post(URL, {"qualification": str(psc1.id), "justificatif": piece()},
                               format='multipart')

        assert bureau.email in {a for m in mail.outbox for a in m.to}

    def test_le_compteur_sert_la_pastille_de_notification(self, create_user, asso, arbre,
                                                          psc1):
        """Sans compteur, l'encadrement devrait déplier l'arborescence entière pour découvrir
        qu'une pièce attend."""
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'titu5', asso, gironde)
        chef = _membre(create_user, 'chef5', asso, gironde, encadrant=True,
                       type_compte='SECOURS')
        _client(benevole).post(URL, {"qualification": str(psc1.id), "justificatif": piece()},
                               format='multipart')

        reponse = _client(chef).get(f"{URL}a-verifier/")
        assert reponse.status_code == 200
        assert reponse.data['total'] == 1
        assert str(benevole.id) in reponse.data['par_membre']

    def test_le_compteur_ignore_ses_propres_titres(self, create_user, asso, arbre, psc1):
        """On ne se vérifie pas soi-même : les compter ferait clignoter une pastille sur
        laquelle il n'y a rien à faire."""
        _, gironde, _ = arbre
        chef = _membre(create_user, 'chef6', asso, gironde, encadrant=True,
                       type_compte='SECOURS')
        _client(chef).post(URL, {"qualification": str(psc1.id), "justificatif": piece()},
                           format='multipart')

        assert _client(chef).get(f"{URL}a-verifier/").data['total'] == 0

    def test_un_titre_sans_piece_n_est_pas_compte(self, create_user, asso, arbre, psc1):
        """Il n'y a rien à consulter : le compter enverrait l'encadrement vers une page vide."""
        _, gironde, _ = arbre
        benevole = _membre(create_user, 'titu7', asso, gironde)
        chef = _membre(create_user, 'chef7', asso, gironde, encadrant=True,
                       type_compte='SECOURS')
        _client(benevole).post(URL, {"qualification": str(psc1.id)}, format='multipart')

        assert _client(chef).get(f"{URL}a-verifier/").data['total'] == 0
