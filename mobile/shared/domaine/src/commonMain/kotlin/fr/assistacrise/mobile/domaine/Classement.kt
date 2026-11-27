package fr.assistacrise.mobile.domaine

/**
 * Le classement « quoi + pour qui » (27/11/2026), miroir de backend/core/classement.py.
 *
 * La famille dit l'action (Transport / évacuation, Hébergement, Soins, Nourriture…) ; le « pour
 * qui » n'est demandé que si la famille en admet plusieurs ; la catégorie d'animaux seulement
 * pour des animaux. « Transport d'animaux » et « animaux à évacuer » ne sont qu'un chemin.
 */
object Classement {
    const val PERSONNES = "PERSONNES"
    const val ANIMAUX = "ANIMAUX"
    const val BIENS = "BIENS"

    private val P = PERSONNES
    private val A = ANIMAUX
    private val B = BIENS

    /** Par code de famille : (pour qui côté demande, pour qui côté offre). Une demande de soins
     * pour une personne n'existe pas : c'est le 15. */
    private val FAMILLES = mapOf(
        "EVAC" to (listOf(P, A, B) to listOf(P, A, B)),
        "ABRI" to (listOf(P, A) to listOf(P, A)),
        "SOIN" to (listOf(A) to listOf(P, A)),
        "NOUR" to (listOf(P, A) to listOf(P, A)),
        "PSY" to (listOf(P) to listOf(P)),
        "ADMIN" to (listOf(P) to listOf(P)),
        "LANG" to (emptyList<String>() to emptyList()),
        "NETT" to (listOf(B) to listOf(B)),
        "MAT" to (emptyList<String>() to emptyList()),
        "AUTRE" to (listOf(P, A, B) to listOf(P, A, B)),
    )

    val LIBELLES = mapOf(P to "Des personnes", A to "Des animaux", B to "Des biens (maison, matériel…)")
    val COURT = mapOf(P to "personnes", A to "animaux", B to "biens")

    /** Code radio (⚑BES) de chaque pour qui, comme CODE_BENEFICIAIRE au serveur. */
    val CODE = mapOf(P to "P", A to "A", B to "B")

    val CATEGORIES_ANIMAUX = listOf(
        "COMPAGNIE" to "Compagnie (chiens, chats…)",
        "EQUIDES" to "Chevaux, ânes",
        "BETAIL" to "Bétail (vaches, moutons, chèvres, porcs)",
        "VOLAILLES" to "Volailles",
        "AUTRES" to "Autres animaux",
    )

    /** Code radio de chaque catégorie, comme CODE_CATEGORIE_ANIMAUX au serveur. */
    val CODE_CATEGORIE = mapOf("COMPAGNIE" to "CO", "EQUIDES" to "EQ", "BETAIL" to "BE", "VOLAILLES" to "VO", "AUTRES" to "AU")

    /** Les familles qu'un intervenant peut relever par radio, avec leur libellé. */
    val FAMILLES_RADIO = listOf(
        "EVAC" to "Évacuation / transport", "ABRI" to "Hébergement", "SOIN" to "Soins (animaux)",
        "NOUR" to "Nourriture et eau", "NETT" to "Nettoyage / déblaiement", "MAT" to "Matériel", "AUTRE" to "Autre",
    )

    fun admis(code: String?, offre: Boolean): List<String> =
        FAMILLES[code ?: ""]?.let { if (offre) it.second else it.first }.orEmpty()

    /** Au-delà, la note est coupée : la radio n'emporte que l'essentiel. */
    const val NOTE_BESOIN_MAX = 30

    /**
     * Le texte d'un besoin relevé sur le terrain (message BES), lu par le serveur
     * (messages_terrain.lire_besoin) : famille, pour qui, catégorie, position, quelques mots.
     * Rien sur l'habitant.
     */
    fun besoin(code: String, beneficiaire: String?, categorie: String?, latitude: Double?, longitude: Double?, note: String = ""): String {
        var etiquette = code
        if (beneficiaire != null && beneficiaire in admis(code, offre = false)) {
            etiquette += "·" + CODE.getValue(beneficiaire)
            if (beneficiaire == ANIMAUX && categorie != null) CODE_CATEGORIE[categorie]?.let { etiquette += "·$it" }
        }
        val morceaux = mutableListOf(etiquette)
        if (latitude != null && longitude != null) morceaux += "${cinq(latitude)},${cinq(longitude)}"
        note.trim().take(NOTE_BESOIN_MAX).trimEnd().takeIf { it.isNotEmpty() }?.let { morceaux += it }
        return morceaux.joinToString(" ")
    }

    /** Cinq décimales, sans dépendre de la langue du téléphone (pas de virgule décimale). */
    private fun cinq(x: Double): String {
        val signe = if (x < 0) "-" else ""
        val v = kotlin.math.round(kotlin.math.abs(x) * 100000).toLong()
        return "$signe${v / 100000}.${(v % 100000).toString().padStart(5, '0')}"
    }
}
