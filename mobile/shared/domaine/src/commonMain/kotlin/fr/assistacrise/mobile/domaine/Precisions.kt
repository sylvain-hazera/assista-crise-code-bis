package fr.assistacrise.mobile.domaine

/**
 * Les précisions qu'un type de demande ou d'offre appelle : un hébergement se décrit par sa
 * capacité, un transport par ses places. Ce sont les champs du formulaire du site
 * (`propose-help-form`, `request-help-form`), décrits ici comme des données plutôt que codés
 * écran par écran : un champ ajouté au site s'ajoute en une ligne, et la liste se teste.
 *
 * `cle` est le nom du champ dans l'API. `si` : le champ n'apparaît (et ne part) que si un
 * autre champ a cette valeur — « accès à l'étage » n'a de sens que pour un logement en étage.
 */
sealed class Precision {
    abstract val cle: String
    abstract val libelle: String
    abstract val si: Pair<String, String>?

    data class Nombre(override val cle: String, override val libelle: String, override val si: Pair<String, String>? = null) : Precision()
    data class Texte(override val cle: String, override val libelle: String, override val si: Pair<String, String>? = null) : Precision()
    data class OuiNon(override val cle: String, override val libelle: String, val defaut: Boolean = false, override val si: Pair<String, String>? = null) : Precision()
    data class Choix(override val cle: String, override val libelle: String, val options: List<Pair<String, String>>, override val si: Pair<String, String>? = null) : Precision()
}

object Precisions {
    private val DUREE = Precision.Choix("hebergement_duree", "Durée", listOf("TEMPORAIRE" to "Temporaire", "LONGUE_DUREE" to "Longue durée"))
    private val LOYER = Precision.Choix("type_loyer", "Loyer", listOf("GRATUIT" to "Gratuit", "NEGOCIE" to "Négocié", "MARCHE" to "Prix du marché"))
    private val LOGEMENT = Precision.Choix("type_logement", "Logement", listOf("MAISON" to "Maison", "APPARTEMENT" to "Appartement", "STUDIO" to "Studio", "COLOCATION" to "Colocation", "CHAMBRE" to "Chambre"))
    private val NIVEAU = Precision.Choix("niveau_logement", "Niveau", listOf("PLAIN_PIED" to "Plain-pied", "ETAGE" to "Étage"))
    private val ACCES = Precision.Choix("acces_etage", "Accès à l'étage", listOf("ESCALIER" to "Escalier", "ASCENSEUR" to "Ascenseur"), si = "niveau_logement" to "ETAGE")

    /** Ce qui décrit un logement, qu'on l'offre ou qu'on le cherche. */
    private val HEBERGEMENT = listOf(
        DUREE, LOYER,
        Precision.Nombre("loyer_montant_min", "Loyer minimum (€)", si = "type_loyer" to "NEGOCIE"),
        Precision.Nombre("loyer_montant_max", "Loyer maximum (€)", si = "type_loyer" to "NEGOCIE"),
        LOGEMENT, NIVEAU, ACCES,
        Precision.Nombre("nombre_pieces", "Pièces"), Precision.Nombre("nombre_chambres", "Chambres"),
        Precision.Nombre("capacite_adultes", "Adultes"), Precision.Nombre("capacite_enfants", "Enfants"),
        Precision.OuiNon("animaux_acceptes", "Animaux acceptés"), Precision.OuiNon("jardin", "Jardin"),
        Precision.OuiNon("pmr_compatible", "Accessible en fauteuil roulant"),
    )

    private val OFFRE = mapOf(
        "hébergement" to HEBERGEMENT + listOf(
            Precision.OuiNon("accueil_sinistres", "J'accueille des sinistrés", defaut = true),
            Precision.OuiNon("accueil_intervenants", "J'accueille des intervenants"),
        ),
        "soins médicaux et paramédicaux" to listOf(Precision.Texte("numero_adeli_rpps", "Numéro ADELI ou RPPS")),
        "transport" to listOf(
            Precision.Choix("transport_type", "Que transportez-vous ?", listOf("PERSONNES" to "Des personnes", "MATERIEL" to "Du matériel", "ANIMAUX" to "Des animaux")),
            Precision.Nombre("nombre_places_assises", "Places assises", si = "transport_type" to "PERSONNES"),
            Precision.Texte("transport_animaux_precision", "Quels animaux ?", si = "transport_type" to "ANIMAUX"),
            Precision.Texte("immatriculation", "Immatriculation"),
            Precision.OuiNon("confirmation_reglementaire", "Véhicule assuré et en règle"),
        ),
        "matériel" to listOf(
            Precision.Choix("materiel_type", "Matériel", listOf("CUVE" to "Cuve", "POMPE" to "Pompe", "ETUVE" to "Étuve", "CHAMBRE_FROIDE" to "Chambre froide", "REMORQUE" to "Remorque", "AUTRE" to "Autre")),
            Precision.Choix("cuve_contenu", "Contenu de la cuve", listOf("EAU" to "Eau", "CARBURANT" to "Carburant"), si = "materiel_type" to "CUVE"),
            Precision.Nombre("quantite", "Quantité"), Precision.Texte("unite", "Unité (litres, pièces…)"),
            Precision.Choix("materiel_livraison", "Remise", listOf("A_RECUPERER" to "À récupérer sur place", "LIVRAISON_POSSIBLE" to "Je peux le déposer")),
        ),
        "soutien psychologique" to listOf(
            Precision.Choix("soutien_type", "Vous êtes", listOf("PROFESSIONNEL" to "Professionnel de santé", "SECOURISTE" to "Secouriste")),
        ),
        "bénévolat" to listOf(
            Precision.OuiNon("diplome_secourisme", "J'ai un diplôme de secourisme"),
            Precision.OuiNon("ancien_sapeur_pompier", "Ancien sapeur-pompier"),
            Precision.OuiNon("accompagne", "Je viens accompagné"),
            Precision.Nombre("nombre_accompagnants", "Combien de personnes avec vous ?", si = "accompagne" to "true"),
        ),
    )

    /** Valables pour toute offre, quel qu'en soit le type. */
    private val TOUTE_OFFRE = listOf(
        Precision.OuiNon("renouvelable", "Je pourrai le refaire"),
        Precision.Texte("organisation_nom", "Au nom d'une organisation (facultatif)"),
    )

    /**
     * @param famille le libellé du type racine choisi (« Hébergement »), tel que le serveur le
     * donne : le site reconnaît lui aussi les types par leur libellé.
     */
    fun pour(genre: GenreDepot, famille: String?): List<Precision> {
        val cle = famille?.trim()?.lowercase()
        return when (genre) {
            GenreDepot.OFFRE -> OFFRE[cle].orEmpty() + TOUTE_OFFRE
            GenreDepot.DEMANDE -> if (cle == "hébergement") HEBERGEMENT + Precision.Nombre("zone_recherche_rayon_km", "Dans un rayon de (km)") else emptyList()
            else -> emptyList()
        }
    }

    /** Les champs à montrer compte tenu de ce qui est déjà saisi. */
    fun visibles(champs: List<Precision>, saisie: Map<String, String>): List<Precision> =
        champs.filter { c -> c.si?.let { (cle, valeur) -> valeurDe(champs, saisie, cle) == valeur || (cle == "type_loyer" && valeurDe(champs, saisie, cle) == "MARCHE") } ?: true }

    /**
     * Ce qui part au serveur : seulement les champs visibles et renseignés. Un « oui/non » part
     * toujours — « non » est une information, pas une absence.
     */
    fun aEnvoyer(champs: List<Precision>, saisie: Map<String, String>): Map<String, String> =
        visibles(champs, saisie).mapNotNull { c ->
            when (c) {
                is Precision.OuiNon -> c.cle to (saisie[c.cle] ?: c.defaut.toString())
                is Precision.Nombre -> saisie[c.cle]?.trim()?.toIntOrNull()?.let { c.cle to it.toString() }
                else -> saisie[c.cle]?.trim()?.takeIf { it.isNotEmpty() }?.let { c.cle to it }
            }
        }.toMap()

    private fun valeurDe(champs: List<Precision>, saisie: Map<String, String>, cle: String): String? =
        saisie[cle] ?: (champs.firstOrNull { it.cle == cle } as? Precision.OuiNon)?.defaut?.toString()
}
