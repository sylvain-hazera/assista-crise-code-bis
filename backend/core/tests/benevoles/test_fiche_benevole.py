"""Fiche d'un bénévole : lecture du fichier d'adhésion, géocodage, département d'affectation.

Deux décisions verrouillées ici :

1. **Le département vient du GÉOCODAGE**, pas du code postal. Un code postal n'est pas un code
   commune — la Corse partage `20xxx` entre 2A et 2B, l'outre-mer demande trois chiffres, et un
   tableur mange le zéro initial. `commune_code` tranche exactement. La dérivation par code
   postal ne reste qu'un **repli signalé**, jamais silencieux.
2. **`diplome_premier_secours` est déclaratif** et reste distinct de `QualificationMembre`, qui
   porte les qualifications vérifiées avec leurs dates et leur justificatif.

Les valeurs testées sont celles du vrai export d'adhésion des Casques Jaunes : listes Python en
texte (`['2 - Régulière (env. 10 jours par an)']`), dates en JJ-MM-AAAA, « NO » pour un
booléen, et des virgules remplacées par des barres verticales.
"""
from unittest.mock import patch

import pytest

from core.imports import (
    _booleen, _date, _disponibilite, _liste_echappee, _situation,
    importer_benevoles_association,
)
from core.models import (
    EchelonEquipe, FicheBenevole, Institution, InstitutionType, Team, User,
)

MAPPING = {
    "prenom": "PRENOM", "nom": "NOM", "email": "EMAIL", "telephone": "SMS",
    "adresse": "ADRESSE", "code_postal": "CODE_POSTAL", "ville": "VILLE",
    "metier": "METIERS_FORMATIONS", "situation": "SITUATION",
    "disponibilite": "DISPONIBILITE", "date_naissance": "DATE_NAISSANCE",
    "diplome_premier_secours": "DIPLOME_PREMIER_SECOURS", "message": "MESSAGE",
    "date_adhesion": "ADDED_TIME",
}


def ligne_reelle(email="vduparcl@essai.invalide"):
    """Une ligne telle que le fichier des Casques Jaunes la contient."""
    return {
        "EMAIL": email, "SMS": "33633286230",
        "NOM": "du Parc Locmaria", "PRENOM": "Virginie",
        "ADRESSE": "131 Route du Cap Ferret", "VILLE": "LE CANON - LEGE CAP FERRET",
        "CODE_POSTAL": "33950", "METIERS_FORMATIONS": "Assureur",
        "DIPLOME_PREMIER_SECOURS": "NO",
        "MESSAGE": "Je ne sais pas trop en fait, je veux juste aider.",
        "DISPONIBILITE": "['1 - Occasionnelle (- de 5 jours par an)']",
        "DATE_NAISSANCE": "18-01-1968",
        "SITUATION": "['Salarié(e)']",
        "ADDED_TIME": "06-10-2026",
    }


@pytest.fixture
def asso(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_FICHE',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom="Association Fiche", type=itype)


@pytest.fixture
def gironde(asso):
    return Team.objects.create(name="Gironde", institution=asso,
                               echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="33")


@pytest.fixture
def requete(rf):
    from django.contrib.auth.models import AnonymousUser

    r = rf.post('/api/x/')
    r.user = AnonymousUser()
    return r


class TestLectureDesValeursDExport:

    def test_une_liste_python_en_texte_est_denouee(self):
        """Les formulaires rendent `['Salarié(e)']`, crochets et apostrophes compris. Les
        stocker tels quels mettrait ce littéral en base."""
        assert _liste_echappee("['Salarié(e)']") == "Salarié(e)"
        assert _liste_echappee("Salarié(e)") == "Salarié(e)"
        assert _liste_echappee("") == ""

    @pytest.mark.parametrize("brut,attendu", [
        ("['Salarié(e)']", "SALARIE"),
        ("['Retraité(e)']", "RETRAITE"),
        ("['Chef(fe) d'entreprise (artisan| profession libérale| etc.)']", "INDEPENDANT"),
        ("", ""),
    ])
    def test_la_situation_est_reconnue_malgre_la_casse_et_les_accents(self, brut, attendu):
        assert _situation(brut) == attendu

    def test_une_situation_inconnue_vaut_AUTRE_et_non_vide(self):
        """« On ne sait pas classer » et « la personne n'a pas répondu » ne sont pas la même
        information : les confondre ferait disparaître une réponse donnée."""
        assert _situation("['Intermittent du spectacle']") == "AUTRE"
        assert _situation("") == ""

    @pytest.mark.parametrize("brut,attendu", [
        ("['1 - Occasionnelle (- de 5 jours par an)']", "OCCASIONNELLE"),
        ("['2 - Régulière (env. 10 jours par an)']", "REGULIERE"),
        ("['3 - Fréquente (+ de 10 jours par an)']", "FREQUENTE"),
    ])
    def test_la_disponibilite_est_lue_sur_le_CHIFFRE(self, brut, attendu):
        """Le chiffre de tête est l'information stable ; le libellé change au gré des
        reformulations du formulaire."""
        assert _disponibilite(brut) == attendu

    def test_la_disponibilite_retombe_sur_le_texte_sans_chiffre(self):
        assert _disponibilite("['Régulière']") == "REGULIERE"

    @pytest.mark.parametrize("brut,attendu", [
        ("18-01-1968", (1968, 1, 18)), ("18/01/1968", (1968, 1, 18)),
        ("1968-01-18", (1968, 1, 18)),
    ])
    def test_les_formats_de_date_courants_sont_acceptes(self, brut, attendu):
        d = _date(brut)
        assert (d.year, d.month, d.day) == attendu

    def test_une_date_illisible_ne_fait_pas_echouer_la_ligne(self):
        """Le reste de la fiche est exploitable sans elle."""
        assert _date("pas une date") is None

    def test_NO_vaut_faux_et_YES_vaut_vrai(self):
        """Pour un diplôme déclaré, l'absence de réponse claire vaut non — l'inverse ferait
        croire à une compétence que personne n'a affirmée."""
        assert _booleen("NO") is False
        assert _booleen("") is False
        assert _booleen("peut-être") is False
        assert _booleen("YES") is True
        assert _booleen("oui") is True


@pytest.mark.django_db
class TestFicheCreeeParLImport:

    def test_toutes_les_colonnes_du_fichier_arrivent_en_base(self, requete, asso, gironde):
        """Le reproche d'origine : 4 colonnes sur 14 arrivaient, les 10 autres étaient
        silencieusement perdues."""
        with patch('core.imports._geocoder_adresse',
                   return_value=(44.71, -1.15, "33236", "Lège-Cap-Ferret")):
            importer_benevoles_association(requete, asso, [ligne_reelle()], MAPPING)

        fiche = FicheBenevole.objects.get()
        assert fiche.adresse == "131 Route du Cap Ferret"
        assert fiche.code_postal == "33950"
        assert fiche.metier == "Assureur"
        assert fiche.situation == "SALARIE"
        assert fiche.disponibilite == "OCCASIONNELLE"
        assert fiche.date_naissance.year == 1968
        assert fiche.date_adhesion.year == 2026
        assert "je veux juste aider" in fiche.message
        assert fiche.diplome_premier_secours is False
        # Et l'utilisateur garde ce qui lui revient.
        u = User.objects.get(username=fiche.utilisateur.username)
        assert u.first_name == "Virginie" and u.last_name == "du Parc Locmaria"

    def test_le_geocodage_pose_le_secteur_complet(self, requete, asso, gironde):
        """Aligné sur Offer : commune, EPCI, département, région posés une fois, pas rejoints
        à chaque lecture."""
        with patch('core.imports._geocoder_adresse',
                   return_value=(44.71, -1.15, "33236", "Lège-Cap-Ferret")), \
             patch('core.geo_lookup.commune_secteur_codes',
                   return_value={"epci_code": "243301124", "departement_code": "33",
                                 "region_code": "75"}):
            importer_benevoles_association(requete, asso, [ligne_reelle()], MAPPING)

        fiche = FicheBenevole.objects.get()
        assert fiche.commune_code == "33236"
        assert fiche.departement_code == "33"
        assert fiche.region_code == "75"
        assert fiche.location is not None

    def test_le_departement_geocode_decide_de_l_equipe(self, requete, asso, gironde):
        with patch('core.imports._geocoder_adresse',
                   return_value=(44.71, -1.15, "33236", "Lège-Cap-Ferret")), \
             patch('core.geo_lookup.commune_secteur_codes',
                   return_value={"epci_code": None, "departement_code": "33",
                                 "region_code": "75"}):
            importer_benevoles_association(requete, asso, [ligne_reelle()], MAPPING)

        assert gironde.members.count() == 1

    def test_sans_geocodage_le_code_postal_sert_de_repli_SIGNALE(self, requete, asso, gironde):
        """Le repli rattache quand même, mais il est dit : un département déduit d'un code
        postal est moins sûr qu'un département géocodé, et celui qui relit l'import doit le
        savoir."""
        with patch('core.imports._geocoder_adresse',
                   return_value=(None, None, None, None)):
            bilan = importer_benevoles_association(requete, asso, [ligne_reelle()], MAPPING)

        assert gironde.members.count() == 1
        messages = " ".join(e["message"] for e in bilan["erreurs"])
        assert "code postal" in messages

    def test_la_corse_reste_refusee_meme_en_repli(self, requete, asso, gironde):
        """2A/2B indiscernables : on ne devine pas, on signale."""
        ligne = ligne_reelle()
        ligne["CODE_POSTAL"] = "20000"
        ligne["ADRESSE"] = ""
        with patch('core.imports._geocoder_adresse',
                   return_value=(None, None, None, None)):
            bilan = importer_benevoles_association(requete, asso, [ligne], MAPPING)

        assert bilan["sans_equipe"] == 1
        assert any("Corse" in e["message"] for e in bilan["erreurs"])

    def test_reimporter_n_efface_pas_une_fiche_deja_completee(self, requete, asso, gironde):
        """Une valeur absente du fichier ne doit pas écraser ce que la personne a saisi
        elle-même depuis sa page de profil."""
        with patch('core.imports._geocoder_adresse',
                   return_value=(44.71, -1.15, "33236", "Lège")):
            importer_benevoles_association(requete, asso, [ligne_reelle()], MAPPING)
            fiche = FicheBenevole.objects.get()
            fiche.metier = "Assureur, formatrice PSC1"
            fiche.save(update_fields=['metier'])

            ligne_sans_metier = ligne_reelle()
            ligne_sans_metier["METIERS_FORMATIONS"] = ""
            importer_benevoles_association(requete, asso, [ligne_sans_metier], MAPPING)

        fiche.refresh_from_db()
        assert fiche.metier == "Assureur, formatrice PSC1"

    def test_le_diplome_declare_ne_cree_PAS_de_qualification_verifiee(self, requete, asso,
                                                                       gironde):
        """Une case cochée à l'inscription n'est pas un diplôme contrôlé par le bureau."""
        from core.models import QualificationMembre

        ligne = ligne_reelle()
        ligne["DIPLOME_PREMIER_SECOURS"] = "YES"
        with patch('core.imports._geocoder_adresse',
                   return_value=(44.71, -1.15, "33236", "Lège")):
            importer_benevoles_association(requete, asso, [ligne], MAPPING)

        assert FicheBenevole.objects.get().diplome_premier_secours is True
        assert not QualificationMembre.objects.exists()
