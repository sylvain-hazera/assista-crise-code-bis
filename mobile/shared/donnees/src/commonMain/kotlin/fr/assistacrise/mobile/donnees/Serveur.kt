package fr.assistacrise.mobile.donnees

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/** Un satellite complet de mon institution, tel que le central le décrit (GET satellites/acces-local/). */
@Serializable
data class SatelliteConnu(
    val id: String,
    val nom: String,
    val urls: List<String> = emptyList(),
    val ips: List<String> = emptyList(),
    @SerialName("port_web") val portWeb: Int = 80,
)

/** Le satellite sur lequel l'application travaille, faute de central. */
@Serializable
data class SatelliteActif(val url: String, val nom: String)

/**
 * Le serveur auquel parle l'application (23/11/2026) : le central, ou, quand il ne répond
 * plus, le satellite du site (« si elle ne se connecte pas au central, elle détecte le
 * satellite et s'y connecte, et le cas échéant demande l'IP »).
 *
 * Une adresse de satellite n'est acceptée que si elle est **locale** : une IP privée ou un nom
 * en `.local`. C'est la seule chose qui autorise du `http://` en clair, et elle ne vaut que
 * sur le réseau du site.
 */
class Serveur(private val magasin: Magasin, val urlCentral: String) {
    private val json = Json { ignoreUnknownKeys = true }
    private val _satellite = MutableStateFlow<SatelliteActif?>(null)
    val satellite: StateFlow<SatelliteActif?> = _satellite

    /** La racine de l'API du serveur du moment, sans « / » final. */
    fun urlApi(): String = (_satellite.value?.url?.trimEnd('/') ?: urlCentral.trimEnd('/')) + "/api"

    suspend fun restaurer() {
        _satellite.value = magasin.lire(FICHIER_ACTIF)?.let { runCatching { json.decodeFromString(SatelliteActif.serializer(), it) }.getOrNull() }
            ?.takeIf { adresseLocaleValide(it.url) != null }
    }

    suspend fun utiliser(satellite: SatelliteActif?) {
        _satellite.value = satellite
        if (satellite == null) magasin.effacer(FICHIER_ACTIF)
        else magasin.ecrire(FICHIER_ACTIF, json.encodeToString(SatelliteActif.serializer(), satellite))
    }

    suspend fun retenirConnus(satellites: List<SatelliteConnu>) =
        magasin.ecrire(FICHIER_CONNUS, json.encodeToString(ListSerializer(SatelliteConnu.serializer()), satellites))

    suspend fun connus(): List<SatelliteConnu> = magasin.lire(FICHIER_CONNUS)
        ?.let { runCatching { json.decodeFromString(ListSerializer(SatelliteConnu.serializer()), it) }.getOrNull() }.orEmpty()

    suspend fun adresseSaisie(): String = magasin.lire(FICHIER_SAISIE).orEmpty()
    suspend fun retenirSaisie(saisie: String) = magasin.ecrire(FICHIER_SAISIE, saisie.trim())

    companion object {
        private const val FICHIER_ACTIF = "serveur-satellite"
        private const val FICHIER_CONNUS = "satellites-connus"
        private const val FICHIER_SAISIE = "satellite-adresse-saisie"

        private val IP = Regex("""^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(:\d{1,5})?$""")
        private val NOM_LOCAL = Regex("""^[a-z0-9][a-z0-9-]{0,62}\.local(:\d{1,5})?$""")

        /** `http://…/` si la saisie désigne une adresse locale (IP privée ou nom en .local), sinon null. */
        fun adresseLocaleValide(saisie: String): String? {
            val s = saisie.trim().removePrefix("http://").removePrefix("https://").substringBefore('/').lowercase()
            IP.matchEntire(s)?.let { m ->
                val o = (1..4).map { m.groupValues[it].toInt() }
                if (o.any { it > 255 }) return null
                val privee = o[0] == 10 || (o[0] == 192 && o[1] == 168) || (o[0] == 172 && o[1] in 16..31)
                return if (privee) "http://$s/" else null
            }
            return if (NOM_LOCAL.matches(s)) "http://$s/" else null
        }
    }
}
