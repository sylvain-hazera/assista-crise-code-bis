package fr.assistacrise.mobile.lien

import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.Meshtastic
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull

/**
 * Les vecteurs viennent des bibliothèques de référence (`meshcore` 2.3.15, `meshtastic`
 * 2.7.11), par l'intermédiaire des tests du relais navigateur : ils ne sont pas écrits à
 * la main, et c'est tout leur intérêt.
 */
class MeshCoreTest {
    @Test fun appStartEstOctetPourOctetCeluiDeLaBibliotheque() {
        assertEquals("3c0d0001032020202020206d63636c69", MeshCore.encadrer(MeshCore.appStart("mccli")).enHex())
    }

    @Test fun requeteAppareilEtReglageDeLHeure() {
        assertEquals("3c02001603", MeshCore.encadrer(MeshCore.requeteAppareil()).enHex())
        assertEquals("3c05000660c51669", MeshCore.encadrer(MeshCore.reglerHeure(1763100000)).enHex())
    }

    @Test fun unMessageEnvoyePuisRelu() {
        val trame = MeshCore.envoyerMessage("a1b2c3d4e5f60708", "Reçu", 1763100000)
        assertEquals("02000060c51669a1b2c3d4e5f6" + "Reçu".encodeToByteArray().enHex(), trame.enHex())
        // Réponse v3 : type, SNR, 2 réservés, préfixe (6), chemin, type de texte, heure, texte.
        val recu = ("10" + "0a0000" + "a1b2c3d4e5f6" + "ff" + "00" + "60c51669").depuisHex() + "Bien reçu".encodeToByteArray()
        val message = MeshCore.lireMessageRecu(recu)!!
        assertEquals("a1b2c3d4e5f6", message.prefixeExpediteurHex)
        assertEquals("Bien reçu", message.texte)
        assertEquals(1763100000, message.horodatageS)
    }

    @Test fun laFicheDeLaRadioDonneSaCleEtSonNom() {
        val charge = ByteArray(58).also { it[0] = 5; for (i in 4 until 36) it[i] = i.toByte() } + "Heltec V3".encodeToByteArray()
        val identite = MeshCore.lireSelfInfo(charge)!!
        assertEquals("Heltec V3", identite.nom)
        assertEquals(64, identite.pubkeyHex.length)
        assertNull(MeshCore.lireSelfInfo(ByteArray(10)))
    }

    @Test fun unMessageTropLongEstRefuse() {
        assertFailsWith<IllegalArgumentException> { MeshCore.envoyerMessage("a1b2c3d4e5f6", "x".repeat(200), 0) }
    }
}

class MeshtasticTest {
    @Test fun laPoigneeDeMainEtLeBattement() {
        assertEquals("18f8acd19101", Meshtastic.veutConfig(0x12345678).enHex())
        assertEquals("3a0308ac02", Meshtastic.battement(300).enHex())
        assertEquals("3a00", Meshtastic.battement(0).enHex())          // sous-message vide, mais présent
        assertEquals(Meshtastic.PREMIER_NONCE_BATTEMENT, Meshtastic.nonceSuivant(0xffffffffL))
    }

    @Test fun unMessageDirectAvecAccuse() {
        assertEquals(
            "0a2215fecaad0b2214080112105265c3a7752c206f6e2061727269766535040302015001",
            Meshtastic.texte(0x0badcafe, "Reçu, on arrive", 0x01020304).enHex(),
        )
    }

    @Test fun laRadioDitSonNumero() {
        assertEquals(Meshtastic.Evenement.MonNoeud(0x1234abcd), Meshtastic.lire("08071a0608cdd7d29101".depuisHex()))
        assertEquals(Meshtastic.Evenement.ConfigTerminee(0x12345678), Meshtastic.lire("38f8acd19101".depuisHex()))
    }

    @Test fun unMessageDirectRecuYComprisAvecUnRssiNegatif() {
        val e = Meshtastic.lire(("123d0dfecaad0b15cdab34122215080112114172726976c3a97320737572207a6f6e6535efbeadde3d60c5" +
            "166945000050c04803609fffffffffffffffff01").depuisHex())
        assertEquals(Meshtastic.Evenement.Texte(0x0badcafe, 0x1234abcd, 0, "Arrivés sur zone", 0xdeadbeefL), e)
    }

    @Test fun unMessageDeCanalAdresseATous() {
        val e = Meshtastic.lire("12280dfecaad0b15ffffffff1801221508011211526f75746520636f7570c3a965204432303505000000".depuisHex())
        assertEquals(Meshtastic.Evenement.Texte(0x0badcafe, Meshtastic.DIFFUSION, 1, "Route coupée D20", 5), e)
    }

    @Test fun ceQuiNEstPasPourNousEstIgnore() {
        assertIs<Meshtastic.Evenement.Autre>(Meshtastic.lire("121d0dfecaad0b15cdab34122a0c9999999999999999999999993506000000".depuisHex()))
        assertIs<Meshtastic.Evenement.Autre>(Meshtastic.lire("12150dfecaad0b15cdab34122209080312050d00000000".depuisHex()))
        assertIs<Meshtastic.Evenement.Progression>(Meshtastic.lire("2a0432023803".depuisHex()))
        assertIs<Meshtastic.Evenement.Progression>(Meshtastic.lire("52130801120d1201011a0846725f454d434f4d1802".depuisHex()))
    }

    @Test fun uneTrameTronqueeEstRefusee() {
        assertFailsWith<IllegalArgumentException> { Meshtastic.lire("08071a0608cdd7".depuisHex()) }
    }

    @Test fun leDecoupageNeCoupeJamaisUnCaractere() {
        val morceaux = Meshtastic.decouper("é".repeat(150), maximum = 200)      // 300 octets
        assertEquals(listOf(100, 50), morceaux.map { it.length })
        assertEquals(listOf("court"), Meshtastic.decouper("court"))
        assertEquals(listOf("🚑", "🚑"), Meshtastic.decouper("🚑🚑", maximum = 4))
    }

    @Test fun laPositionVoyageSurLePortPriveEtSeRelit() {
        val trame = TramePosition(TramePosition.Genre.POSITION, 45.764043, 4.835659, 1763100000, statut = 2, batterie = 87, precisionM = 12)
        val relu = Meshtastic.lire(encapsulerCommeRecu(Meshtastic.prive(trame.enOctets(), 7, canal = 2)))
        assertIs<Meshtastic.Evenement.Prive>(relu)
        assertEquals(trame, TramePosition.lire(relu.charge))
        assertEquals(2, relu.canal)
    }

    /** Un ToRadio{packet=1} devient, à la réception, un FromRadio{packet=2} : même contenu. */
    private fun encapsulerCommeRecu(versRadio: ByteArray): ByteArray = versRadio.copyOf().also { it[0] = 0x12 }
}

class TramePositionTest {
    @Test fun seizeOctetsAllerEtRetour() {
        val trame = TramePosition(TramePosition.Genre.SOS, -21.115141, 55.536384, 1763100000, statut = 4, batterie = 9, precisionM = 300)
        val octets = trame.enOctets()
        assertEquals(16, octets.size)
        assertEquals(0x12, octets[0].toInt())                           // version 1, genre SOS
        // La précision est plafonnée ; le reste revient à l'identique, latitude négative comprise.
        assertEquals(trame.copy(precisionM = 255), TramePosition.lire(octets))
    }

    @Test fun uneAutreVersionOuUneAutreTailleNEstPasLue() {
        val octets = TramePosition(TramePosition.Genre.POSITION, 1.0, 2.0, 3).enOctets()
        assertNull(TramePosition.lire(octets.copyOf(15)))
        assertNull(TramePosition.lire(octets.copyOf().also { it[0] = 0x21 }))
    }
}
