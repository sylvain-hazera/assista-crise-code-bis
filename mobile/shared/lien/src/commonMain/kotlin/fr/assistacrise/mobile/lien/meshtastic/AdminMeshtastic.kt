package fr.assistacrise.mobile.lien.meshtastic

/**
 * « Utilisateur radio avancé », côté Meshtastic (22/11/2026) : lire et écrire l'intégralité des
 * réglages, canaux et contacts de la radio connectée, par les messages d'administration
 * (`AdminMessage`, port 6) adressés au nœud local.
 *
 * Les réglages sont décrits par `SchemaMeshtastic` (numéro, type, valeurs possibles), et lus ou
 * écrits par un codec protobuf générique : aucune définition n'est embarquée, seulement les
 * numéros (voir la licence dans `SchemaMeshtastic.kt`).
 */
enum class TypeReglage { BOOL, UINT, INT, SINT, FLOAT, FIXED32, SFIXED32, TEXTE, OCTETS, ENUM, MESSAGE, DOUBLE, FIXED64 }

enum class Conteneur { CONFIG, MODULE }

data class ChampReglage(
    val numero: Int,
    val nom: String,
    val type: TypeReglage,
    val valeurs: List<Pair<Int, String>> = emptyList(),
    /** Peut couper la radio du réseau (région, préréglage, fréquence…) : confirmation renforcée. */
    val sensible: Boolean = false,
    /** Clé ou mot de passe : saisi et affiché masqué, jamais journalisé. */
    val secret: Boolean = false,
) {
    /** Le nom affiché : « position_broadcast_secs » devient « Position broadcast secs ». */
    val libelle: String get() = nom.replace('_', ' ').replaceFirstChar { it.uppercase() }
}

data class SectionReglage(
    val conteneur: Conteneur,
    /** Numéro du champ dans `Config` / `ModuleConfig` ; le type de demande vaut numéro − 1. */
    val numero: Int,
    val cle: String,
    val libelle: String,
    val champs: List<ChampReglage>,
)

/** Un nœud entendu (« contacts » Meshtastic). */
data class NoeudMeshtastic(
    val numero: Long,
    val nomLong: String,
    val nomCourt: String,
    val snr: Float? = null,
    val dernierContact: Long? = null,
    val sauts: Int? = null,
    val favori: Boolean = false,
    val latitude: Double? = null,
    val longitude: Double? = null,
    /** Batterie en % (101 = alimenté sur secteur), d'après les métriques de l'appareil. */
    val batterie: Int? = null,
    /** Taux d'occupation du canal radio vu par ce nœud, en %. */
    val occupationCanal: Float? = null,
    /** Entendu par Internet (MQTT) plutôt que par la radio. */
    val parInternet: Boolean = false,
) {
    val identifiant: String get() = "!" + numero.toString(16).padStart(8, '0')
}

/** Un emplacement de canal, avec sa clé (PSK). `role` : 0 désactivé, 1 primaire, 2 secondaire. */
data class CanalMeshtastic(
    val index: Int,
    val nom: String,
    val role: Int,
    val psk: ByteArray = ByteArray(0),
    val montant: Boolean = false,
    val descendant: Boolean = false,
    val precisionPosition: Int = 0,
)

object AdminMeshtastic {
    const val PORT_ADMIN = 6

    // ── Codec générique ──

    /** Lit une section en valeurs typées par le schéma : Boolean, Long, Float, Double, String, ByteArray. */
    fun lireSection(section: SectionReglage, octets: ByteArray): Map<Int, Any> {
        val bruts = lireChamps(octets)
        val valeurs = LinkedHashMap<Int, Any>()
        for (c in section.champs) {
            val b = bruts.lastOrNull { it.numero == c.numero }
            valeurs[c.numero] = when (c.type) {
                TypeReglage.BOOL -> (b?.nombre ?: 0L) != 0L
                TypeReglage.UINT, TypeReglage.ENUM, TypeReglage.FIXED32 -> b?.nombre ?: 0L
                TypeReglage.INT -> (b?.nombre ?: 0L).toInt().toLong()   // int32 : les 32 bits de poids faible
                TypeReglage.SINT -> (b?.nombre ?: 0L).let { (it ushr 1) xor -(it and 1) }
                TypeReglage.SFIXED32 -> (b?.nombre ?: 0L).toInt().toLong()
                TypeReglage.FLOAT -> Float.fromBits((b?.nombre ?: 0L).toInt())
                TypeReglage.TEXTE -> b?.octets?.decodeToString() ?: ""
                TypeReglage.OCTETS -> b?.octets ?: ByteArray(0)
                TypeReglage.DOUBLE, TypeReglage.FIXED64, TypeReglage.MESSAGE -> continue
            }
        }
        return valeurs
    }

    /**
     * Réécrit une section : les valeurs du schéma sont remplacées, et **tout le reste est gardé
     * tel que la radio l'a donné** (sous-messages, listes, champs plus récents que ce schéma) —
     * sans quoi enregistrer une section effacerait ce que l'application ne sait pas afficher.
     */
    fun ecrireSection(section: SectionReglage, origine: ByteArray, valeurs: Map<Int, Any>): ByteArray {
        val connus = section.champs.associateBy { it.numero }
        // Par numéro croissant, comme les bibliothèques officielles : un octet près, la radio
        // reçoit la même trame que celle qu'enverrait leur application.
        val morceaux = sortedMapOf<Int, MutableList<ByteArray>>()
        fun ajouter(numero: Int, e: Ecrivain) { morceaux.getOrPut(numero) { mutableListOf() } += e.fin() }
        for (b in lireChamps(origine)) {
            if (b.numero in connus) continue
            when {
                b.octets != null -> ajouter(b.numero, Ecrivain().messageBrut(b.numero, b.octets))
                b.nombre != null -> ajouter(b.numero, Ecrivain().varint(b.numero, b.nombre))
            }
        }
        for (c in section.champs) {
            val v = valeurs[c.numero] ?: continue
            val e = Ecrivain()
            when (c.type) {
                TypeReglage.BOOL -> e.booleen(c.numero, v as Boolean)
                TypeReglage.UINT, TypeReglage.ENUM, TypeReglage.INT -> e.varint(c.numero, (v as Number).toLong())
                TypeReglage.SINT -> (v as Number).toLong().let { e.varint(c.numero, (it shl 1) xor (it shr 63)) }
                TypeReglage.FIXED32, TypeReglage.SFIXED32 -> e.fixe32(c.numero, (v as Number).toLong() and 0xffffffffL)
                TypeReglage.FLOAT -> e.fixe32(c.numero, (v as Number).toFloat().toRawBits().toLong() and 0xffffffffL)
                TypeReglage.TEXTE -> e.brut(c.numero, (v as String).encodeToByteArray())
                TypeReglage.OCTETS -> e.brut(c.numero, v as ByteArray)
                else -> Unit
            }
            ajouter(c.numero, e)
        }
        return morceaux.values.flatten().fold(ByteArray(0)) { acc, b -> acc + b }
    }

    // ── Messages d'administration (champs de AdminMessage) ──

    private fun admin(champ: (Ecrivain) -> Ecrivain): ByteArray = champ(Ecrivain()).fin()

    fun demanderConfig(section: SectionReglage): ByteArray = admin {
        // proto3 : la valeur 0 (DEVICE_CONFIG, MQTT_CONFIG) ne s'écrirait pas ; on la force.
        forcerVarint(it, if (section.conteneur == Conteneur.CONFIG) 5 else 7, (section.numero - 1).toLong())
    }

    fun ecrireConfig(section: SectionReglage, contenu: ByteArray): ByteArray = admin {
        val enveloppe = Ecrivain().messageBrut(section.numero, contenu)
        it.message(if (section.conteneur == Conteneur.CONFIG) 34 else 35, enveloppe)
    }

    fun demanderCanal(index: Int): ByteArray = admin { it.varint(1, (index + 1).toLong()) }

    fun ecrireCanal(c: CanalMeshtastic): ByteArray = admin {
        val reglages = Ecrivain().brut(2, c.psk).brut(3, c.nom.encodeToByteArray())
            .booleen(5, c.montant).booleen(6, c.descendant)
            .message(7, Ecrivain().varint(1, c.precisionPosition.toLong()))
        val canal = Ecrivain().also { e -> forcerVarint(e, 1, c.index.toLong()) }.message(2, reglages).varint(3, c.role.toLong())
        it.message(33, canal)
    }

    fun ecrireProprietaire(nomLong: String, nomCourt: String): ByteArray =
        admin { it.message(32, Ecrivain().brut(2, nomLong.encodeToByteArray()).brut(3, nomCourt.encodeToByteArray())) }

    fun demanderProprietaire(): ByteArray = admin { it.booleen(3, true) }
    fun commencerEdition(): ByteArray = admin { it.booleen(64, true) }
    fun validerEdition(): ByteArray = admin { it.booleen(65, true) }
    fun retirerNoeud(numero: Long): ByteArray = admin { it.varint(38, numero) }
    fun favori(numero: Long, oui: Boolean): ByteArray = admin { it.varint(if (oui) 39 else 40, numero) }
    fun redemarrer(secondes: Int = 2): ByteArray = admin { it.varint(97, secondes.toLong()) }
    fun reinitialiserNoeuds(): ByteArray = admin { it.booleen(100, true) }
    fun retourUsine(): ByteArray = admin { it.varint(99, 1) }

    /** Enveloppe un message d'administration pour le nœud local (`ToRadio.packet`). */
    fun paquet(monNoeud: Long, admin: ByteArray, identifiant: Long): ByteArray {
        val donnees = Ecrivain().varint(1, PORT_ADMIN.toLong()).brut(2, admin).booleen(3, true)
        val paquet = Ecrivain().fixe32(2, monNoeud).message(4, donnees).fixe32(6, identifiant).booleen(10, true)
        return Ecrivain().message(1, paquet).fin()
    }

    private fun forcerVarint(e: Ecrivain, numero: Int, valeur: Long): Ecrivain =
        if (valeur != 0L) e.varint(numero, valeur) else e.zero(numero)

    // ── Lecture de ce que la radio décrit ──

    sealed class Lu {
        data class Config(val conteneur: Conteneur, val numero: Int, val contenu: ByteArray) : Lu()
        data class Canal(val canal: CanalMeshtastic) : Lu()
        data class Noeud(val noeud: NoeudMeshtastic) : Lu()
        data class Proprietaire(val nomLong: String, val nomCourt: String) : Lu()
    }

    /** Ce qu'une trame `FromRadio` apprend des réglages, canaux, nœuds ; `null` sinon. */
    fun lire(trame: ByteArray): Lu? {
        val racine = runCatching { lireChamps(trame) }.getOrNull() ?: return null
        racine.champ(5)?.octets?.let { return section(Conteneur.CONFIG, it) }
        racine.champ(9)?.octets?.let { return section(Conteneur.MODULE, it) }
        racine.champ(10)?.octets?.let { return Lu.Canal(canal(it)) }
        racine.champ(4)?.octets?.let { return noeud(it)?.let(Lu::Noeud) }
        // Réponse d'administration (port 6) : get_config / get_module_config / get_channel / get_owner.
        val p = racine.champ(2)?.octets?.let(::lireChamps) ?: return null
        val d = p.champ(4)?.octets?.let(::lireChamps) ?: return null
        if ((d.champ(1)?.nombre ?: 0L).toInt() != PORT_ADMIN) return null
        val a = d.champ(2)?.octets?.let(::lireChamps) ?: return null
        a.champ(6)?.octets?.let { return section(Conteneur.CONFIG, it) }
        a.champ(8)?.octets?.let { return section(Conteneur.MODULE, it) }
        a.champ(2)?.octets?.let { return Lu.Canal(canal(it)) }
        a.champ(4)?.octets?.let { u ->
            val c = lireChamps(u)
            return Lu.Proprietaire(c.champ(2)?.octets?.decodeToString() ?: "", c.champ(3)?.octets?.decodeToString() ?: "")
        }
        return null
    }

    private fun section(conteneur: Conteneur, octets: ByteArray): Lu? {
        val c = lireChamps(octets).firstOrNull { it.octets != null } ?: return null
        return Lu.Config(conteneur, c.numero, c.octets!!)
    }

    private fun canal(octets: ByteArray): CanalMeshtastic {
        val c = lireChamps(octets)
        val r = c.champ(2)?.octets?.let(::lireChamps) ?: emptyList()
        val m = r.champ(7)?.octets?.let(::lireChamps) ?: emptyList()
        return CanalMeshtastic(
            index = (c.champ(1)?.nombre ?: 0).toInt(), nom = r.champ(3)?.octets?.decodeToString() ?: "",
            role = (c.champ(3)?.nombre ?: 0).toInt(), psk = r.champ(2)?.octets ?: ByteArray(0),
            montant = (r.champ(5)?.nombre ?: 0) != 0L, descendant = (r.champ(6)?.nombre ?: 0) != 0L,
            precisionPosition = (m.champ(1)?.nombre ?: 0).toInt(),
        )
    }

    private fun noeud(octets: ByteArray): NoeudMeshtastic? {
        val n = lireChamps(octets)
        val numero = n.champ(1)?.nombre ?: return null
        val u = n.champ(2)?.octets?.let(::lireChamps) ?: emptyList()
        val pos = n.champ(3)?.octets?.let(::lireChamps) ?: emptyList()
        val lat = pos.champ(1)?.nombre?.toInt()?.takeIf { it != 0 }?.let { it / 1e7 }
        val lon = pos.champ(2)?.nombre?.toInt()?.takeIf { it != 0 }?.let { it / 1e7 }
        val metriques = n.champ(6)?.octets?.let(::lireChamps) ?: emptyList()
        return NoeudMeshtastic(
            numero = numero, nomLong = u.champ(2)?.octets?.decodeToString() ?: "", nomCourt = u.champ(3)?.octets?.decodeToString() ?: "",
            snr = n.champ(4)?.nombre?.let { Float.fromBits(it.toInt()) }, dernierContact = n.champ(5)?.nombre,
            sauts = n.champ(9)?.nombre?.toInt(), favori = (n.champ(10)?.nombre ?: 0) != 0L, latitude = lat, longitude = lon,
            batterie = metriques.champ(1)?.nombre?.toInt(),
            occupationCanal = metriques.champ(3)?.nombre?.let { Float.fromBits(it.toInt()) },
            parInternet = (n.champ(8)?.nombre ?: 0) != 0L,
        )
    }

    /** Lien de partage d'un canal (format des applications officielles : URL + clé encodée). */
    fun pskLisible(psk: ByteArray): String = when {
        psk.isEmpty() -> "aucune (non chiffré)"
        psk.size == 1 -> "par défaut n° ${psk[0].toInt() and 0xff}"
        else -> "${psk.size * 8} bits"
    }
}
