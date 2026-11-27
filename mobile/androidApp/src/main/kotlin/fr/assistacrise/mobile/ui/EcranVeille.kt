package fr.assistacrise.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.domaine.EvenementVeille
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * La mini veille du territoire (27/11/2026) : « très léger, texte, peu de couleurs ». Une zone par
 * crise ou manifestation en cours, six rubriques ; la seule couleur est celle de l'alerte.
 */
@Composable
fun EcranVeille(modele: ModeleApplication) {
    val v = modele.veille
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(start = 4.dp, end = 8.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = modele::fermerVeille) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
            Column(Modifier.weight(1f)) {
                Text("Veille du territoire", style = MaterialTheme.typography.titleLarge)
                val heure = modele.veilleLueLe?.let { SimpleDateFormat("HH:mm", Locale.FRANCE).format(Date(it)) }
                Text(listOfNotNull(heure?.let { "Mise à jour à $it" }, modele.veilleErreur).joinToString(" · ").ifEmpty { "Lecture…" },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (modele.veilleErreur != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TextButton(onClick = modele::lireVeille, enabled = !modele.veilleEnCours) { Text("Actualiser") }
        }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            when {
                v == null -> Text(if (modele.veilleErreur != null) "La veille n'a pas encore pu être lue." else "Lecture de la veille…",
                    style = MaterialTheme.typography.bodyMedium)
                v.zones.isEmpty() -> Text("Aucune crise ni manifestation en cours pour vous : rien à veiller.", style = MaterialTheme.typography.bodyMedium)
                else -> v.zones.forEach { zone ->
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text((if (zone.nature == "manifestation") "Manifestation · " else "Crise · ") + zone.nom,
                            style = MaterialTheme.typography.titleMedium)
                        if (zone.rubriques.isEmpty()) Text("Zone inconnue : pas de commune rattachée.", style = MaterialTheme.typography.bodySmall)
                        zone.rubriques.forEach { r ->
                            Column {
                                Text(r.libelle, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
                                if (r.evenements.isEmpty()) {
                                    Text(r.texteSiVide, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                r.evenements.forEach { e ->
                                    val marque = when (e.niveau) { EvenementVeille.EXCEPTIONNEL -> "‼ "; EvenementVeille.ALERTE -> "! "; else -> "· " }
                                    Text(marque + e.titre, style = MaterialTheme.typography.bodyMedium,
                                        color = if (e.important) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
                                        fontWeight = if (e.niveau == EvenementVeille.EXCEPTIONNEL) FontWeight.SemiBold else null)
                                    if (e.detail.isNotBlank()) Text(e.detail, style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(start = 14.dp))
                                }
                            }
                        }
                        HorizontalDivider()
                    }
                }
            }
            // Les cinq stations-service les plus proches (27/11/2026) ; toucher l'une l'ouvre dans
            // l'application de cartes du téléphone.
            v?.stations?.takeIf { it.resultats.isNotEmpty() }?.let { s ->
                val contexte = androidx.compose.ui.platform.LocalContext.current
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Stations-service les plus proches" + (s.autourDe?.let { " (de $it)" } ?: ""), style = MaterialTheme.typography.titleMedium)
                    s.resultats.forEach { st ->
                        Column(Modifier.fillMaxWidth().clickable(enabled = st.latitude != null && st.longitude != null) {
                            val geo = android.net.Uri.parse("geo:${st.latitude},${st.longitude}?q=${st.latitude},${st.longitude}")
                            runCatching { contexte.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, geo)) }
                        }) {
                            Text(st.titre, style = MaterialTheme.typography.bodyMedium)
                            Text(st.etat, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 14.dp),
                                color = if (st.enRupture) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    HorizontalDivider()
                }
            }
            Text("‼ exceptionnel · ! alerte, selon les seuils conseillés des alertes automatiques. Les estimations " +
                "(orage en approche) ne sont pas des prévisions. Sources : Météo-France, Vigicrues, Hub'Eau, Shom, BCSF-Rénass, EMSC, " +
                "NASA FIRMS, EUMETSAT ; carburants : prix des carburants, ministère de l'Économie.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
