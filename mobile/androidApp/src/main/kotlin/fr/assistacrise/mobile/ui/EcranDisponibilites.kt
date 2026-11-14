package fr.assistacrise.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.Ecran
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.Creneau
import fr.assistacrise.mobile.domaine.JourDeGrille
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Mes disponibilités : une ligne par jour, quatre créneaux. Sur le site, la grille est en
 * colonnes par jour ; sur un téléphone tenu debout, quinze colonnes ne tiennent pas — ici
 * le jour est la ligne, et l'écran défile dans le sens du temps.
 */
@Composable
fun EcranDisponibilites(modele: ModeleApplication) {
    val grille by modele.grille.collectAsStateWithLifecycle()
    val campagne = grille?.campagne
    Column(Modifier.fillMaxSize()) {
        EnTeteRetour(if (campagne != null) "Mes créneaux" else "Mes disponibilités", modele) {
            if (modele.notificationOuverte != null && campagne != null) modele.ouvrirNotification(modele.notificationOuverte!!) else modele.aller(Ecran.COMPTE)
        }
        val g = grille
        when {
            modele.chargement && g == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            g == null -> Message(
                if (modele.horsLigne) "Pas de réseau. Vos disponibilités se lisent et se déclarent en ligne : une case cochée sans que le serveur l'ait reçue ferait croire que vous avez répondu."
                else "Vos disponibilités n'ont pas pu être chargées.",
            )
            g.sansRessource -> Message("Vous n'avez pas encore de fiche de bénévole dans une association : il n'y a pas de disponibilité à déclarer. Complétez d'abord « Ma fiche ».")
            else -> LazyColumn(Modifier.fillMaxSize()) {
                item {
                    Column(Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) {
                        if (campagne != null) {
                            Text("${campagne.institutionNom} vous demande vos disponibilités", style = MaterialTheme.typography.titleMedium)
                            Text("Du ${jourLisible(campagne.debut)} au ${jourLisible(campagne.fin)}", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.primary)
                            Spacer(Modifier.height(6.dp))
                            Text("Chaque case cochée est enregistrée tout de suite et vaut réponse.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        } else {
                            Text(
                                "C'est cette grille que votre encadrement consulte pour constituer une équipe. Une case vide veut dire indisponible.",
                                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        if (g.ressources.size > 1) {
                            Spacer(Modifier.height(6.dp))
                            Text("Vos créneaux valent pour vos ${g.ressources.size} associations : on ne peut être qu'à un endroit à la fois.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Spacer(Modifier.height(10.dp))
                    }
                    // Mêmes marges que les lignes de jours : chaque mot tombe au-dessus de sa colonne.
                    Row(Modifier.fillMaxWidth().padding(start = 76.dp, end = 72.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Creneau.entries.forEach { c ->
                            Text(c.libelle, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center, modifier = Modifier.weight(1f))
                        }
                    }
                }
                items(g.jours, key = { it.date }) { jour -> LigneJour(jour, modele) }
                item { Spacer(Modifier.height(24.dp)) }
            }
        }
    }
}

@Composable
private fun Message(texte: String) {
    Text(texte, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(20.dp))
}

@Composable
private fun LigneJour(jour: JourDeGrille, modele: ModeleApplication) {
    val date = runCatching { LocalDate.parse(jour.date) }.getOrNull()
    val nom = date?.format(DateTimeFormatter.ofPattern("EEE d", Locale.FRANCE)) ?: jour.date
    val nomLong = date?.format(DateTimeFormatter.ofPattern("EEEE d MMMM", Locale.FRANCE)) ?: jour.date
    val weekEnd = date?.dayOfWeek?.value?.let { it >= 6 } == true
    Row(
        Modifier.fillMaxWidth().background(if (weekEnd) MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f) else MaterialTheme.colorScheme.background)
            .padding(start = 20.dp, end = 8.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(nom, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.width(56.dp))
        Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Creneau.entries.forEach { c ->
                val coche = jour.coche(c)
                val enCours = modele.caseEnCours == "${jour.date}|${c.name}"
                Box(
                    Modifier.weight(1f).height(44.dp).clip(RoundedCornerShape(8.dp))
                        .background(if (coche) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface)
                        .border(1.dp, if (coche) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline, RoundedCornerShape(8.dp))
                        .clickable(enabled = modele.caseEnCours == null, role = Role.Checkbox) { modele.basculerCreneau(jour.date, c, !coche) }
                        .semantics { contentDescription = "$nomLong, ${c.libelle} : ${if (coche) "disponible" else "indisponible"}" },
                    contentAlignment = Alignment.Center,
                ) {
                    when {
                        enCours -> CircularProgressIndicator(Modifier.height(18.dp).width(18.dp), strokeWidth = 2.dp, color = if (coche) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.primary)
                        coche -> Icon(Icons.Filled.Check, contentDescription = null, tint = MaterialTheme.colorScheme.onPrimary)
                    }
                }
            }
        }
        // Toute la journée d'un geste : personne ne coche soixante cases une par une.
        TextButton(onClick = { modele.basculerCreneau(jour.date, null, !jour.complet) }, enabled = modele.caseEnCours == null, modifier = Modifier.width(64.dp)) {
            Text(if (jour.complet) "Rien" else "Tout", style = MaterialTheme.typography.labelMedium)
        }
    }
}
