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


// ── Mon relevé dans l'application (28/11/2026), miroir de `mon-releve/` ───────────────────

@Serializable
data class FraisLigne(
    val id: String,
    val nature: String,
    @SerialName("nature_libelle") val libelle: String = "",
    val montant: String = "0",
    val justificatif: Boolean = false,
    @SerialName("justificatif_nom") val nomJustificatif: String = "",
) {
    /** Un « autre justificatif » n'a pas de montant : la photo est tout. */
    val sansMontant: Boolean get() = nature == "AUTRE"
}

@Serializable
data class LigneReleve(
    val id: String,
    @SerialName("crise_nom") val activite: String = "",
    val crise: String? = null,
    val manifestation: String? = null,
    @SerialName("equipe") val equipeId: String? = null,
    @SerialName("equipe_nom") val equipe: String = "",
    @SerialName("depart_de") val departDe: String = "DOMICILE",
    @SerialName("retour_a") val retourA: String = "",
    @SerialName("vehicule") val typeVehicule: String = "AUCUN",
    @SerialName("vehicule_personnel") val vehiculePersonnel: String? = null,
    @SerialName("compteur_depart") val compteurDepart: String = "",
    @SerialName("compteur_arrivee") val compteurArrivee: String = "",
    val source: String = "DECLARE",
    @SerialName("parti_le") val partiLe: String = "",
    @SerialName("rentre_le") val rentreLe: String? = null,
    val heures: Double? = null,
    val kilometres: String = "",
    @SerialName("vehicule_designation") val vehicule: String = "",
    @SerialName("lieu_depart") val lieuDepart: String = "",
    @SerialName("lieu_arrivee") val lieuArrivee: String = "",
    val motif: String = "",
    @SerialName("aller_retour") val allerRetour: Boolean = true,
    val validee: Boolean = false,
    @SerialName("remarque_chef") val remarque: String = "",
    @SerialName("saisie_manuelle") val aLaMain: Boolean = false,
    val frais: List<FraisLigne> = emptyList(),
) {
    /** « Domicile → Floirac (A/R) », vide si rien n'est dit. */
    val trajet: String get() = if (lieuDepart.isBlank() && lieuArrivee.isBlank()) "" else
        "${lieuDepart.ifBlank { "?" }} → ${lieuArrivee.ifBlank { "?" }}" + if (allerRetour) " (A/R)" else ""

    val etat: EtatLigne get() = when {
        rentreLe == null -> EtatLigne.EN_COURS
        validee -> EtatLigne.VALIDEE
        remarque.isNotBlank() -> EtatLigne.A_REVOIR
        else -> EtatLigne.EN_ATTENTE
    }

    /** Péages et stationnement de la ligne, en euros. */
    val totalFrais: Double get() = frais.filter { !it.sansMontant }.sumOf { it.montant.replace(",", ".").toDoubleOrNull() ?: 0.0 }

    /** Une ligne validée ne se modifie plus, et une sortie pas terminée n'a pas encore de justificatif. */
    val accepteJustificatif: Boolean get() = !validee && rentreLe != null

    /** Se corrige tant qu'elle n'est pas validée (le retour oublié compris). */
    val corrigeable: Boolean get() = !validee

    /** Se retire seulement si on l'a ajoutée à la main : une déclaration du moment se corrige. */
    val retirable: Boolean get() = !validee && aLaMain

    /** La cible au format du formulaire : « c:<crise> » ou « m:<manifestation> ». */
    val cible: String get() = manifestation?.let { "m:$it" } ?: "c:${crise.orEmpty()}"
}

enum class EtatLigne(val libelle: String) {
    EN_COURS("en cours"), EN_ATTENTE("en attente de validation"), A_REVOIR("à revoir"), VALIDEE("validée")
}

@Serializable
data class AbandonReleve(
    val id: String,
    val statut: String = "",
    @SerialName("statut_libelle") val libelle: String = "",
    @SerialName("numero_recu") val numeroRecu: String = "",
    @SerialName("motif_refus") val motifRefus: String = "",
    val montant: String? = null,
) {
    val recuDisponible: Boolean get() = statut == "RECU_EMIS"
    /** On peut (re)demander tant que rien n'a été accepté. */
    val renouvelable: Boolean get() = statut == "REFUSE" || statut == "DEMANDE"
}

@Serializable
data class AssociationReleve(
    val institution: String,
    val nom: String,
    val annee: Int = 0,
    @SerialName("recus_fiscaux") val recusFiscaux: Boolean = false,
    val kilometres: Double = 0.0,
    val montant: String = "0.00",
    val abandon: AbandonReleve? = null,
) {
    /** Renoncer au remboursement (reçu fiscal) : l'association le permet, il y a des frais, et
     * rien n'est encore accepté. */
    val renonciationPossible: Boolean get() =
        recusFiscaux && (montant.replace(",", ".").toDoubleOrNull() ?: 0.0) > 0 && (abandon == null || abandon.renouvelable)
}

@Serializable
data class Choix(val id: String = "", val nom: String = "", val code: String = "", val libelle: String = "", val debut: String = "")

@Serializable
data class ActiviteReleve(
    val quand: String,
    val heure: Boolean = false,
    val source: String = "moi",
    val equipe: String = "",
    val quoi: String = "",
)

@Serializable
data class MonReleve(
    val du: String,
    val au: String,
    val lignes: List<LigneReleve> = emptyList(),
    @SerialName("total_heures") val totalHeures: Double = 0.0,
    @SerialName("total_kilometres") val totalKilometres: Double = 0.0,
    val frais: List<AssociationReleve> = emptyList(),
    /** De quoi compléter un oubli : crises, manifestations, équipes, lieux, types de véhicule. */
    val crises: List<Choix> = emptyList(),
    val manifestations: List<Choix> = emptyList(),
    val equipes: List<Choix> = emptyList(),
    val lieux: List<Choix> = emptyList(),
    @SerialName("mes_vehicules") val mesVehicules: List<VehiculePersonnel> = emptyList(),
    /** Ce que la personne et ses équipes ont fait, pour retrouver ses heures. */
    val activite: List<ActiviteReleve> = emptyList(),
    /** Elle encadre une équipe, ou relit pour son bureau ou sa mairie : onglet « À valider ». */
    val encadre: Boolean = false,
) {
    val peutAjouter: Boolean get() = crises.isNotEmpty() || manifestations.isNotEmpty()
}

/** Le relevé d'une personne, tel que l'encadrement le relit (`releves-equipe/`). */
@Serializable
data class FicheEquipe(
    val personne: String,
    val lignes: List<LigneReleve> = emptyList(),
    @SerialName("total_heures") val totalHeures: Double = 0.0,
    @SerialName("heures_validees") val heuresValidees: Double = 0.0,
    @SerialName("a_valider") val aValider: Int = 0,
)

@Serializable
data class RelevesEquipe(val du: String = "", val au: String = "", val fiches: List<FicheEquipe> = emptyList()) {
    val aValider: Int get() = fiches.sumOf { it.aValider }
}

/**
 * Une sortie en cours de saisie, dans l'application (28/11/2026) : ajout d'un oubli ou
 * correction. Les instants sont déjà en ISO 8601 avec leur décalage (l'heure du téléphone).
 * `champs()` donne le corps de `mon-releve/` (POST) ou `mon-releve/<id>/` (PATCH).
 */
data class BrouillonSortie(
    val id: String? = null,
    val cible: String = "",
    val equipe: String = "",
    val partiLe: String = "",
    val rentreLe: String = "",
    val departDe: String = "DOMICILE",
    val retourA: String = "DOMICILE",
    val vehiculePersonnel: String = "",
    val typeVehicule: String = "AUCUN",
    val lieuDepart: String = "",
    val lieuArrivee: String = "",
    val motif: String = "",
    val allerRetour: Boolean = true,
    val compteurDepart: String = "",
    val compteurArrivee: String = "",
    val kilometres: String = "",
) {
    val kmDesCompteurs: Int? get() = ReleveKm.kmCompteurs(compteurDepart, compteurArrivee)

    /** Ce qui manque encore, en clair, ou null. */
    fun manque(): String? = when {
        id == null && cible.length < 3 -> "Choisissez la crise ou la manifestation."
        partiLe.isBlank() || rentreLe.isBlank() -> "Indiquez le départ et le retour."
        else -> null                     // l'ordre des heures, le recouvrement : le serveur le dit
    }

    /** `origine` : la ligne telle qu'elle était, pour une correction. Les heures et les lieux de
     * départ ou de retour inchangés ne partent pas : le serveur marquerait sinon les heures
     * « complétées à la main » alors qu'on n'a touché qu'au trajet. */
    fun champs(origine: BrouillonSortie? = null): Map<String, Any?> = buildMap {
        if (id == null) {
            if (cible.startsWith("m:")) put("manifestation", cible.drop(2))
            else { put("crise", cible.drop(2)); put("equipe", equipe.ifBlank { null }) }
        }
        if (origine == null || partiLe != origine.partiLe) put("parti_le", partiLe)
        if (origine == null || rentreLe != origine.rentreLe) put("rentre_le", rentreLe)
        if (origine == null || departDe != origine.departDe) put("depart_de", departDe)
        if (origine == null || retourA != origine.retourA) put("retour_a", retourA)
        put("vehicule_personnel", vehiculePersonnel)
        put("vehicule", if (vehiculePersonnel.isBlank()) typeVehicule else null)
        put("lieu_depart", lieuDepart.trim()); put("lieu_arrivee", lieuArrivee.trim()); put("motif", motif.trim())
        put("aller_retour", allerRetour)
        put("compteur_depart", compteurDepart.filter { it.isDigit() })
        put("compteur_arrivee", compteurArrivee.filter { it.isDigit() })
        put("kilometres", kmDesCompteurs?.toString() ?: kilometres.trim())
    }

    companion object {
        fun depuis(l: LigneReleve) = BrouillonSortie(
            id = l.id, cible = l.cible, equipe = l.equipeId.orEmpty(), partiLe = l.partiLe, rentreLe = l.rentreLe.orEmpty(),
            departDe = l.departDe, retourA = l.retourA.ifBlank { l.departDe }, vehiculePersonnel = l.vehiculePersonnel.orEmpty(),
            typeVehicule = l.typeVehicule, lieuDepart = l.lieuDepart, lieuArrivee = l.lieuArrivee, motif = l.motif,
            allerRetour = l.allerRetour, compteurDepart = l.compteurDepart, compteurArrivee = l.compteurArrivee, kilometres = l.kilometres,
        )
    }
}
