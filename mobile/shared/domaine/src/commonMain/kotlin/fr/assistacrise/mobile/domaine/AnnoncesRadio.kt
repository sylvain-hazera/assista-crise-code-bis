package fr.assistacrise.mobile.domaine

/**
 * Interventions annoncées par radio (26/11/2026). Le central dit à une équipe, sur son canal, qu'un
 * dossier lui est confié — ou le redit quand un intervenant demande « @PC MAJ » :
 *
 *     📋 D-0123 · Pompage · Talence · 44.80000,-0.59000
 *
 * Numéro, nature, commune, position ; rien sur l'habitant. Le détail arrive par le réseau dès
 * qu'il revient, et la ligne reçue par radio s'efface devant le vrai dossier (même numéro).
 * Même format au serveur (core/annonces_radio.py).
 */
object AnnoncesRadio {
    const val PREFIXE = "📋"
    const val DEMANDE_MAJ = "@PC MAJ"
    private const val SEPARATEUR = "·"
    private val PREFIXE_NOM = Regex("""^[^:\n]{1,40}: """)
    private val POSITION = Regex("""^(-?\d+\.?\d*),(-?\d+\.?\d*)$""")

    data class Annonce(val numero: String, val nature: String = "", val commune: String = "",
                       val latitude: Double? = null, val longitude: Double? = null) {
        val situee: Boolean get() = latitude != null && longitude != null
    }

    fun lire(texte: String): Annonce? {
        var t = texte.trim()
        repeat(3) {
            if (t.startsWith(PREFIXE)) return@repeat
            val m = PREFIXE_NOM.find(t) ?: return null
            t = t.substring(m.range.last + 1).trimStart()
        }
        if (!t.startsWith(PREFIXE)) return null
        val morceaux = t.removePrefix(PREFIXE).split(SEPARATEUR).map { it.trim() }
        val numero = morceaux.firstOrNull()?.takeIf { it.isNotEmpty() } ?: return null
        fun champ(i: Int) = morceaux.getOrNull(i)?.takeIf { it != "-" } ?: ""
        val position = morceaux.getOrNull(3)?.let { POSITION.find(it) }
        val lat = position?.groupValues?.get(1)?.toDoubleOrNull()?.takeIf { it in -90.0..90.0 }
        val lon = position?.groupValues?.get(2)?.toDoubleOrNull()?.takeIf { it in -180.0..180.0 }
        return Annonce(numero, champ(1), champ(2), lat.takeIf { lon != null }, lon.takeIf { lat != null })
    }

    /** Les annonces encore utiles : la plus récente par numéro, sans celles dont le vrai dossier
     * est déjà sur le téléphone. */
    fun aGarder(annonces: List<Pair<Annonce, Long>>, numerosConnus: Set<String>): List<Pair<Annonce, Long>> =
        annonces.sortedByDescending { it.second }.distinctBy { it.first.numero }
            .filter { it.first.numero !in numerosConnus }
}
