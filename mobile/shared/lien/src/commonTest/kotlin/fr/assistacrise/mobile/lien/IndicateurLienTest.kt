package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.domaine.EtatLien
import kotlin.test.Test
import kotlin.test.assertEquals

class IndicateurLienTest {
    @Test fun sansReseauIlNYARien() {
        assertEquals(EtatLien.AUCUN, IndicateurLien().etat.value)
    }

    @Test fun unReseauPresentVautInternetJusquAPreuveDuContraire() {
        val lien = IndicateurLien()
        lien.reseau(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
        lien.echange(false)   // Wi-Fi sans Internet, portail captif, central en panne
        assertEquals(EtatLien.AUCUN, lien.etat.value)
        lien.echange(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
    }

    @Test fun leRetourDuReseauEffaceLEchecPrecedent() {
        val lien = IndicateurLien()
        lien.reseau(true); lien.echange(false); lien.reseau(false)
        lien.reseau(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
    }

    @Test fun laRadioNePrendLaMainQueSansInternet() {
        val lien = IndicateurLien()
        lien.radio(true)
        assertEquals(EtatLien.MESH, lien.etat.value)
        lien.reseau(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
    }

    @Test fun unServeurQuiRepondLEmporteSurLAvisDuSysteme() {
        // Wi-Fi d'un satellite coupé d'Internet : le système dit « pas de connexion ».
        val lien = IndicateurLien()
        lien.reseau(false)
        lien.echange(true)
        assertEquals(EtatLien.INTERNET, lien.etat.value)
        // Le réseau change : la réussite d'avant ne prouve plus rien.
        lien.reseau(false)
        assertEquals(EtatLien.AUCUN, lien.etat.value)
    }
}
