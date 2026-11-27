package fr.assistacrise.mobile.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import fr.assistacrise.mobile.domaine.Mentions

/**
 * Appui long sur un message (23/11/2026, « appui long sur un message précédent permet de taguer ou
 * de répondre précisément ») : Répondre (cite le début du message et tague son auteur), Taguer
 * l'auteur, Copier le texte. Commun à la messagerie d'équipe et à la messagerie radio.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun AvecMenuMessage(auteur: String, texte: String, moi: Boolean, surRepondre: () -> Unit, surTaguer: () -> Unit,
                    surReagir: ((String) -> Unit)? = null, surTrajet: (() -> Unit)? = null, contenu: @Composable () -> Unit) {
    var ouvert by remember { mutableStateOf(false) }
    val presse = LocalClipboardManager.current
    Box(Modifier.combinedClickable(onClick = {}, onLongClick = { ouvert = true }, onLongClickLabel = "Répondre, taguer ou copier")) {
        contenu()
        DropdownMenu(expanded = ouvert, onDismissRequest = { ouvert = false }) {
            // Réagir d'un émoji (26/11/2026, messagerie radio) : la rangée des plus courants.
            if (surReagir != null) {
                Row(Modifier.padding(horizontal = 8.dp)) {
                    fr.assistacrise.mobile.domaine.ReactionsRadio.RAPIDES.forEach { e ->
                        androidx.compose.material3.TextButton(onClick = { ouvert = false; surReagir(e) },
                            modifier = Modifier.semantics { contentDescription = "Réagir $e" }) {
                            Text(e, style = MaterialTheme.typography.titleMedium)
                        }
                    }
                }
            }
            DropdownMenuItem(text = { Text("Répondre") }, onClick = { ouvert = false; surRepondre() })
            if (!moi && auteur.isNotBlank()) {
                DropdownMenuItem(text = { Text("Taguer ${Mentions.etiquette(auteur)}") }, onClick = { ouvert = false; surTaguer() })
            }
            DropdownMenuItem(text = { Text("Copier le texte") }, onClick = { ouvert = false; presse.setText(AnnotatedString(texte)) })
            // Messagerie radio MeshCore (27/11/2026) : par quels relais le message est arrivé.
            if (surTrajet != null) DropdownMenuItem(text = { Text("Voir le trajet") }, onClick = { ouvert = false; surTrajet() })
        }
    }
}

/** Au-dessus de la zone de saisie : le message auquel on répond, et de quoi annuler. */
@Composable
fun BandeauReponse(auteur: String, texte: String, annuler: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(10.dp)).padding(start = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f).padding(vertical = 6.dp)) {
            Text("En réponse à ${auteur.ifBlank { "vous-même" }}", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Text(texte, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        IconButton(onClick = annuler) { Icon(Icons.Filled.Close, contentDescription = "Ne plus répondre à ce message") }
    }
}

/** Ajoute le tag d'une personne au brouillon, sans le doubler. */
fun taguer(brouillon: String, auteur: String): String {
    val tag = Mentions.etiquette(auteur)
    if (brouillon.contains(tag)) return brouillon
    return (brouillon.trimEnd() + " " + tag + " ").trimStart()
}
