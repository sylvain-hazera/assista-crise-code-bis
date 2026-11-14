package fr.assistacrise.mobile.lien.meshtastic

/**
 * L'interface « téléphone » de Meshtastic, réduite à ce que l'application en dit : se
 * présenter, rester en vie, envoyer et recevoir du texte.
 *
 * Porté de `frontend/src/app/shared/mesh/meshtastic-trames.ts`, vérifié octet pour octet
 * contre les messages générés par la bibliothèque officielle (2.7.11). Les tests reprennent
 * les mêmes vecteurs. L'administration de la radio (canaux, clés) n'est pas portée :
 * l'application utilise une radio déjà configurée (dossier § 2).
 */
object Meshtastic {
    const val SERVICE = "6ba1b218-15a8-461f-9fa8-5dcae273eafd"
    const val TO_RADIO = "f75c76d2-129e-4dad-a1dd-7866124401e7"
    const val FROM_RADIO = "2c55e69e-4993-11ed-b878-0242ac120002"
    const val FROM_NUM = "ed9da18c-a800-4f66-a670-aa7547e34453"

    const val DIFFUSION = 0xffffffffL
    const val PORT_TEXTE = 1
    /** Port réservé aux applications privées : c'est là que voyage la trame de position. */
    const val PORT_PRIVE = 256
    const val CHARGE_MAX = 200

    /** La poignée de main se fait en deux temps, avec ces deux identifiants que le firmware
     * reconnaît : la configuration, puis la liste des nœuds. Jamais d'identifiant au hasard. */
    const val NONCE_CONFIG = 69420L
    const val NONCE_NOEUDS = 69421L

    /** Les battements comptent à partir de 2 : un firmware récent jette une écriture
     * identique à la précédente, et lit le nonce 1 comme « diffuse ta fiche ». */
    const val PREMIER_NONCE_BATTEMENT = 2L
    const val PERIODE_BATTEMENT_MS = 30_000L

    fun veutConfig(identifiant: Long): ByteArray = Ecrivain().varint(3, identifiant).fin()

    fun battement(nonce: Long): ByteArray = Ecrivain().message(7, Ecrivain().varint(1, nonce)).fin()

    fun nonceSuivant(nonce: Long): Long = if (nonce >= 0xffffffffL) PREMIER_NONCE_BATTEMENT else nonce + 1

    /** Message texte : direct (avec accusé) ou sur un canal (`destinataire = DIFFUSION`). */
    fun texte(destinataire: Long, contenu: String, identifiant: Long, canal: Int = 0, accuse: Boolean = true): ByteArray =
        paquet(destinataire, PORT_TEXTE, contenu.encodeToByteArray(), identifiant, canal, accuse)

    /** Charge binaire sur le port privé — la trame de position de seize octets. */
    fun prive(charge: ByteArray, identifiant: Long, canal: Int): ByteArray =
        paquet(DIFFUSION, PORT_PRIVE, charge, identifiant, canal, accuse = false)

    private fun paquet(destinataire: Long, port: Int, charge: ByteArray, identifiant: Long, canal: Int, accuse: Boolean): ByteArray {
        require(charge.size <= CHARGE_MAX) { "Charge trop longue pour un paquet Meshtastic." }
        val donnees = Ecrivain().varint(1, port.toLong()).brut(2, charge)
        val paquet = Ecrivain()
            .fixe32(2, destinataire)
            .varint(3, canal.toLong())
            .message(4, donnees)
            .fixe32(6, identifiant)
            .booleen(10, accuse)
        return Ecrivain().message(1, paquet).fin()
    }

    /** Découpe un texte sans jamais couper un caractère en deux. */
    fun decouper(contenu: String, maximum: Int = CHARGE_MAX): List<String> {
        val morceaux = ArrayList<String>()
        val courant = StringBuilder()
        var taille = 0
        var i = 0
        while (i < contenu.length) {
            // Un caractère hors du plan de base tient sur deux unités : on les garde ensemble.
            val fin = if (contenu[i].isHighSurrogate() && i + 1 < contenu.length) i + 2 else i + 1
            val caractere = contenu.substring(i, fin)
            val n = caractere.encodeToByteArray().size
            if (taille + n > maximum && courant.isNotEmpty()) { morceaux.add(courant.toString()); courant.clear(); taille = 0 }
            courant.append(caractere); taille += n
            i = fin
        }
        if (courant.isNotEmpty() || morceaux.isEmpty()) morceaux.add(courant.toString())
        return morceaux
    }

    sealed class Evenement {
        data class MonNoeud(val numero: Long) : Evenement()
        data class ConfigTerminee(val identifiant: Long) : Evenement()
        data class Texte(val de: Long, val vers: Long, val canal: Int, val texte: String, val id: Long) : Evenement()
        data class Prive(val de: Long, val canal: Int, val charge: ByteArray) : Evenement()
        /** Une trame de la poignée de main : elle prouve que la radio parle encore. */
        data object Progression : Evenement()
        data object Autre : Evenement()
    }

    /** Lève `IllegalArgumentException` sur une trame tronquée. */
    fun lire(octets: ByteArray): Evenement {
        val racine = lireChamps(octets)
        racine.champ(3)?.octets?.let { return Evenement.MonNoeud(lireChamps(it).champ(1)?.nombre ?: 0) }
        racine.champ(7)?.nombre?.let { return Evenement.ConfigTerminee(it) }
        if (racine.any { it.numero in setOf(4, 5, 9, 10, 13, 15, 17) || it.numero >= 19 }) return Evenement.Progression
        val paquet = racine.champ(2)?.octets ?: return Evenement.Autre
        val p = lireChamps(paquet)
        val decode = p.champ(4)?.octets ?: return Evenement.Autre      // chiffré pour quelqu'un d'autre
        val d = lireChamps(decode)
        val de = p.champ(1)?.nombre ?: 0
        val canal = (p.champ(3)?.nombre ?: 0).toInt()
        val charge = d.champ(2)?.octets ?: ByteArray(0)
        return when ((d.champ(1)?.nombre ?: 0).toInt()) {
            PORT_TEXTE -> Evenement.Texte(de, p.champ(2)?.nombre ?: 0, canal, charge.decodeToString(), p.champ(6)?.nombre ?: 0)
            PORT_PRIVE -> Evenement.Prive(de, canal, charge)
            else -> Evenement.Autre
        }
    }
}
