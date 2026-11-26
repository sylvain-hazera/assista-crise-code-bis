package fr.assistacrise.mobile.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.CartesEmbarquees
import fr.assistacrise.mobile.domaine.Crise
import fr.assistacrise.mobile.domaine.Dossier
import fr.assistacrise.mobile.domaine.PointCrise
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.maps.MapLibreMap

/**
 * « Embarquer ce secteur » (22/11/2026) : trois choix, avec la taille annoncée avant, et le
 * Wi-Fi conseillé. Les régions embarquées sont listées, avec leur taille, et se suppriment.
 */
@Composable
fun DialogueHorsLigne(
    modele: ModeleApplication, carte: MapLibreMap?, crises: List<Crise>, dossiers: List<Dossier>, points: List<PointCrise>,
    surFermeture: () -> Unit,
) {
    val cartes = modele.cartesHorsLigne
    val regions by cartes.regions.collectAsStateWithLifecycle()
    val encours by cartes.encours.collectAsStateWithLifecycle()
    var confirmation by remember { mutableStateOf<Triple<String, LatLngBounds, Int>?>(null) }
    LaunchedEffect(Unit) { cartes.relire() }

    // La zone en cours (+15 km) d'abord (27/11/2026) : la crise ou la manifestation en cours, au
    // niveau des rues ; « toute la zone de la crise », sur toutes les crises ouvertes, a disparu.
    val choix = buildList {
        modele.empriseDeLaZone()?.let { e ->
            add(Triple("La zone en cours (+15 km)", LatLngBounds.from(e.nord, e.est, e.sud, e.ouest), CartesEmbarquees.ZOOM_MAX_ZONE))
        }
        carte?.projection?.visibleRegion?.latLngBounds?.let { add(Triple("Ce que montre la carte", it, 17)) }
    }

    AlertDialog(
        onDismissRequest = surFermeture,
        title = { Text("Télécharger pour le hors-ligne") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text("Embarquez le fond de carte IGN pour l'utiliser sans réseau, avec votre position, les dossiers et les points de la crise.",
                    style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(8.dp))
                choix.forEach { (nom, bornes, zoom) ->
                    val (tuiles, octets) = cartes.estimation(bornes, zoom)
                    OutlinedButton(onClick = { confirmation = Triple(nom, bornes, zoom) }, modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                        enabled = encours?.let { it.termine || it.erreur != null } ?: true) {
                        Text("$nom — ${CartesEmbarquees.tailleLisible(octets)} environ ($tuiles tuiles)")
                    }
                }
                encours?.let { e ->
                    Spacer(Modifier.height(8.dp))
                    Text(if (e.termine) "« ${e.nom} » est embarquée." else "Téléchargement de « ${e.nom} » : ${e.faites} / ${e.attendues}",
                        style = MaterialTheme.typography.bodyMedium)
                    if (!e.termine && e.attendues > 0) LinearProgressIndicator(progress = { (e.faites.toFloat() / e.attendues).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                    e.erreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                }
                if (regions.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    Text("Déjà embarquées", style = MaterialTheme.typography.titleSmall)
                    regions.forEach { r ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("${fr.assistacrise.mobile.CartesHorsLigne.libelle(r.nom)} — ${CartesEmbarquees.tailleLisible(r.octets)}${if (r.terminee) "" else " (incomplète)"}",
                                style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                            TextButton(onClick = { cartes.supprimer(r.id) }) { Text("Supprimer") }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = surFermeture) { Text("Fermer") } },
    )

    confirmation?.let { (nom, bornes, zoom) ->
        val (_, octets) = cartes.estimation(bornes, zoom)
        val wifi = cartes.surWifi()
        AlertDialog(
            onDismissRequest = { confirmation = null },
            title = { Text("Embarquer « $nom » ?") },
            text = {
                Text("Environ ${CartesEmbarquees.tailleLisible(octets)}." +
                    if (wifi) " Vous êtes en Wi-Fi." else " Vous n'êtes pas en Wi-Fi : le téléchargement passera par vos données mobiles.")
            },
            confirmButton = { TextButton(onClick = {
                // La zone en cours garde son nom de zone : elle ne sera pas retéléchargée d'office.
                if (zoom == CartesEmbarquees.ZOOM_MAX_ZONE && nom.startsWith("La zone en cours")) modele.telechargerZone(modele.empriseDeLaZone())
                else cartes.telecharger(nom, bornes, zoom)
                confirmation = null
            }) { Text("Télécharger") } },
            dismissButton = { TextButton(onClick = { confirmation = null }) { Text("Annuler") } },
        )
    }
}
