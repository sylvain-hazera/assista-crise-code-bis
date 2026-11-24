package fr.assistacrise.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.Photographe
import fr.assistacrise.mobile.domaine.GenreSignalementPei
import fr.assistacrise.mobile.domaine.NaturePei
import fr.assistacrise.mobile.domaine.PointEau
import fr.assistacrise.mobile.domaine.Releve
import fr.assistacrise.mobile.domaine.SignalementPei
import fr.assistacrise.mobile.domaine.SuiviSignalementPei
import fr.assistacrise.mobile.domaine.distanceMetres
import fr.assistacrise.mobile.domaine.doublonsPossibles
import java.io.File
import java.util.UUID

/** La fiche d'un point d'eau incendie touché sur la carte (24/11/2026). */
@Composable
fun FichePointEau(point: PointEau, moi: Releve?, suivi: List<SuiviSignalementPei>,
                  surSignaler: (GenreSignalementPei) -> Unit, surFermer: () -> Unit, modifier: Modifier = Modifier) {
    Surface(shape = MaterialTheme.shapes.large, shadowElevation = 4.dp, modifier = modifier) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(point.typeLibelle + if (point.refTerrain.isNotBlank()) " ${point.refTerrain}" else "",
                 style = MaterialTheme.typography.titleLarge)
            Text(point.libelleEtat, style = MaterialTheme.typography.titleMedium,
                 color = if (point.etat == "INDISPONIBLE") Refus else MaterialTheme.colorScheme.onSurface)
            val details = listOfNotNull(
                point.debit?.let { "Débit : ${it.toInt()} m³/h" }, point.volume?.let { "Volume : ${it.toInt()} m³" },
                point.diametre?.let { "Diamètre : $it mm" }, point.gestionnaire.ifBlank { null }?.let { "Gestionnaire : $it" },
                moi?.let { "À ${distanceMetres(it.latitude, it.longitude, point.latitude, point.longitude).toInt()} m de vous" },
            )
            details.forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
            Text(point.libelleSource + (point.attribution?.let { " — $it" } ?: ""),
                 style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            suivi.filter { it.pei == point.id }.take(3).forEach { s ->
                Text("Votre signalement « ${s.genreLibelle} » : ${s.statutLibelle.lowercase()}" +
                     (s.motifDecision.ifBlank { null }?.let { " ($it)" } ?: ""),
                     style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text("Signaler à la commune", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 4.dp))
            GenreSignalementPei.entries.filter { it.surUnPoint }.forEach { g ->
                OutlinedButton(onClick = { surSignaler(g) }, modifier = Modifier.fillMaxWidth().height(50.dp)) { Text(g.libelle) }
            }
            TextButton(onClick = surFermer, modifier = Modifier.fillMaxWidth()) { Text("Fermer") }
        }
    }
}

/**
 * Signaler un point d'eau : l'état d'un point existant, ou un nouveau point à ma position
 * (citerne agricole, plan d'eau, piscine…). Sans réseau, il attend dans la file.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SignalerPointEau(modele: ModeleApplication, genre: GenreSignalementPei, point: PointEau?, moi: Releve?,
                     connus: List<PointEau>, crise: String?, surFin: () -> Unit, modifier: Modifier = Modifier) {
    val contexte = LocalContext.current
    val identifiant = remember { UUID.randomUUID().toString() }
    var nature by remember { mutableStateOf<NaturePei?>(null) }
    var debit by remember { mutableStateOf("") }
    var volume by remember { mutableStateOf("") }
    var commentaire by remember { mutableStateOf("") }
    val photos = remember { mutableStateListOf<File>() }
    var prise by remember { mutableStateOf<File?>(null) }
    val appareil = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { reussie ->
        val fichier = prise
        prise = null
        if (reussie && fichier != null) photos += fichier else fichier?.delete()
    }
    val nouveau = genre == GenreSignalementPei.NOUVEAU
    val lieu = if (nouveau) moi?.let { it.latitude to it.longitude } else point?.let { it.latitude to it.longitude }
    val doublons = if (nouveau && moi != null) doublonsPossibles(connus, moi.latitude, moi.longitude) else emptyList()
    Surface(shape = MaterialTheme.shapes.large, shadowElevation = 4.dp, modifier = modifier) {
        Column(Modifier.padding(18.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(if (nouveau) "Nouveau point d'eau ici" else "${genre.libelle} — ${point?.typeLibelle ?: "point d'eau"}",
                 style = MaterialTheme.typography.titleLarge)
            if (lieu == null) {
                Text("Votre position n'est pas encore connue : attendez que la carte vous situe.", color = Refus)
            }
            if (doublons.isNotEmpty()) {
                Text("Attention : ${doublons.size} point(s) d'eau déjà connu(s) à moins de 50 m (le plus proche à " +
                     "${distanceMetres(moi!!.latitude, moi.longitude, doublons[0].latitude, doublons[0].longitude).toInt()} m). " +
                     "S'il s'agit du même, signalez plutôt son état depuis sa fiche.",
                     color = Attente, style = MaterialTheme.typography.bodyMedium)
            }
            if (nouveau) {
                Text("Nature", style = MaterialTheme.typography.titleMedium)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    NaturePei.entries.forEach { n -> FilterChip(selected = nature == n, onClick = { nature = n }, label = { Text(n.libelle) }) }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = debit, onValueChange = { debit = it.filter { c -> c.isDigit() }.take(5) },
                                      label = { Text("Débit estimé (m³/h)") }, singleLine = true,
                                      keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
                    OutlinedTextField(value = volume, onValueChange = { volume = it.filter { c -> c.isDigit() }.take(7) },
                                      label = { Text("Volume estimé (m³)") }, singleLine = true,
                                      keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
                }
            }
            OutlinedTextField(value = commentaire, onValueChange = { commentaire = it.take(500) },
                              label = { Text(if (nouveau) "Accès, propriétaire, remarques" else "Ce que vous constatez") },
                              modifier = Modifier.fillMaxWidth())
            OutlinedButton(onClick = {
                val (fichier, adresse) = Photographe.nouvellePrise(contexte)
                prise = fichier
                runCatching { appareil.launch(adresse) }.onFailure { prise = null; fichier.delete() }
            }, modifier = Modifier.fillMaxWidth().height(50.dp)) {
                Text(if (photos.isEmpty()) "Prendre une photo" else "Prendre une photo (${photos.size} prise(s))")
            }
            Button(
                enabled = lieu != null && (!nouveau || nature != null) && !modele.photoEnCours,
                onClick = {
                    val (lat, lon) = lieu ?: return@Button
                    val signalement = SignalementPei(
                        id = identifiant, genre = genre.name, pei = if (nouveau) null else point?.id,
                        latitude = lat, longitude = lon, precisionM = moi?.precisionM?.toInt()?.takeIf { it > 0 },
                        typePei = if (nouveau) nature?.code.orEmpty() else "",
                        debitEstime = debit.toDoubleOrNull(), volumeEstime = volume.toDoubleOrNull(),
                        commentaire = commentaire.trim(), observeLe = java.time.Instant.now().toString(), crise = crise,
                    )
                    modele.signalerPointEau(signalement, "Point d'eau — ${genre.libelle}", photos.toList(), moi, surFin)
                },
                modifier = Modifier.fillMaxWidth().height(52.dp),
            ) { Text("Envoyer à la commune") }
            Text("La commune valide votre signalement, puis le transmet au SDIS.",
                 style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick = surFin, modifier = Modifier.fillMaxWidth()) { Text("Annuler") }
        }
    }
}
