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
}
