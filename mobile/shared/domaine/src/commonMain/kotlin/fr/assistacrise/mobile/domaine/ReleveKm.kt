package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * « Je pars », « je rentre » et le relevé kilométrique (28/11/2026), miroir de `mon-engagement/`
 * (backend/core/engagements_personnels.py).
 *
 * L'heure du départ et du retour est celle du serveur au moment du geste : le téléphone n'en
 * fabrique aucune. Le déplacement (véhicule, compteurs, km, péage, stationnement) est
 * facultatif et se complète ensuite dans « Mon relevé » sur le site.
 */
@Serializable
data class VehiculePersonnel(
    val id: String,
    val genre: String = "VOITURE",
    val libelle: String = "",
    val immatriculation: String = "",
    @SerialName("puissance_cv") val puissanceCv: Int? = null,
    val designation: String = "",
)

@Serializable
data class EngagementEnCours(
    val crise: String? = null,
    @SerialName("crise_nom") val nom: String = "",
    val manifestation: String? = null,
    @SerialName("equipe_nom") val equipe: String? = null,
    @SerialName("parti_le") val partiLe: String = "",
    @SerialName("depart_de") val departDe: String = "DOMICILE",
    val hebergement: String = "",
    @SerialName("vehicule_personnel") val vehicule: String? = null,
    @SerialName("compteur_depart") val compteurDepart: String = "",
    @SerialName("motif_propose") val motifPropose: String = "",
    @SerialName("arrivee_proposee") val arriveePropose: String = "",
)

/** Une crise, une manifestation ou une équipe proposée au départ. */
@Serializable
data class CibleDepart(
    val id: String,
    val nom: String,
    val hebergement: String = "",
    val debut: String = "",
)

@Serializable
data class EtatEngagement(
    @SerialName("en_cours") val enCours: EngagementEnCours? = null,
    val crises: List<CibleDepart> = emptyList(),
    val equipes: List<CibleDepart> = emptyList(),
    val manifestations: List<CibleDepart> = emptyList(),
    val vehicules: List<VehiculePersonnel> = emptyList(),
) {
    /** Rien à déclarer : ni départ en cours, ni crise ou manifestation où partir. */
    val vide: Boolean get() = enCours == null && crises.isEmpty() && manifestations.isEmpty()
}

/** Ce que la personne dit de son déplacement au retour ; tout est facultatif. */
data class Retour(
    val kilometres: String = "",
    val compteurArrivee: String = "",
    val lieuArrivee: String = "",
    val motif: String = "",
    val allerRetour: Boolean = true,
    val peage: String = "",
    val stationnement: String = "",
) {
    /** Les champs à envoyer : seulement ce qui est saisi, comme le site. */
    fun champs(): Map<String, Any> = buildMap {
        if (kilometres.isNotBlank()) put("kilometres", kilometres.trim())
        if (compteurArrivee.isNotBlank()) put("compteur_arrivee", compteurArrivee.filter { it.isDigit() })
        if (lieuArrivee.isNotBlank()) put("lieu_arrivee", lieuArrivee.trim())
        if (motif.isNotBlank()) put("motif", motif.trim())
        if (!allerRetour) put("aller_retour", false)
        if (peage.isNotBlank()) put("peage", peage.trim())
        if (stationnement.isNotBlank()) put("stationnement", stationnement.trim())
    }
}

object ReleveKm {
    /** Les kilomètres d'après les compteurs, ou null s'ils manquent, sont illisibles ou à
     * rebours. Même règle que le serveur : 3000 km au plus. */
    fun kmCompteurs(depart: String, arrivee: String): Int? {
        val d = depart.filterNot { it.isWhitespace() }.toIntOrNull() ?: return null
        val a = arrivee.filterNot { it.isWhitespace() }.toIntOrNull() ?: return null
        val ecart = a - d
        return ecart.takeIf { it in 0..3000 }
    }
}

/**
 * La distance parcourue depuis le départ, cumulée à partir des positions que le suivi relève
 * déjà. **Seule la distance est gardée, jamais la trace** : une position ne sert qu'à mesurer
 * l'écart avec la précédente, puis elle est oubliée.
 *
 * C'est une estimation, proposée au retour et jamais envoyée d'office : le suivi ne relève
 * qu'une position toutes les 30 s et 50 m, la route réelle est donc un peu plus longue.
 */
class DistanceParcourue(metres: Double = 0.0, private var derniere: Releve? = null) {
    var metres: Double = metres
        private set

    fun ajouter(r: Releve) {
        // Une position trop floue fausse plus la mesure qu'elle ne l'aide.
        if (r.precisionM > PRECISION_MAX_M) return
        val avant = derniere
        derniere = r
        if (avant == null || r.instant <= avant.instant) return
        val d = avant.distanceA(r)
        val heures = (r.instant - avant.instant) / 3_600_000.0
        // Un saut impossible (plus de 200 km/h) est une position aberrante : on la saute, et la
        // suivante repart d'elle.
        if (d / 1000 / heures > VITESSE_MAX_KMH) return
        metres += d
    }

    /** L'estimation arrondie au km, ou null s'il n'y a rien de mesuré. */
    val kilometres: Int? get() = (metres / 1000).let { if (it < 0.5) null else kotlin.math.round(it).toInt() }

    /** Pour le magasin local : la distance et la dernière position, rien d'autre. */
    fun enTexte(): String = derniere?.let { "$metres;${it.latitude};${it.longitude};${it.instant}" } ?: "$metres"

    companion object {
        const val PRECISION_MAX_M = 100f
        const val VITESSE_MAX_KMH = 200.0

        fun depuis(texte: String?): DistanceParcourue {
            val p = texte?.split(';') ?: return DistanceParcourue()
            val m = p.getOrNull(0)?.toDoubleOrNull() ?: return DistanceParcourue()
            val r = if (p.size == 4) {
                val la = p[1].toDoubleOrNull(); val lo = p[2].toDoubleOrNull(); val t = p[3].toLongOrNull()
                if (la != null && lo != null && t != null) Releve(la, lo, t) else null
            } else null
            return DistanceParcourue(m, r)
        }
    }
}
