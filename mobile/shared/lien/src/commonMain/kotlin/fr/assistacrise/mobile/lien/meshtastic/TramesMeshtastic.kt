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
    /** ROUTING_APP : accusés de réception et erreurs de routage. */
    const val PORT_ROUTAGE = 5
    /** TRACEROUTE_APP : la route aller et retour vers un nœud, avec le signal à chaque saut. */
    const val PORT_TRACEROUTE = 70
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
    fun texte(destinataire: Long, contenu: String, identifiant: Long, canal: Int = 0, accuse: Boolean = true,
              repondA: Long = 0, emoji: Boolean = false): ByteArray =
        paquet(destinataire, PORT_TEXTE, contenu.encodeToByteArray(), identifiant, canal, accuse, repondA, emoji)

    /** Demande de traceroute (RouteDiscovery vide, réponse demandée) : la réponse revient sur le
     * même port, avec `request_id` = `identifiant` (26/11/2026). */
    fun traceroute(destinataire: Long, identifiant: Long): ByteArray =
        paquet(destinataire, PORT_TRACEROUTE, ByteArray(0), identifiant, 0, accuse = false, veutReponse = true)

    /** Charge binaire sur le port privé — la trame de position de seize octets. */
    fun prive(charge: ByteArray, identifiant: Long, canal: Int): ByteArray =
        paquet(DIFFUSION, PORT_PRIVE, charge, identifiant, canal, accuse = false)

    private fun paquet(destinataire: Long, port: Int, charge: ByteArray, identifiant: Long, canal: Int, accuse: Boolean,
                       repondA: Long = 0, emoji: Boolean = false, veutReponse: Boolean = false): ByteArray {
        require(charge.size <= CHARGE_MAX) { "Charge trop longue pour un paquet Meshtastic." }
        // Data : 7 reply_id, 8 emoji (1 = la charge est une réaction posée sur reply_id).
        val donnees = Ecrivain().varint(1, port.toLong()).brut(2, charge).booleen(3, veutReponse)
            .fixe32(7, repondA).fixe32(8, if (emoji) 1 else 0)
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

    /** `repeated fixed32` : empaqueté (un bloc d'octets) ou non. */
    private fun fixes32(champs: List<Champ>, numero: Int): List<Long> = champs.filter { it.numero == numero }.flatMap { c ->
        c.octets?.toList()?.chunked(4)?.filter { it.size == 4 }?.map { o -> o.foldIndexed(0L) { i, acc, b -> acc or ((b.toLong() and 0xff) shl (8 * i)) } }
            ?: listOfNotNull(c.nombre)
    }

    /** `repeated int32` (SNR × 4, INT8_MIN = inconnu), empaqueté ou non. */
    private fun snrs(champs: List<Champ>, numero: Int): List<Float?> = champs.filter { it.numero == numero }.flatMap { c ->
        val valeurs = c.octets?.let { o ->
            val l = ArrayList<Long>(); var i = 0
            while (i < o.size) { var v = 0L; var n = 0
                while (i < o.size) { val b = o[i++].toLong() and 0xff; v = v or ((b and 0x7f) shl (7 * n)); n++; if (b and 0x80 == 0L) break }
                l.add(v) }
            l
        } ?: listOfNotNull(c.nombre)
        valeurs.map { it.toInt() }.map { if (it == -128) null else it / 4f }
    }

    /** Ce qu'une erreur de routage veut dire pour l'intervenant (null si remis). */
    fun raisonErreur(code: Int): String? = when (code) {
        0 -> null
        1 -> "aucune route"
        3 -> "pas de réponse à temps"
        5 -> "trop de réémissions sans accusé"
        8 -> "pas de réponse"
        32, 33, 34, 35 -> "refusé (clé ou droits)"
        else -> "erreur de routage $code"
    }

    /** Pour les tests : la fin de configuration que la radio renvoie à une demande (`ToRadio`
     * champ 3 → `FromRadio` champ 7, même identifiant). */
    fun lireEcho(veutConfig: ByteArray): ByteArray = veutConfig.copyOf().also { it[0] = 0x38 }

    sealed class Evenement {
        data class MonNoeud(val numero: Long) : Evenement()
        data class ConfigTerminee(val identifiant: Long) : Evenement()
        /** Un emplacement de canal de la radio. `role` : 0 désactivé, 1 primaire, 2 secondaire. */
        data class Canal(val index: Int, val nom: String, val role: Int) : Evenement()
        /** `sauts` : hop_start - hop_limit (null sur un firmware trop ancien pour le dire). */
        data class Texte(
            val de: Long, val vers: Long, val canal: Int, val texte: String, val id: Long,
            val sauts: Int? = null, val snr: Float? = null, val rssi: Int? = null, val parInternet: Boolean = false,
            val repondA: Long = 0, val emoji: Boolean = false,
        ) : Evenement()
        /** Réponse de traceroute : nœuds relais à l'aller et au retour, SNR (dB) de chaque saut
         * (le dernier est celui de l'arrivée). Un SNR inconnu vaut null. */
        data class Trajet(val de: Long, val requete: Long, val aller: List<Long>, val snrAller: List<Float?>,
                          val retour: List<Long>, val snrRetour: List<Float?>) : Evenement()
        /** Accusé (port ROUTING) du paquet `requete` ; `erreur` 0 = remis. */
        data class Accuse(val de: Long, val requete: Long, val erreur: Int) : Evenement()
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
        racine.champ(10)?.octets?.let { canal ->
            val c = lireChamps(canal)
            val reglages = c.champ(2)?.octets?.let(::lireChamps) ?: emptyList()
            return Evenement.Canal(
                index = (c.champ(1)?.nombre ?: 0).toInt(),
                nom = reglages.champ(3)?.octets?.decodeToString() ?: "",
                role = (c.champ(3)?.nombre ?: 0).toInt(),
            )
        }
        if (racine.any { it.numero in setOf(4, 5, 9, 13, 15, 17) || it.numero >= 19 }) return Evenement.Progression
        val paquet = racine.champ(2)?.octets ?: return Evenement.Autre
        val p = lireChamps(paquet)
        val decode = p.champ(4)?.octets ?: return Evenement.Autre      // chiffré pour quelqu'un d'autre
        val d = lireChamps(decode)
        val de = p.champ(1)?.nombre ?: 0
        val canal = (p.champ(3)?.nombre ?: 0).toInt()
        val charge = d.champ(2)?.octets ?: ByteArray(0)
        return when ((d.champ(1)?.nombre ?: 0).toInt()) {
            PORT_TEXTE -> {
                val depart = p.champ(15)?.nombre?.toInt() ?: 0
                val restant = p.champ(9)?.nombre?.toInt() ?: 0
                Evenement.Texte(
                    de, p.champ(2)?.nombre ?: 0, canal, charge.decodeToString(), p.champ(6)?.nombre ?: 0,
                    sauts = if (depart > 0 && depart >= restant) depart - restant else null,
                    snr = p.champ(8)?.nombre?.let { Float.fromBits(it.toInt()) }?.takeIf { it != 0f },
                    rssi = p.champ(12)?.nombre?.toInt()?.takeIf { it != 0 },
                    parInternet = (p.champ(14)?.nombre ?: 0) != 0L,
                    repondA = d.champ(7)?.nombre ?: 0, emoji = (d.champ(8)?.nombre ?: 0) != 0L,
                )
            }
            PORT_TRACEROUTE -> {
                val requete = d.champ(6)?.nombre?.takeIf { it != 0L } ?: return Evenement.Autre   // une demande, pas une réponse
                val r = lireChamps(charge)
                Evenement.Trajet(de, requete, fixes32(r, 1), snrs(r, 2), fixes32(r, 3), snrs(r, 4))
            }
            PORT_ROUTAGE -> {
                val routage = lireChamps(charge)
                val requete = d.champ(6)?.nombre ?: return Evenement.Autre
                Evenement.Accuse(de, requete, (routage.champ(3)?.nombre ?: 0).toInt())
            }
            PORT_PRIVE -> Evenement.Prive(de, canal, charge)
            else -> Evenement.Autre
        }
    }
}
