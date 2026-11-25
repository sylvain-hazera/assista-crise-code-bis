package fr.assistacrise.mobile

import android.content.Context
import fr.assistacrise.mobile.domaine.CanalAInstaller
import fr.assistacrise.mobile.domaine.CanauxRadioEquipe
import fr.assistacrise.mobile.domaine.PlanCanauxEquipes
import fr.assistacrise.mobile.domaine.PlanCanauxEquipes.Action
import fr.assistacrise.mobile.domaine.PlanRadio
import fr.assistacrise.mobile.lien.PiloteMeshCore
import fr.assistacrise.mobile.lien.PiloteMeshtastic
import fr.assistacrise.mobile.lien.Protocole
import fr.assistacrise.mobile.lien.meshcore.AdminMeshCore
import fr.assistacrise.mobile.lien.meshcore.MeshCore
import fr.assistacrise.mobile.lien.meshtastic.AdminMeshtastic
import fr.assistacrise.mobile.lien.meshtastic.CanalMeshtastic
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject

/**
 * Les canaux radio de mes équipes, installés d'office sur la radio du téléphone (25/11/2026).
 * Règles dans [PlanCanauxEquipes] : on n'écrase jamais un canal que la personne a mis elle-même
 * (canal ADRASEC déjà présent), on ne retire que ce que l'application a installé.
 *
 * Ce qui est gardé sur le téléphone : le réglage, et pour chaque canal installé son nom et sa
 * version (une empreinte), jamais la clé — elle ne vit que sur la radio.
 */
class CanauxEquipes(contexte: Context) {
    private val preferences = contexte.getSharedPreferences("canaux-equipes", Context.MODE_PRIVATE)
    private val verrou = Mutex()

    var automatique: Boolean
        get() = preferences.getBoolean("automatique", true)
        set(v) { preferences.edit().putBoolean("automatique", v).apply() }

    data class Bilan(val ajoutes: Int = 0, val reecrits: Int = 0, val retires: Int = 0, val sansPlace: Int = 0) {
        val rien get() = ajoutes + reecrits + retires + sansPlace == 0
        fun texte(protocole: Protocole) = buildString {
            val faits = listOfNotNull(
                ajoutes.takeIf { it > 0 }?.let { "$it canal(aux) d'équipe ajouté(s)" },
                reecrits.takeIf { it > 0 }?.let { "$it mis à jour" },
                retires.takeIf { it > 0 }?.let { "$it retiré(s)" },
            )
            if (faits.isNotEmpty()) append("Radio ${protocole.libelle} : ${faits.joinToString(", ")}.")
            if (sansPlace > 0) append(" Plus d'emplacement libre pour $sansPlace canal(aux) d'équipe : libérez-en un (Radio avancée).")
        }.trim()
    }

    private fun installes(p: Protocole): MutableMap<String, String> {
        val brut = preferences.getString("installes-${p.name}", null) ?: return mutableMapOf()
        return runCatching { JSONObject(brut).let { o -> o.keys().asSequence().associateWith { o.getString(it) }.toMutableMap() } }
            .getOrDefault(mutableMapOf())
    }

    private fun memoriser(p: Protocole, m: Map<String, String>) {
        preferences.edit().putString("installes-${p.name}", JSONObject(m as Map<*, *>).toString()).apply()
    }

    /** Met la radio de cette liaison en accord avec les canaux de mes équipes. */
    suspend fun aligner(liaison: LiaisonRadio, equipes: List<CanauxRadioEquipe>): Bilan = verrou.withLock {
        val pilote = liaison.piloteCourant?.takeIf { it.prete } ?: return Bilan()
        val protocole = pilote.protocole
        val meshcore = protocole == Protocole.MESHCORE
        val voulus = PlanCanauxEquipes.pour(meshcore, equipes)
        val presents = pilote.canaux.associate { PlanCanauxEquipes.normaliser(it.nom) to it.index }
        val memoire = installes(protocole)
        // Ce qui n'est plus sur la radio (retiré à la main) n'est plus à nous.
        memoire.keys.retainAll(presents.keys + voulus.map { PlanCanauxEquipes.normaliser(it.nom) }.toSet())
        val actions = PlanCanauxEquipes.actions(voulus, presents, memoire)
        if (actions.isEmpty()) { memoriser(protocole, memoire); return Bilan() }

        var bilan = Bilan()
        when (pilote) {
            is PiloteMeshtastic -> {
                liaison.relireAvance(); delay(2_000)
                val roles = pilote.avance.canauxMeshtastic.mapValues { it.value.role }.toMutableMap()
                for (a in actions) {
                    when (a) {
                        is Action.Retirer -> if (liaison.envoyerAdmin(pilote.adminGroupe(listOf(AdminMeshtastic.ecrireCanal(CanalMeshtastic(a.index, "", role = 0)))))) {
                            roles[a.index] = 0; memoire.remove(a.nom); bilan = bilan.copy(retires = bilan.retires + 1)
                        }
                        is Action.Reecrire -> if (ecrireMeshtastic(liaison, pilote, a.index, a.canal)) {
                            memoire[PlanCanauxEquipes.normaliser(a.canal.nom)] = a.canal.version; bilan = bilan.copy(reecrits = bilan.reecrits + 1)
                        }
                        is Action.Ajouter -> {
                            val i = PlanRadio.emplacementLibreMeshtastic(roles)
                            if (i == null) bilan = bilan.copy(sansPlace = bilan.sansPlace + 1)
                            else if (ecrireMeshtastic(liaison, pilote, i, a.canal)) {
                                roles[i] = 2; memoire[PlanCanauxEquipes.normaliser(a.canal.nom)] = a.canal.version
                                bilan = bilan.copy(ajoutes = bilan.ajoutes + 1)
                            }
                        }
                    }
                }
            }
            is PiloteMeshCore -> {
                val occupes = pilote.canaux.map { it.index }.toMutableSet()
                for (a in actions) {
                    when (a) {
                        is Action.Retirer -> if (liaison.envoyerAdmin(listOf(AdminMeshCore.effacerCanal(a.index), MeshCore.demanderCanal(a.index)))) {
                            occupes -= a.index; memoire.remove(a.nom); bilan = bilan.copy(retires = bilan.retires + 1)
                        }
                        is Action.Reecrire -> if (ecrireMeshCore(liaison, a.index, a.canal)) {
                            memoire[PlanCanauxEquipes.normaliser(a.canal.nom)] = a.canal.version; bilan = bilan.copy(reecrits = bilan.reecrits + 1)
                        }
                        is Action.Ajouter -> {
                            val i = PlanRadio.emplacementLibreMeshCore(occupes)
                            if (i == null) bilan = bilan.copy(sansPlace = bilan.sansPlace + 1)
                            else if (ecrireMeshCore(liaison, i, a.canal)) {
                                occupes += i; memoire[PlanCanauxEquipes.normaliser(a.canal.nom)] = a.canal.version
                                bilan = bilan.copy(ajoutes = bilan.ajoutes + 1)
                            }
                        }
                    }
                }
            }
            else -> {}
        }
        memoriser(protocole, memoire)
        if (bilan.ajoutes + bilan.reecrits + bilan.retires > 0) { delay(1_500); liaison.relireAvance() }
        bilan
    }

    private suspend fun ecrireMeshtastic(liaison: LiaisonRadio, pilote: PiloteMeshtastic, index: Int, c: CanalAInstaller) =
        liaison.envoyerAdmin(pilote.adminGroupe(listOf(AdminMeshtastic.ecrireCanal(CanalMeshtastic(index, c.nom, role = 2, psk = c.cleHex.hexEnOctets())))))

    private suspend fun ecrireMeshCore(liaison: LiaisonRadio, index: Int, c: CanalAInstaller) =
        liaison.envoyerAdmin(listOf(AdminMeshCore.ecrireCanal(index, c.nom, c.cleHex.hexEnOctets()), MeshCore.demanderCanal(index)))

    private fun String.hexEnOctets(): ByteArray = chunked(2).mapNotNull { it.toIntOrNull(16)?.toByte() }.toByteArray()
}
