package fr.assistacrise.mobile.domaine

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Relevé kilométrique (28/11/2026) : compteurs, distance estimée, état du départ. */
class ReleveKmTest {
    @Test
    fun lesCompteursFontLesKilometres() {
        assertEquals(52, ReleveKm.kmCompteurs("45 210", "45262"))
        assertNull(ReleveKm.kmCompteurs("45262", "45210"))
        assertNull(ReleveKm.kmCompteurs("", "45210"))
        assertNull(ReleveKm.kmCompteurs("1000", "9000"))
    }

    @Test
    fun laDistanceCumuleSansLesPositionsAberrantes() {
        val d = DistanceParcourue()
        val t0 = 1_700_000_000_000L
        d.ajouter(Releve(45.0, 4.0, t0, 10f))
        d.ajouter(Releve(45.01, 4.0, t0 + 60_000, 10f))           // ~1,1 km en 1 min : 67 km/h
        d.ajouter(Releve(46.0, 4.0, t0 + 120_000, 10f))           // ~110 km en 1 min : aberrant
        d.ajouter(Releve(45.02, 4.0, t0 + 180_000, 500f))         // trop flou : ignoré
        d.ajouter(Releve(45.02, 4.0, t0 + 240_000, 10f))
        // La position aberrante est sautée ; la suivante repart d'elle, et le saut retour est
        // lui aussi aberrant : seul le premier kilomètre compte.
        assertEquals(1, d.kilometres)
        val relu = DistanceParcourue.depuis(d.enTexte())
        assertEquals(d.metres, relu.metres)
        relu.ajouter(Releve(45.03, 4.0, t0 + 300_000, 10f))
        assertTrue(relu.metres > d.metres)
    }

    @Test
    fun rienDeMesureRienDePropose() {
        assertNull(DistanceParcourue().kilometres)
        assertNull(DistanceParcourue.depuis("illisible").kilometres)
    }

    @Test
    fun leRetourNEnvoieQueCeQuiEstSaisi() {
        assertEquals(mapOf("compteur_arrivee" to "45262", "peage" to "3,40"),
            Retour(compteurArrivee = "45 262", peage = "3,40").champs())
        assertEquals(mapOf("aller_retour" to false), Retour(allerRetour = false).champs())
    }

    @Test
    fun litLEtatDuServeur() {
        val json = Json { ignoreUnknownKeys = true }
        val etat = json.decodeFromString(EtatEngagement.serializer(), """
            {"en_cours": {"crise": null, "crise_nom": "Course des 10 km", "manifestation": "m1", "parti_le": "2026-11-28T08:00:00Z",
             "depart_de": "DOMICILE", "vehicule_personnel": "v1", "compteur_depart": "45210", "motif_propose": "Course des 10 km",
             "arrivee_proposee": "Floirac"},
             "crises": [], "equipes": [], "manifestations": [],
             "vehicules": [{"id": "v1", "genre": "VOITURE", "libelle": "Clio", "puissance_cv": 5, "designation": "Clio · 5 CV"}]}
        """.trimIndent())
        assertEquals("45210", etat.enCours?.compteurDepart)
        assertEquals("Floirac", etat.enCours?.arriveePropose)
        assertEquals(5, etat.vehicules.single().puissanceCv)
        assertTrue(!etat.vide)
    }

    @Test
    fun litMonReleveDuServeur() {
        val json = Json { ignoreUnknownKeys = true }
        val r = json.decodeFromString(MonReleve.serializer(), """
            {"du": "2026-10-29", "au": "2026-11-28", "total_heures": 7.5, "total_kilometres": 52.0,
             "lignes": [
               {"id": "l1", "crise_nom": "Course des 10 km", "parti_le": "2026-11-27T08:00:00+01:00", "rentre_le": "2026-11-27T12:00:00+01:00",
                "heures": 4.0, "kilometres": "52", "lieu_depart": "Domicile", "lieu_arrivee": "Floirac", "aller_retour": true,
                "validee": false, "remarque_chef": "", "activite": [],
                "frais": [{"id": "f1", "nature": "PEAGE", "nature_libelle": "Péage", "montant": "3.40", "justificatif": true, "justificatif_nom": "t.jpg"},
                          {"id": "f2", "nature": "AUTRE", "nature_libelle": "Autre justificatif", "montant": "0", "justificatif": true}]},
               {"id": "l2", "crise_nom": "Crue", "parti_le": "2026-11-28T08:00:00+01:00", "rentre_le": null, "validee": false},
               {"id": "l3", "crise_nom": "Crue", "parti_le": "2026-11-20T08:00:00+01:00", "rentre_le": "2026-11-20T10:00:00+01:00",
                "validee": false, "remarque_chef": "Retour à 9 h, pas 10 h"}],
             "frais": [{"institution": "a1", "nom": "Radio-club", "annee": 2026, "kilometres": 52.0, "montant": "33.07", "abandon": null}],
             "activite": [], "crises": []}
        """.trimIndent())
        val (l1, l2, l3) = r.lignes
        assertEquals("Domicile → Floirac (A/R)", l1.trajet)
        assertEquals(3.4, l1.totalFrais, 1e-9)                      // l'autre justificatif ne compte pas
        assertTrue(l1.frais[1].sansMontant && l1.accepteJustificatif)
        assertEquals(EtatLigne.EN_ATTENTE, l1.etat)
        assertEquals(EtatLigne.EN_COURS, l2.etat)
        assertTrue(!l2.accepteJustificatif)                          // pas encore rentré
        assertEquals(EtatLigne.A_REVOIR, l3.etat)
        assertEquals("a1", r.frais.single().institution)
    }

    @Test
    fun uneSortieOublieePortePourQuiEtLesHeures() {
        val b = BrouillonSortie(cible = "c:k1", equipe = "e1", partiLe = "2026-11-27T08:00:00+01:00", rentreLe = "2026-11-27T12:00:00+01:00",
            compteurDepart = "45 210", compteurArrivee = "45262", kilometres = "999")
        val c = b.champs()
        assertEquals("k1", c["crise"]); assertEquals("e1", c["equipe"]); assertEquals("52", c["kilometres"])
        assertEquals("45210", c["compteur_depart"]); assertEquals("AUCUN", c["vehicule"])
        assertEquals("Indiquez le départ et le retour.", b.copy(rentreLe = "").manque())
        assertEquals("Choisissez la crise ou la manifestation.", b.copy(cible = "").manque())
        assertEquals("m1", BrouillonSortie(cible = "m:m1", partiLe = "a", rentreLe = "b").champs()["manifestation"])
    }

    @Test
    fun uneCorrectionNEnvoieQueCeQuiAChange() {
        val ligne = LigneReleve(id = "l1", crise = "k1", partiLe = "2026-11-27T08:00:00+01:00", rentreLe = "2026-11-27T12:00:00+01:00",
            departDe = "DOMICILE", retourA = "DOMICILE", kilometres = "40")
        val origine = BrouillonSortie.depuis(ligne)
        val c = origine.copy(kilometres = "52", motif = "Balisage").champs(origine)
        // Seul le trajet change : ni les heures ni les lieux ne partent, et pas d'activité.
        assertTrue("parti_le" !in c && "rentre_le" !in c && "depart_de" !in c && "retour_a" !in c && "crise" !in c)
        assertEquals("52", c["kilometres"]); assertEquals("Balisage", c["motif"])
        assertEquals("2026-11-27T13:00:00+01:00", origine.copy(rentreLe = "2026-11-27T13:00:00+01:00").champs(origine)["rentre_le"])
        assertTrue(ligne.retirable.not() && ligne.corrigeable)
    }
}
