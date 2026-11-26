package fr.assistacrise.mobile

import fr.assistacrise.mobile.domaine.Alerte
import fr.assistacrise.mobile.domaine.EtiquetteTerrain

/**
 * La mise en forme des notifications de messages radio (23/11/2026). Une étiquette de terrain
 * reçue par radio (« ⚑DANG 3f2a9c.9c1e0b.a1b2c3 Danger… ») se lit « Danger / problème sur
 * place — Léa : mur fissuré » ; un Danger ou une Demande de premiers secours sonne en plus
 * comme une alerte urgente, à part de la conversation.
 */
object FormatNotification {

    fun ligneRadio(auteur: String, texte: String): String {
        val lue = EtiquetteTerrain.lire(texte)
        val qui = auteur.ifBlank { null }
        // Marqueur radio (format MeshCore SAR, 26/11/2026) : « 📍 🔥 Feu · note », pas le texte brut.
        fr.assistacrise.mobile.domaine.MarqueursRadio.lire(texte)?.let { m ->
            val l = "📍 ${m.emoji} ${fr.assistacrise.mobile.domaine.MarqueursRadio.libelleDe(m)}" + (fr.assistacrise.mobile.domaine.MarqueursRadio.noteLibre(m)?.let { " · $it" } ?: "") + " (sur la carte)"
            return if (qui != null) "$qui : $l" else l
        }
        return when {
            lue != null -> listOfNotNull(lue.type.libelle, qui).joinToString(" — ") + if (lue.corps.isNotBlank()) " : ${lue.corps}" else ""
            qui != null -> "$qui : $texte"
            else -> texte
        }
    }

    /** Danger ou demande de secours reçus par radio : une alerte urgente en plus de la conversation. */
    fun urgenceTerrain(app: Application, auteur: String, texte: String, cible: String) {
        val lue = EtiquetteTerrain.lire(texte) ?: return
        if (!lue.type.prioritaire) return
        app.alertes.afficher(Alerte(
            cle = "urgence-radio:${texte.hashCode()}", genre = Alerte.Genre.MESSAGE,
            titre = "${lue.type.libelle}${if (auteur.isNotBlank()) " — $auteur" else ""}",
            texte = lue.corps.ifBlank { "Reçu par radio." }, urgent = true, cible = cible,
        ))
    }
}
