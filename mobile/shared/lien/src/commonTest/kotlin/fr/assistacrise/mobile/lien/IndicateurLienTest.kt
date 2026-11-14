package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.domaine.EtatLien
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class IndicateurLienTest {
    @Test fun sansReseauIlNYARien() {
        assertEquals(EtatLien.AUCUN, IndicateurLien().etat.value)
    }

    @Test fun unEchecIsoleNeFaitPasPasserHorsLigne() {
        // Constaté sur un vrai téléphone : une requête perdue au réveil de l'application
        // affichait « hors ligne » pendant une minute, sur un lien qui marchait.
        val lien = IndicateurLien()
        lien.reseau(true)
        lien.echange(false)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
        assertTrue(lien.enDoute)                      // … mais il faut revérifier vite
        lien.echange(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
        assertFalse(lien.enDoute)
    }

    @Test fun deuxEchecsDeSuiteLEmportentSurLAvisDuSysteme() {
        // Wi-Fi sans Internet, portail captif, central en panne.
        val lien = IndicateurLien()
        lien.reseau(true)
        lien.echange(false); lien.echange(false)
        assertEquals(EtatLien.AUCUN, lien.etat.value)
        assertFalse(lien.enDoute)                     // on sait : inutile de s'acharner
        lien.echange(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
    }

    @Test fun lAbsenceDeReseauEstUneCertitudeEtSonRetourRemetLesCompteursAZero() {
        val lien = IndicateurLien()
        lien.reseau(true); lien.echange(true)
        lien.reseau(false)                            // mode avion
        assertEquals(EtatLien.AUCUN, lien.etat.value)
        lien.echange(false); lien.echange(false)
        lien.reseau(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
    }

    @Test fun unServeurQuiRepondLEmporteSurLAvisDuSysteme() {
        // Wi-Fi d'un satellite coupé d'Internet : le système dit « pas de connexion ».
        val lien = IndicateurLien()
        lien.reseau(false)
        lien.echange(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
        lien.echange(false)                           // un échec isolé n'y change rien
        assertEquals(EtatLien.INTERNET, lien.etat.value)
        lien.reseau(false)                            // le réseau change : ce qu'on savait ne vaut plus
        assertEquals(EtatLien.AUCUN, lien.etat.value)
    }

    @Test fun laRadioNePrendLaMainQueSansInternet() {
        val lien = IndicateurLien()
        lien.radio(true)
        assertEquals(EtatLien.MESH, lien.etat.value)
        lien.reseau(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
        lien.echange(false); lien.echange(false)
        assertEquals(EtatLien.MESH, lien.etat.value)
    }
}
