"""Suivi associatif d'un membre : statut, adhésion, aptitude, qualifications.

Socle de la section RH d'une association agréée de sécurité civile (voir § 5.12 bis). Ce que
ces tests tiennent :

1. **Un ancien membre ne garde pas ses accès.** `statut` (où en est la personne) et `actif`
   (ce rattachement ouvre-t-il des droits) sont deux questions distinctes, et les laisser
   divergar produirait un sorti qui accède encore — invisible, puisque aucun écran ne montre
   les deux ensemble.
2. **Une qualification périmée est détectable avant l'échéance.** C'est la raison d'être du
   modèle : pour une AASC, un PSE1 expiré vaut un PSE1 absent, et on le découvre le jour de la
   mobilisation si personne ne l'a suivi.
3. **Aucune donnée de santé.** Décision explicite du responsable de traitement le 28/10/2026 :
   la date de fin de validité du certificat médical, et RIEN d'autre — ni « apte / inapte »,
   ni restriction, ni le document. Un test le verrouille au niveau du modèle, pour qu'un ajout
   ultérieur se heurte à un échec plutôt qu'à la bonne volonté de son auteur.
"""
import datetime

import pytest
from django.utils import timezone

from core.models import (
    ContactInstitution, Institution, InstitutionType, Qualification, QualificationMembre, User,
)


@pytest.fixture
def aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    institution, _ = Institution.objects.get_or_create(
        nom="AASC Suivi Associatif", defaults={"type": itype, "actif": True})
    return institution


@pytest.fixture
def membre(create_user, aasc):
    user = create_user(username="membre-rh@test.fr", email="membre-rh@test.fr",
                       type="SECOURS", last_name="DUPONT")
    return ContactInstitution.objects.create(
        institution=aasc, utilisateur=user, fonction="Équipier", actif=True)


class TestStatutDuMembre:
    def test_un_nouveau_membre_est_actif(self, membre):
        assert membre.statut == ContactInstitution.StatutMembre.ACTIF
        assert membre.actif is True

    def test_un_membre_en_conge_garde_ses_acces(self, membre):
        """Un congé n'est pas un départ : la personne garde son ancienneté et ses accès, elle
        ne doit simplement pas apparaître dans les disponibilités d'une mobilisation."""
        membre.statut = ContactInstitution.StatutMembre.CONGE
        membre.save()

        membre.refresh_from_db()
        assert membre.actif is True

    def test_un_membre_sorti_perd_ses_acces(self, membre):
        """LE test. Sans cette règle, un ancien membre reste rattaché et accède encore à
        l'application, et aucun écran ne le montre : le bureau lit `statut`, le contrôle
        d'accès lit `actif`."""
        membre.statut = ContactInstitution.StatutMembre.SORTI
        membre.save()

        membre.refresh_from_db()
        assert membre.actif is False

    def test_la_sortie_sapplique_meme_avec_update_fields(self, membre):
        """Le piège : `save(update_fields=['statut'])` n'écrirait pas `actif` si la règle ne
        complétait pas la liste des champs. Un formulaire qui n'enregistre que le champ modifié
        laisserait donc l'accès ouvert."""
        membre.statut = ContactInstitution.StatutMembre.SORTI
        membre.save(update_fields=["statut"])

        membre.refresh_from_db()
        assert membre.actif is False


class TestAdhesion:
    def test_les_dates_dadhesion_sont_facultatives(self, membre):
        """Une association reprend un historique incomplet : exiger la date ferait inventer."""
        assert membre.date_adhesion is None
        assert membre.adhesion_valide_jusquau is None

    def test_adhesion_et_renouvellement(self, membre):
        membre.date_adhesion = datetime.date(2021, 9, 1)
        membre.adhesion_valide_jusquau = datetime.date(2027, 8, 31)
        membre.save()

        membre.refresh_from_db()
        assert membre.date_adhesion.year == 2021
        assert membre.adhesion_valide_jusquau.year == 2027

    def test_aucun_montant_nest_stocke(self, membre):
        """L'association ne perçoit pas de cotisation (28/10/2026). Un champ montant
        ouvrirait une gestion financière, qui est un autre métier que la préparation de
        crise — si le besoin apparaît, il se repose, il ne se glisse pas."""
        champs = {f.name for f in ContactInstitution._meta.fields}
        for interdit in ("montant", "cotisation", "montant_cotisation", "paye", "reglement"):
            assert interdit not in champs, interdit


class TestAptitudeMedicale:
    def test_seule_la_date_est_conservee(self, membre):
        membre.aptitude_valide_jusquau = datetime.date(2027, 6, 30)
        membre.save()

        membre.refresh_from_db()
        assert membre.aptitude_valide_jusquau == datetime.date(2027, 6, 30)

    def test_aucun_champ_de_sante_ne_sest_glisse_dans_le_modele(self, membre):
        """Verrou délibéré. La date de fin de validité d'un certificat est un fait
        administratif sur un document ; « apte / inapte », une restriction ou le certificat
        lui-même révèlent un état de santé (RGPD art. 9), que le projet s'interdit. Ce test
        existe pour qu'un ajout ultérieur échoue au lieu de passer."""
        champs = {f.name for f in ContactInstitution._meta.fields}
        for interdit in ("apte", "aptitude", "inapte", "restriction", "restrictions",
                         "certificat", "certificat_medical", "document_medical",
                         "contre_indication"):
            assert interdit not in champs, interdit


class TestQualifications:
    @pytest.fixture
    def pse1(self, db):
        return Qualification.objects.create(
            nom="PSE1 — Premiers secours en équipe niveau 1", validite_mois=12)

    @pytest.fixture
    def permis(self, db):
        """Sans péremption : un permis de conduire ne s'épuise pas."""
        return Qualification.objects.create(nom="Permis B", validite_mois=None)

    def _detenir(self, membre, qualification, **kwargs):
        return QualificationMembre.objects.create(
            utilisateur=membre.utilisateur, qualification=qualification, **kwargs)

    def test_une_qualification_valide_nest_pas_expiree(self, membre, pse1):
        titre = self._detenir(
            membre, pse1, date_expiration=timezone.localdate() + datetime.timedelta(days=60))

        assert titre.expiree is False
        assert titre.jours_avant_expiration() == 60

    def test_une_qualification_perimee_est_signalee(self, membre, pse1):
        """Pour une AASC, c'est le cœur du suivi : un PSE1 expiré vaut un PSE1 absent."""
        titre = self._detenir(
            membre, pse1, date_expiration=timezone.localdate() - datetime.timedelta(days=1))

        assert titre.expiree is True
        assert titre.jours_avant_expiration() == -1

    def test_une_qualification_qui_expire_aujourdhui_est_encore_valide(self, membre, pse1):
        """La borne compte : on ne retire pas quelqu'un d'une mobilisation le dernier jour de
        validité de son titre."""
        titre = self._detenir(membre, pse1, date_expiration=timezone.localdate())

        assert titre.expiree is False
        assert titre.jours_avant_expiration() == 0

    def test_un_titre_sans_peremption_nexpire_jamais(self, membre, permis):
        titre = self._detenir(membre, permis)

        assert titre.expiree is False
        assert titre.jours_avant_expiration() is None

    def test_une_personne_ne_detient_quune_fois_le_meme_titre(self, membre, pse1):
        """Deux lignes pour le même PSC1 divergeraient, et on ne saurait plus laquelle croit."""
        from django.db import IntegrityError

        self._detenir(membre, pse1, date_expiration=timezone.localdate())
        with pytest.raises(IntegrityError):
            self._detenir(membre, pse1, date_expiration=timezone.localdate())

    def test_le_titre_appartient_a_la_personne_pas_a_lassociation(self, membre, pse1, aasc):
        """Quelqu'un membre de deux AASC détient un seul PSE1 : le rattacher au rattachement
        associatif ferait saisir la même attestation deux fois, et les deux copies
        divergeraient."""
        titre = self._detenir(membre, pse1)

        assert titre.utilisateur_id == membre.utilisateur_id
        assert not hasattr(titre, "institution")

    def test_un_titre_attribue_survit_au_retrait_du_catalogue(self, membre, pse1):
        """`PROTECT` sur la qualification : une entrée retirée se masque (`actif=False`), elle
        ne se supprime pas — un titre déjà attribué doit rester lisible."""
        from django.db.models import ProtectedError

        self._detenir(membre, pse1)
        with pytest.raises(ProtectedError):
            pse1.delete()
