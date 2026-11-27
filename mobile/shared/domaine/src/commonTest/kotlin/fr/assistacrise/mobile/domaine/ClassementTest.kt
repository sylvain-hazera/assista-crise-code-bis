package fr.assistacrise.mobile.domaine

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Classement « quoi + pour qui » (27/11/2026) : miroir de backend/core/classement.py. */
class ClassementTest {
    @Test
    fun unSeulCheminPourLesAnimauxAEvacuer() {
        assertEquals(listOf("PERSONNES", "ANIMAUX", "BIENS"), Classement.admis("EVAC", offre = false))
        // Pas de demande de soins pour une personne : c'est le 15.
        assertEquals(listOf("ANIMAUX"), Classement.admis("SOIN", offre = false))
        assertEquals(listOf("PERSONNES", "ANIMAUX"), Classement.admis("SOIN", offre = true))
        assertTrue(Classement.admis("MAT", offre = false).isEmpty())
    }

    @Test
    fun leBesoinReleveSEcritCommeLeLitLeServeur() {
        assertEquals("EVAC·A·EQ 45.50000,4.60000 3 chevaux dans un pré inondé,",
            Classement.besoin("EVAC", "ANIMAUX", "EQUIDES", 45.5, 4.6, "3 chevaux dans un pré inondé, accès par le nord"))
        assertEquals("NETT·B -0.50000,-73.12346", Classement.besoin("NETT", "BIENS", null, -0.5, -73.123456))
        // Un pour qui hors famille ne part pas ; la catégorie seulement pour des animaux.
        assertEquals("MAT", Classement.besoin("MAT", "PERSONNES", "EQUIDES", null, null))
        assertEquals("NOUR·P", Classement.besoin("NOUR", "PERSONNES", "EQUIDES", null, null))
    }

    @Test
    fun lesPrecisionsDemandentPourQuiPuisLesAnimaux() {
        val champs = Precisions.pour(GenreDepot.DEMANDE, "Hébergement", "ABRI")
        assertEquals("beneficiaire", champs.first().cle)
        val pourDesPersonnes = Precisions.visibles(champs, mapOf("beneficiaire" to "PERSONNES")).map { it.cle }
        assertTrue("type_logement" in pourDesPersonnes)
        assertFalse("categorie_animaux" in pourDesPersonnes)
        val pourDesAnimaux = Precisions.visibles(champs, mapOf("beneficiaire" to "ANIMAUX")).map { it.cle }
        assertTrue("categorie_animaux" in pourDesAnimaux && "nombre_animaux" in pourDesAnimaux)
        assertFalse("type_logement" in pourDesAnimaux)
    }

    @Test
    fun lesSoinsNeConcernentQueDesAnimaux() {
        val champs = Precisions.pour(GenreDepot.DEMANDE, "Soins", "SOIN").map { it.cle }
        assertEquals(listOf("categorie_animaux", "nombre_animaux"), champs)
    }

    @Test
    fun leTransportDitDejaPourQui() {
        val champs = Precisions.pour(GenreDepot.OFFRE, "Transport", "EVAC")
        assertFalse(champs.any { it.cle == "beneficiaire" })
        val animaux = Precisions.visibles(champs, mapOf("transport_type" to "ANIMAUX")).map { it.cle }
        assertTrue("categories_animaux" in animaux)
    }
}
