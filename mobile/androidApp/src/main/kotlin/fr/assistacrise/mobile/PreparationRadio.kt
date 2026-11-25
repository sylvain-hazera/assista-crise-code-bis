package fr.assistacrise.mobile

import fr.assistacrise.mobile.domaine.ActionRestauration
import fr.assistacrise.mobile.domaine.CanalComplet
import fr.assistacrise.mobile.domaine.PlanUrgence
import fr.assistacrise.mobile.domaine.PlanUrgenceServeur
import fr.assistacrise.mobile.domaine.Proposition
import fr.assistacrise.mobile.domaine.SauvegardeRadio
import fr.assistacrise.mobile.donnees.Magasin
import fr.assistacrise.mobile.lien.PiloteMeshCore
import fr.assistacrise.mobile.lien.PiloteMeshtastic
import fr.assistacrise.mobile.lien.PiloteRadio
import fr.assistacrise.mobile.lien.Protocole
import fr.assistacrise.mobile.lien.meshcore.AdminMeshCore
import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.AdminMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.CanalMeshtastic
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Préparer la radio d'un intervenant, et la remettre comme avant (25/11/2026). Les canaux
 * d'urgence vont en 5 (crise), 6 (équipe), 7 (commune) — Meshtastic — ou dans les trois derniers
 * emplacements MeshCore ; ce qu'ils remplacent est sauvegardé, chiffré, sur le téléphone
 * seulement (`MagasinChiffre` : la sauvegarde contient les clés des canaux de la structure),
 * les trois dernières par radio. Rien n'est écrit sans validation de l'intervenant.
 */
class PreparationRadio(private val magasin: Magasin) {
    private val verrou = Mutex()
    private val json = Json { ignoreUnknownKeys = true }

    fun total(pilote: PiloteRadio) = if (pilote is PiloteMeshCore) MeshCore.EMPLACEMENTS else 8

    fun identite(pilote: PiloteRadio): String? = when (pilote) {
        is PiloteMeshtastic -> pilote.avance.monNoeud?.toString(16)
        is PiloteMeshCore -> pilote.avance.moi?.pubkeyHex?.take(16)
        else -> null
    }

    /** La table complète des canaux de la radio, clés comprises. */
    fun table(pilote: PiloteRadio): List<CanalComplet> = when (pilote) {
        is PiloteMeshtastic -> pilote.avance.canauxMeshtastic.values.map {
            CanalComplet(it.index, it.nom, it.psk.toHex(), actif = it.role != 0)
        }
        is PiloteMeshCore -> pilote.avance.canauxMeshCore.values.map {
            CanalComplet(it.index, it.nom, it.secret.toHex(), actif = it.nom.isNotBlank())
        }
        else -> emptyList()
    }.sortedBy { it.index }

    private fun cle(protocole: Protocole, radio: String) = "sauvegarde-radio-${protocole.name}-$radio"

    suspend fun sauvegardes(protocole: Protocole, radio: String): List<SauvegardeRadio> =
        magasin.lire(cle(protocole, radio))?.let { runCatching { json.decodeFromString(ListSerializer(SauvegardeRadio.serializer()), it) }.getOrNull() }
            ?: emptyList()

    private suspend fun garder(s: SauvegardeRadio, protocole: Protocole) {
        val liste = (listOf(s) + sauvegardes(protocole, s.radio)).take(3)
        magasin.ecrire(cle(protocole, s.radio), json.encodeToString(ListSerializer(SauvegardeRadio.serializer()), liste))
    }

    /** Relit la radio : sa table de canaux à jour (Meshtastic répond à la relecture). */
    suspend fun relire(liaison: LiaisonRadio) { liaison.relireAvance(); delay(2_500) }

    /**
     * Écrit les canaux proposés. `sauvegarder` : faux pour un nœud dédié d'équipe (rien à
     * restaurer). Rend un message pour l'écran.
     */
    suspend fun appliquer(liaison: LiaisonRadio, plan: PlanUrgenceServeur, propositions: List<Proposition>,
                          sauvegarder: Boolean = true): String = verrou.withLock {
        val pilote = liaison.piloteCourant?.takeIf { it.prete } ?: return "Radio non connectée."
        PlanUrgence.erreur(propositions, total(pilote))?.let { return it }
        val aEcrire = PlanUrgence.aEcrire(propositions)
        if (aEcrire.isEmpty()) return "Rien à écrire : les canaux d'urgence sont déjà sur la radio."
        val radio = identite(pilote) ?: return "La radio ne s'est pas encore décrite : réessayez dans un instant."
        if (sauvegarder) {
            garder(SauvegardeRadio(
                radio = radio, protocole = pilote.protocole.name, date = System.currentTimeMillis(),
                equipe = plan.equipe, crise = plan.crise, table = table(pilote),
                ecrits = aEcrire.map { (i, e) -> CanalComplet(i, e.nom, e.cleHex) },
                roles = aEcrire.associate { (i, e) -> i to e.role }), pilote.protocole)
        }
        val ok = when (pilote) {
            is PiloteMeshtastic -> liaison.envoyerAdmin(pilote.adminGroupe(aEcrire.map { (i, e) ->
                AdminMeshtastic.ecrireCanal(CanalMeshtastic(i, e.nom, role = 2, psk = e.cleHex.hexEnOctets())) }))
            is PiloteMeshCore -> aEcrire.all { (i, e) ->
                liaison.envoyerAdmin(listOf(AdminMeshCore.ecrireCanal(i, e.nom, e.cleHex.hexEnOctets()), MeshCore.demanderCanal(i))) }
            else -> false
        }
        delay(1_500); liaison.relireAvance()
        if (!ok) return "La radio n'a pas pris toutes les écritures : vérifiez la liaison, puis recommencez."
        buildString {
            append("${aEcrire.size} canal(aux) d'urgence écrit(s) sur la radio ${pilote.protocole.libelle}")
            append(if (sauvegarder) ". Ce qu'ils remplacent est sauvegardé sur ce téléphone." else ".")
        }
    }

    /** Ce que la restauration ferait, pour l'écran de confirmation. */
    suspend fun projetRestauration(liaison: LiaisonRadio, garderEquipe: Boolean): Pair<SauvegardeRadio, List<ActionRestauration>>? {
        val pilote = liaison.piloteCourant?.takeIf { it.prete } ?: return null
        val radio = identite(pilote) ?: return null
        val s = sauvegardes(pilote.protocole, radio).firstOrNull() ?: return null
        return s to PlanUrgence.restaurer(s, table(pilote), garderEquipe)
    }

    /** Remet la radio comme avant : les emplacements modifiés à la main depuis sont laissés. */
    suspend fun restaurer(liaison: LiaisonRadio, garderEquipe: Boolean): String = verrou.withLock {
        val pilote = liaison.piloteCourant?.takeIf { it.prete } ?: return "Radio non connectée."
        val radio = identite(pilote) ?: return "La radio ne s'est pas encore décrite : réessayez dans un instant."
        val liste = sauvegardes(pilote.protocole, radio)
        val s = liste.firstOrNull() ?: return "Aucune sauvegarde de cette radio sur ce téléphone."
        val actions = PlanUrgence.restaurer(s, table(pilote), garderEquipe)
        val faites = actions.filter { !it.modifieDepuis }
        val ok = when (pilote) {
            is PiloteMeshtastic -> faites.isEmpty() || liaison.envoyerAdmin(pilote.adminGroupe(faites.map { a ->
                val v = a.vers
                AdminMeshtastic.ecrireCanal(if (v != null) CanalMeshtastic(a.index, v.nom, role = 2, psk = v.cleHex.hexEnOctets())
                                            else CanalMeshtastic(a.index, "", role = 0)) }))
            is PiloteMeshCore -> faites.all { a ->
                val v = a.vers
                liaison.envoyerAdmin(listOf(if (v != null) AdminMeshCore.ecrireCanal(a.index, v.nom, v.cleHex.hexEnOctets())
                                            else AdminMeshCore.effacerCanal(a.index), MeshCore.demanderCanal(a.index))) }
            else -> false
        }
        delay(1_500); liaison.relireAvance()
        if (!ok) return "La radio n'a pas pris toute la restauration : la sauvegarde est gardée, recommencez."
        magasin.ecrire(cle(pilote.protocole, radio), json.encodeToString(ListSerializer(SauvegardeRadio.serializer()), liste.drop(1)))
        val laisses = actions.count { it.modifieDepuis }
        buildString {
            append("Radio remise comme avant : ${faites.size} emplacement(s) restauré(s).")
            if (laisses > 0) append(" $laisses modifié(s) à la main depuis, laissé(s) tel(s) quel(s).")
        }
    }

    private fun ByteArray.toHex() = joinToString("") { "%02x".format(it) }
    private fun String.hexEnOctets(): ByteArray = chunked(2).mapNotNull { it.toIntOrNull(16)?.toByte() }.toByteArray()
}
