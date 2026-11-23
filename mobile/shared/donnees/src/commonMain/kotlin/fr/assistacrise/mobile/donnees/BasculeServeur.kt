package fr.assistacrise.mobile.donnees

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Basculer du central vers le satellite du site, et revenir (23/11/2026).
 *
 * « Si elle ne se connecte pas au central, elle détecte le satellite et s'y connecte, et le cas
 * échéant demande l'IP du serveur satellite. »
 *
 * 1. Le central est jugé injoignable après [SEUIL_ECHECS] échecs réseau consécutifs (un seul
 *    raté n'est pas une panne).
 * 2. On cherche : les satellites annoncés en mDNS sur le Wi-Fi ([decouvrir], fourni par la
 *    plateforme), puis les adresses que le central a données quand il répondait, puis
 *    l'adresse saisie la dernière fois. Le premier qui répond à la sonde est retenu.
 * 3. Rien trouvé : [etat] passe à [Etat.ADRESSE_DEMANDEE] — l'écran demande l'IP.
 * 4. Sur le satellite, la session est celle du satellite (mêmes identifiants : il en a la
 *    copie) ; le central est resondé régulièrement, et l'on y revient dès qu'il répond.
 */
class BasculeServeur(
    private val serveur: Serveur,
    private val session: Session,
    private val sonde: suspend (String) -> Boolean,
    private val decouvrir: suspend () -> List<Pair<String, String>>,   // (url, nom)
) {
    enum class Etat { CENTRAL, RECHERCHE, ADRESSE_DEMANDEE, SATELLITE }

    private val _etat = MutableStateFlow(if (serveur.satellite.value != null) Etat.SATELLITE else Etat.CENTRAL)
    val etat: StateFlow<Etat> = _etat
    private var echecs = 0

    /** Au démarrage, une fois le serveur relu : sur le satellite si on l'avait quitté ainsi. */
    fun reprendre() {
        _etat.value = if (serveur.satellite.value != null) Etat.SATELLITE else Etat.CENTRAL
    }

    /** Chaque appel au serveur du moment : il a répondu, ou non. Rend vrai s'il faut chercher. */
    fun noter(repondu: Boolean): Boolean {
        if (_etat.value != Etat.CENTRAL) return false
        echecs = if (repondu) 0 else echecs + 1
        return echecs >= SEUIL_ECHECS
    }

    /** Cherche un satellite qui répond, et s'y connecte. Rend son nom, ou null (l'IP est alors demandée). */
    suspend fun chercherEtBasculer(): String? {
        _etat.value = Etat.RECHERCHE
        val candidats = mutableListOf<Pair<String, String>>()
        runCatching { decouvrir() }.getOrDefault(emptyList()).forEach { candidats += it }
        serveur.connus().forEach { s -> s.urls.forEach { candidats += it to s.nom } }
        Serveur.adresseLocaleValide(serveur.adresseSaisie())?.let { candidats += it to "Satellite" }
        for ((url, nom) in candidats.distinctBy { it.first }) {
            val propre = Serveur.adresseLocaleValide(url) ?: continue
            if (sonde(propre)) {
                basculer(propre, nom)
                return nom
            }
        }
        _etat.value = Etat.ADRESSE_DEMANDEE
        return null
    }

    /** L'adresse saisie à la main. Rend un message d'erreur, ou null si la bascule est faite. */
    suspend fun essayerAdresse(saisie: String): String? {
        val url = Serveur.adresseLocaleValide(saisie) ?: return "Adresse IP privée (ex. 192.168.1.20) ou nom en .local."
        if (!sonde(url)) return "Aucun satellite ne répond à cette adresse. Le téléphone est-il sur le Wi-Fi du site ?"
        serveur.retenirSaisie(saisie)
        basculer(url, "Satellite")
        return null
    }

    /** Sur le satellite : le central répond-il de nouveau ? Si oui, on y revient. */
    suspend fun verifierRetour(): Boolean {
        if (_etat.value != Etat.SATELLITE) return false
        if (!sonde(serveur.urlCentral)) return false
        revenirAuCentral()
        return true
    }

    suspend fun revenirAuCentral() {
        serveur.utiliser(null)
        session.basculerEspace(satellite = false)
        echecs = 0
        _etat.value = Etat.CENTRAL
    }

    /** À la main (écran Compte) : se connecter à un satellite en donnant son adresse. */
    fun demanderAdresse() {
        if (_etat.value == Etat.CENTRAL) _etat.value = Etat.ADRESSE_DEMANDEE
    }

    /** L'écran a renoncé à chercher (« continuer sans réseau ») : on reste sur le central. */
    fun abandonner() {
        if (_etat.value == Etat.ADRESSE_DEMANDEE || _etat.value == Etat.RECHERCHE) {
            echecs = 0
            _etat.value = Etat.CENTRAL
        }
    }

    private suspend fun basculer(url: String, nom: String) {
        serveur.utiliser(SatelliteActif(url, nom))
        session.basculerEspace(satellite = true)
        _etat.value = Etat.SATELLITE
    }

    companion object {
        const val SEUIL_ECHECS = 3
    }
}
