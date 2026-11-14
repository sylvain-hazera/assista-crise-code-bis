package fr.assistacrise.mobile.domaine

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Une crise, vue par quelqu'un qui veut y déposer quelque chose (`CrisisSerializer`, réduit). */
@Serializable
data class Crise(
    val id: String,
    @SerialName("name") val nom: String = "",
    val type: String = "AUTRE",
    val description: String? = null,
    @SerialName("is_open") val ouverte: Boolean = true,
    @SerialName("has_responsable_actif") val suivie: Boolean = false,
) {
    /** Le serveur refuse tout dépôt sur une crise close ou sans responsable désigné. */
    val accepteLesDepots: Boolean get() = ouverte && suivie

    val typeLibelle: String
        get() = when (type) {
            "INCENDIE" -> "Incendie"
            "INONDATION" -> "Inondation"
            "ACCIDENT" -> "Accident"
            "CATASTROPHE_NATURELLE" -> "Catastrophe naturelle"
            else -> "Crise"
        }
}

/** Un type de demande ou d'information, tel que le serveur le propose. */
@Serializable
data class TypeDepot(
    val id: String,
    @SerialName("type") val libelle: String? = null,
    /** Les types forment un arbre (« Matériel » → « Bulldozer à lame »). `null` = racine. */
    val parent: String? = null,
)

/** Une information publiée sur une crise. */
@Serializable
data class Information(
    val id: String,
    @SerialName("title") val titre: String = "",
    @SerialName("crisis") val crise: String? = null,
    @SerialName("created_at") val creeLe: String? = null,
)

/** Miroir de `DeclarationSecurite.situation`. */
enum class Situation(val libelle: String) {
    RELOGE("En sécurité / relogé"),
    EN_CENTRE("En centre d'accueil"),
    BESOIN_CENTRE("En sécurité, cherche un centre d'accueil"),
    HORS_ZONE("En sécurité, hors zone"),
}

/** Miroir de `DeclarationSecurite.type_declarant`. */
enum class Declarant(val libelle: String) {
    PERSONNE_SEULE("Personne seule"),
    FAMILLE("Famille"),
    GROUPE("Groupe"),
}

/** Qui dépose : repris du compte, corrigeable dans le formulaire. */
data class Deposant(val prenom: String = "", val nom: String = "", val email: String = "", val telephone: String = "")

/** Les trois gestes du mode citoyen. Une seule saisie, que l'écran remplit selon `genre`. */
enum class GenreDepot(val titre: String, val chemin: String) {
    SECURITE("Je suis en sécurité", "declarations-securite/"),
    DEMANDE("Demander de l'aide", "demandes/"),
    SIGNALEMENT("Signaler", "informations/"),
}

data class Depot(
    val genre: GenreDepot,
    val crise: Crise,
    val deposant: Deposant,
    val titre: String = "",
    val description: String = "",
    val type: TypeDepot? = null,
    val situation: Situation = Situation.RELOGE,
    val declarant: Declarant = Declarant.PERSONNE_SEULE,
    val adultes: Int = 1,
    val enfants: Int = 0,
    /** Lue au moment du geste, jamais avant ni après (dossier § 13). */
    val position: Releve? = null,
)

object ChampsDepot {
    const val PRENOM = "prenom"
    const val NOM = "nom"
    const val EMAIL = "email"
    const val TELEPHONE = "telephone"
    const val TITRE = "titre"
    const val TYPE = "type"
    const val POSITION = "position"
    const val PERSONNES = "personnes"
}

private val EMAIL_DEPOT = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]{2,}$")

/** Erreurs de saisie d'un dépôt, par champ. Vide = recevable. Le serveur revérifie tout. */
fun validerDepot(d: Depot): Map<String, String> = buildMap {
    if (d.deposant.prenom.isBlank()) put(ChampsDepot.PRENOM, "Indiquez votre prénom.")
    if (d.deposant.nom.isBlank()) put(ChampsDepot.NOM, "Indiquez votre nom.")
    if (d.deposant.telephone.isBlank()) put(ChampsDepot.TELEPHONE, "Indiquez un numéro où vous joindre.")
    when (d.genre) {
        GenreDepot.SECURITE -> {
            if (d.adultes + d.enfants < 1) put(ChampsDepot.PERSONNES, "Indiquez au moins une personne.")
        }
        GenreDepot.DEMANDE, GenreDepot.SIGNALEMENT -> {
            if (!EMAIL_DEPOT.matches(d.deposant.email.trim())) put(ChampsDepot.EMAIL, "Cette adresse e-mail n'est pas valide.")
            if (d.titre.trim().length < 3) put(ChampsDepot.TITRE, "Dites en quelques mots de quoi il s'agit.")
            if (d.type == null) put(ChampsDepot.TYPE, "Choisissez un type.")
            // Un signalement sans lieu ne sert à personne ; une demande peut s'en passer.
            if (d.genre == GenreDepot.SIGNALEMENT && d.position == null) {
                put(ChampsDepot.POSITION, "Un signalement doit être situé : autorisez la position.")
            }
        }
    }
}
