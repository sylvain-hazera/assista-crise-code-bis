package fr.assistacrise.mobile.domaine

/**
 * Ce qu'une personne saisit pour créer son compte depuis l'application.
 *
 * Seul le compte de particulier (`UTIL_SIMPLE`) se crée ici. Les comptes de mairie ou de
 * secours demandent de prouver une institution (domaine de l'adresse, annuaire officiel,
 * validation) : ce parcours reste sur le site.
 */
data class Inscription(
    val prenom: String = "",
    val nom: String = "",
    val email: String = "",
    val telephone: String = "",
    val codePostal: String = "",
    val motDePasse: String = "",
    val rejoindreLaReserve: Boolean = true,
    val conditionsAcceptees: Boolean = false,
)

/** Les quatre exigences du mot de passe, séparées pour que l'écran les coche une à une. */
data class ForceMotDePasse(
    val longueur: Boolean,
    val majuscule: Boolean,
    val minuscule: Boolean,
    val chiffre: Boolean,
    val special: Boolean,
) {
    val suffisante: Boolean get() = longueur && majuscule && minuscule && chiffre && special

    companion object {
        /** Mêmes règles que le formulaire du site (`passwordStrengthValidator`). */
        const val SPECIAUX = "!@#\$%^&*(),.?\":{}|<>"

        fun de(motDePasse: String) = ForceMotDePasse(
            longueur = motDePasse.length >= 8,
            majuscule = motDePasse.any { it in 'A'..'Z' },
            minuscule = motDePasse.any { it in 'a'..'z' },
            chiffre = motDePasse.any { it in '0'..'9' },
            special = motDePasse.any { it in SPECIAUX },
        )
    }
}

object Champs {
    const val PRENOM = "first_name"
    const val NOM = "last_name"
    const val EMAIL = "email"
    const val TELEPHONE = "phone_number"
    const val CODE_POSTAL = "postal_code"
    const val MOT_DE_PASSE = "password"
    const val CONDITIONS = "conditions"
}

private val EMAIL = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]{2,}$")
private val TELEPHONE_FR = Regex("^(?:(?:\\+|00)33|0)\\s*[1-9](?:[\\s.-]*\\d{2}){4}$")
private val CODE_POSTAL = Regex("^\\d{5}$")

/**
 * Erreurs de saisie, par nom de champ de l'API — les mêmes clés que celles que le serveur
 * renvoie, pour que l'écran n'ait qu'une façon d'afficher une erreur. Vide = recevable.
 *
 * Le serveur revérifie tout : ceci épargne un aller-retour, ça ne remplace rien.
 */
fun validerInscription(i: Inscription): Map<String, String> = buildMap {
    if (i.prenom.trim().length < 2) put(Champs.PRENOM, "Indiquez votre prénom.")
    if (i.nom.trim().length < 2) put(Champs.NOM, "Indiquez votre nom.")
    if (!EMAIL.matches(i.email.trim())) put(Champs.EMAIL, "Cette adresse e-mail n'est pas valide.")
    if (!TELEPHONE_FR.matches(i.telephone.trim())) put(Champs.TELEPHONE, "Indiquez un numéro français, par exemple 06 12 34 56 78.")
    if (!CODE_POSTAL.matches(i.codePostal.trim())) put(Champs.CODE_POSTAL, "Le code postal a cinq chiffres.")
    if (!ForceMotDePasse.de(i.motDePasse).suffisante) put(Champs.MOT_DE_PASSE, "Le mot de passe ne remplit pas toutes les conditions.")
    if (!i.conditionsAcceptees) put(Champs.CONDITIONS, "Vous devez accepter les conditions d'utilisation.")
}
