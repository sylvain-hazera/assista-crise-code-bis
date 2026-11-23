package fr.assistacrise.mobile.donnees

import fr.assistacrise.mobile.domaine.Alerte
import fr.assistacrise.mobile.domaine.Etape
import fr.assistacrise.mobile.domaine.alertesNouvelles
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.SetSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * Ce qui doit faire sonner le téléphone. Un seul relevé pour les trois sources : les
 * notifications du serveur (une campagne), les messages d'équipe, les missions nouvelles.
 *
 * Le même code tourne application ouverte et application fermée (tâche de fond) : il n'y a
 * donc qu'une mémoire de « ce qui a déjà sonné », sur disque, et une chose ne sonne jamais
 * deux fois parce qu'on a rouvert l'application entre-temps.
 */
class Veille(
    private val magasin: Magasin,
    private val notifications: DepotNotifications,
    private val equipes: DepotEquipes,
    private val missions: DepotMissions,
    /** Les dossiers confiés à mes équipes, relus si demandé (23/11/2026) : un dossier nouvellement
     * confié sonne, comme une mission. */
    private val dossiersAFaire: suspend (relire: Boolean) -> List<fr.assistacrise.mobile.domaine.Dossier> = { emptyList() },
) {
    private val json = Json
    private val verrou = Mutex()

    /**
     * Relit le serveur et rend ce qui est nouveau. `afficher` reçoit chaque alerte et dit si
     * le système a bien accepté de la montrer : c'est seulement alors qu'une notification du
     * serveur est accusée « remise » — on n'affirme pas avoir prévenu quelqu'un sans l'avoir fait.
     *
     * @return `null` si le serveur n'a pas répondu.
     */
    suspend fun relever(relire: Boolean = true, afficher: suspend (Alerte) -> Boolean): List<Alerte>? = verrou.withLock {
        if (notifications.rafraichir() is Reponse.Injoignable) return@withLock null
        // `relire = false` : l'appelant vient de relire missions et équipes, inutile de le refaire.
        if (relire) { missions.rafraichir(); equipes.rafraichir() }
        equipes.equipes.value.forEach { equipes.rafraichirFil(it.id) }
        val dossiers = runCatching { dossiersAFaire(true) }.getOrDefault(emptyList())

        val presentes = presentes() + dossiers.map {
            Alerte("do:${it.id}", Alerte.Genre.DOSSIER, "Dossier confié à ${it.equipeNom ?: "votre équipe"}",
                   listOfNotNull(it.titre.ifBlank { null }, it.commune).joinToString(" · ").ifBlank { "Nouveau dossier" },
                   urgent = it.priorite == "URGENTE", cible = it.id)
        }
        val dejaVues = magasin.lire(FICHIER)?.let { runCatching { json.decodeFromString(FORME, it) }.getOrNull() }
        val nouvelles = alertesNouvelles(presentes, dejaVues)

        val remises = mutableListOf<String>()
        val sonnees = mutableSetOf<String>()
        for (alerte in nouvelles) {
            if (!afficher(alerte)) continue
            sonnees += alerte.cle
            if (alerte.genre == Alerte.Genre.NOTIFICATION) remises += alerte.cible
        }
        // On ne retient que ce qui existe encore : la mémoire ne grossit pas sans fin. Une
        // alerte que le système a refusé d'afficher n'est PAS retenue : elle sera retentée.
        val retenues = if (dejaVues == null) presentes.map { it.cle }.toSet()
        else presentes.map { it.cle }.filter { it in dejaVues || it in sonnees }.toSet()
        magasin.ecrire(FICHIER, json.encodeToString(FORME, retenues))
        if (remises.isNotEmpty()) notifications.noter(Etape.REMISE, remises)
        nouvelles.filter { it.cle in sonnees }
    }

    suspend fun toutEffacer() = magasin.effacer(FICHIER)

    private fun presentes(): List<Alerte> {
        val parEquipe = equipes.equipes.value.associateBy { it.id }
        return notifications.notifications.value
            // Déjà remise par un autre téléphone, ou déjà traitée : inutile de la refaire sonner.
            .filter { it.dateVue == null && it.dateReponse == null }
            .map { Alerte("n:${it.id}", Alerte.Genre.NOTIFICATION, it.titre, it.institutionNom ?: "", it.urgent, it.id) } +
            equipes.fils.value.flatMap { (idEquipe, fil) ->
                // Ni mes propres messages, ni ceux que ma radio a entendus : je les ai déjà.
                fil.filter { !it.moi && !it.id.startsWith(fr.assistacrise.mobile.domaine.MessageEquipe.PREFIXE_RADIO_LOCALE) }.takeLast(MESSAGES_PAR_EQUIPE).map {
                    Alerte("m:$idEquipe:${it.id}", Alerte.Genre.MESSAGE, parEquipe[idEquipe]?.nom ?: "Mon équipe", "${it.auteur} : ${it.texte}".take(160), it.urgent, idEquipe)
                }
            } +
            missions.missions.value.map {
                Alerte("mi:${it.id}", Alerte.Genre.MISSION, "Nouvelle mission", it.titre, cible = it.id)
            }
    }

    private companion object {
        const val FICHIER = "veille"
        /** Au retour d'une longue coupure, on ne fait pas sonner cinquante messages d'affilée. */
        const val MESSAGES_PAR_EQUIPE = 5
        val FORME = SetSerializer(String.serializer())
    }
}
