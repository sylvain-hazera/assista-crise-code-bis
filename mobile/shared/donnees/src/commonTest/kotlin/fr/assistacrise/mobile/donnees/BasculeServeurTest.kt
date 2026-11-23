package fr.assistacrise.mobile.donnees

import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BasculeServeurTest {
    private val central = "https://www.assista-crise.fr"

    @Test fun uneAdresseLocaleSeulement() {
        assertEquals("http://192.168.1.20/", Serveur.adresseLocaleValide("192.168.1.20"))
        assertEquals("http://10.0.0.5:8080/", Serveur.adresseLocaleValide("http://10.0.0.5:8080/pilotage"))
        assertEquals("http://assista-crise.local/", Serveur.adresseLocaleValide("Assista-Crise.local"))
        assertNull(Serveur.adresseLocaleValide("8.8.8.8"))
        assertNull(Serveur.adresseLocaleValide("exemple.com"))
        assertNull(Serveur.adresseLocaleValide("300.1.1.1"))
    }

    @Test fun troisEchecsPuisLeSatelliteAnnonceEnMdnsEtRetourAuCentral() = runTest {
        val magasin = MagasinEnMemoire()
        val serveur = Serveur(magasin, central)
        val session = Session(magasin)
        var centralRepond = false
        val bascule = BasculeServeur(serveur, session,
            sonde = { url -> if (url.startsWith("http://192.168.1.20")) true else centralRepond },
            decouvrir = { listOf("http://192.168.1.20/" to "Sat Porge") })
        assertFalse(bascule.noter(false)); assertFalse(bascule.noter(false))
        assertTrue(bascule.noter(false))
        assertEquals("Sat Porge", bascule.chercherEtBasculer())
        assertEquals(BasculeServeur.Etat.SATELLITE, bascule.etat.value)
        assertEquals("http://192.168.1.20/api", serveur.urlApi())
        assertFalse(bascule.verifierRetour())
        centralRepond = true
        assertTrue(bascule.verifierRetour())
        assertEquals("$central/api", serveur.urlApi())
    }

    @Test fun rienTrouveAlorsLAdresseEstDemandee() = runTest {
        val magasin = MagasinEnMemoire()
        val serveur = Serveur(magasin, central)
        val bascule = BasculeServeur(serveur, Session(magasin), sonde = { it == "http://192.168.1.30/" }, decouvrir = { emptyList() })
        assertNull(bascule.chercherEtBasculer())
        assertEquals(BasculeServeur.Etat.ADRESSE_DEMANDEE, bascule.etat.value)
        assertNotNull(bascule.essayerAdresse("8.8.8.8"))
        assertNotNull(bascule.essayerAdresse("192.168.1.99"))
        assertNull(bascule.essayerAdresse("192.168.1.30"))
        assertEquals(BasculeServeur.Etat.SATELLITE, bascule.etat.value)
        assertEquals("192.168.1.30", serveur.adresseSaisie())
    }

    @Test fun lesAdressesDonneesParLeCentralServentAussi() = runTest {
        val magasin = MagasinEnMemoire()
        val serveur = Serveur(magasin, central)
        serveur.retenirConnus(listOf(SatelliteConnu("s1", "Sat B", urls = listOf("http://assista-crise.local/", "http://192.168.1.40/"))))
        val bascule = BasculeServeur(serveur, Session(magasin), sonde = { it == "http://192.168.1.40/" }, decouvrir = { emptyList() })
        assertEquals("Sat B", bascule.chercherEtBasculer())
    }
}
