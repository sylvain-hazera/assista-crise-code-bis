package fr.assistacrise.mobile.ui

import android.annotation.SuppressLint
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.Photographe
import fr.assistacrise.mobile.domaine.Constat
import fr.assistacrise.mobile.domaine.Danger
import fr.assistacrise.mobile.domaine.EtatBien
import fr.assistacrise.mobile.domaine.PointTournee
import fr.assistacrise.mobile.domaine.Releve
import fr.assistacrise.mobile.domaine.distanceM
import fr.assistacrise.mobile.domaine.prochainPoint
import org.maplibre.android.MapLibre
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.layers.CircleLayer
import org.maplibre.android.style.layers.PropertyFactory.circleColor
import org.maplibre.android.style.layers.PropertyFactory.circleRadius
import org.maplibre.android.style.layers.PropertyFactory.circleStrokeColor
import org.maplibre.android.style.layers.PropertyFactory.circleStrokeWidth
import org.maplibre.android.style.sources.GeoJsonSource
import java.io.File
import java.time.Instant
import java.util.UUID

/*
 * L'évaluation des dégâts à pied (DOSSIER-ADRESSES-ET-DEGATS.md, § 5) : une personne seule,
 * téléphone à la main. Tournée des points les plus proches → « le point est-il bien placé ? »
 * (sinon : le replacer) → évaluer → suivant. Et « nouveau point ici » là où il n'y a pas
 * d'adresse (une voiture, un pont). Tout part par la file ; hors réseau, sur le secteur embarqué.
 */

private sealed interface Etape {
    data object Accueil : Etape
    data object Tournee : Etape
    data class Position(val point: PointTournee) : Etape
    data class Replacer(val point: PointTournee) : Etape
    data class Evaluer(val point: PointTournee?, val lieu: Releve?, val replace: Boolean) : Etape
}

@Composable
fun EcranDegats(modele: ModeleApplication) {
    val crises by modele.crises.collectAsStateWithLifecycle()
    val secteur by modele.secteurDegats.collectAsStateWithLifecycle()
    val (position, autorise, demanderPosition) = positionDuMoment()
    val ouvertes = crises.filter { it.ouverte }
    var crise by remember { mutableStateOf(ouvertes.singleOrNull()?.id) }
    var etape by remember { mutableStateOf<Etape>(Etape.Accueil) }
    var dernier by remember { mutableStateOf<String?>(null) }

    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Évaluer les dégâts", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            if (etape != Etape.Accueil) TextButton(onClick = { etape = if (etape == Etape.Tournee) Etape.Accueil else Etape.Tournee }) { Text("Retour") }
        }
        if (!autorise) {
            Text("La position du téléphone est nécessaire pour trouver les points autour de vous.", style = MaterialTheme.typography.bodyMedium)
            Button(onClick = demanderPosition, modifier = Modifier.fillMaxWidth()) { Text("Autoriser la localisation") }
            return@Column
        }
        when (val e = etape) {
            Etape.Accueil -> Accueil(modele, ouvertes.map { it.id to it.nom }, crise, { crise = it }, position, secteur?.let {
                "Secteur embarqué le ${it.genereLe.take(16).replace('T', ' ')} : ${it.adresses.size} adresses, ${it.biens.size} biens déjà vus" +
                    (if (it.constatsFaits > 0) ", ${it.constatsFaits} constat(s) à envoyer" else "")
            }) { etape = Etape.Tournee }
            Etape.Tournee -> Tournee(modele, crise!!, position, dernier, surPoint = { etape = Etape.Position(it) },
                                     surNouveau = { etape = Etape.Evaluer(null, position, replace = false) })
            is Etape.Position -> PositionDuPoint(e.point, position,
                                                 surOui = { etape = Etape.Evaluer(e.point, null, replace = false) },
                                                 surNon = { etape = Etape.Replacer(e.point) })
            is Etape.Replacer -> Replacer(e.point, position) { lieu -> etape = Etape.Evaluer(e.point, lieu, replace = true) }
            is Etape.Evaluer -> Evaluer(modele, crise!!, e.point, e.lieu ?: position, e.replace, position) {
                dernier = e.point?.let { it.banId ?: it.habitation }
                etape = Etape.Tournee
            }
        }
    }
}

@Composable
private fun Accueil(modele: ModeleApplication, crises: List<Pair<String, String>>, crise: String?, choisir: (String) -> Unit,
                    position: Releve?, resumeSecteur: String?, commencer: () -> Unit) {
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Crise", style = MaterialTheme.typography.titleMedium)
        if (crises.isEmpty()) Text("Aucune crise ouverte.", style = MaterialTheme.typography.bodyMedium)
        crises.forEach { (id, nom) ->
            Row(Modifier.fillMaxWidth().clickable { choisir(id) }, verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = crise == id, onCheckedChange = { choisir(id) })
                Text(nom.ifBlank { "Crise" })
            }
        }
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Sans réseau", style = MaterialTheme.typography.titleMedium)
                Text(resumeSecteur ?: "Avant de partir, embarquez le secteur : adresses, biens déjà vus, dossiers ouverts, à 1 km autour de vous. Il s'efface de ce téléphone dès que vos constats sont partis.",
                     style = MaterialTheme.typography.bodyMedium)
                Button(onClick = { if (crise != null && position != null) modele.embarquerSecteur(crise, position) },
                       enabled = crise != null && position != null && !modele.embarquementEnCours, modifier = Modifier.fillMaxWidth()) {
                    if (modele.embarquementEnCours) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    else Text(if (resumeSecteur == null) "Embarquer ce secteur" else "Réembarquer ici")
                }
                if (resumeSecteur != null) OutlinedButton(onClick = modele::effacerSecteurDegats, modifier = Modifier.fillMaxWidth()) { Text("Effacer le secteur embarqué") }
            }
        }
        Button(onClick = commencer, enabled = crise != null && position != null, modifier = Modifier.fillMaxWidth().height(56.dp)) {
            Text(if (position == null) "Localisation en cours…" else "Commencer la tournée")
        }
    }
}

@Composable
private fun Tournee(modele: ModeleApplication, crise: String, position: Releve?, dernier: String?,
                    surPoint: (PointTournee) -> Unit, surNouveau: () -> Unit) {
    val tournee = modele.tournee
    // Relue quand on s'est déplacé de plus de 20 m : la liste suit la marche.
    var lue by remember { mutableStateOf<Releve?>(null) }
    LaunchedEffect(position) {
        val ici = position ?: return@LaunchedEffect
        if (lue == null || lue!!.distanceA(ici) > 20) { lue = ici; modele.chargerTournee(crise, ici) }
    }
    val points = tournee?.points.orEmpty()
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (tournee?.horsLigne == true) Text("Sans réseau : points du secteur embarqué.", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.tertiary)
        tournee?.refus?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error) }
        val suivant = prochainPoint(points, sauf = dernier)
        if (suivant != null) {
            Button(onClick = { surPoint(suivant) }, modifier = Modifier.fillMaxWidth().height(64.dp)) {
                Text("Je suis devant : ${suivant.libelle} (${suivant.distanceM.toInt()} m)")
            }
        }
        OutlinedButton(onClick = surNouveau, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("Nouveau point ici (sans adresse)") }
        if (modele.tourneeEnCours && points.isEmpty()) CircularProgressIndicator()
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            items(points, key = { (it.banId ?: it.habitation ?: "${it.latitude},${it.longitude}") }) { p ->
                Row(Modifier.fillMaxWidth().clickable { surPoint(p) }.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(p.libelle, style = MaterialTheme.typography.bodyLarge)
                        Text(listOfNotNull(p.typeBien, etatLibelle(p)).joinToString(" · "), style = MaterialTheme.typography.bodySmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text("${p.distanceM.toInt()} m", style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

private fun etatLibelle(p: PointTournee): String = when {
    p.enAttente -> "évalué ici, en attente d'envoi"
    p.statutEvaluation == null || p.statutEvaluation == "NON_EVALUEE" -> "à évaluer"
    else -> EtatBien.entries.firstOrNull { it.name == p.statutEvaluation }?.libelle ?: p.statutEvaluation!!
}

@Composable
private fun PositionDuPoint(point: PointTournee, position: Releve?, surOui: () -> Unit, surNon: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(point.libelle, style = MaterialTheme.typography.titleLarge)
        val ecart = position?.let { distanceM(it.latitude, it.longitude, point.latitude, point.longitude).toInt() }
        Text(if (ecart != null) "Le point est à $ecart m de vous." else "Localisation en cours…", style = MaterialTheme.typography.bodyMedium)
        Text("Le point est-il bien placé par rapport au bâtiment ?", style = MaterialTheme.typography.titleMedium)
        Button(onClick = surOui, modifier = Modifier.fillMaxWidth().height(56.dp)) { Text("Oui, évaluer") }
        OutlinedButton(onClick = surNon, modifier = Modifier.fillMaxWidth().height(56.dp)) { Text("Non, le replacer") }
    }
}

/** Replacer le point : à ma position, ou en touchant la carte. L'adresse ne change pas. */
@SuppressLint("MissingPermission")
@Composable
private fun Replacer(point: PointTournee, position: Releve?, valider: (Releve) -> Unit) {
    val contexte = LocalContext.current
    var choisi by remember { mutableStateOf(Releve(point.latitude, point.longitude, System.currentTimeMillis())) }
    var carte by remember { mutableStateOf<MapLibreMap?>(null) }
    val vue = remember { MapLibre.getInstance(contexte); MapView(contexte).apply { onCreate(null) } }
    DisposableEffect(Unit) {
        vue.onStart(); vue.onResume()
        vue.getMapAsync { m ->
            m.uiSettings.isRotateGesturesEnabled = false
            m.cameraPosition = CameraPosition.Builder().target(LatLng(point.latitude, point.longitude)).zoom(18.0).build()
            m.setStyle(Style.Builder().fromJson(STYLE)) { style ->
                style.addSource(GeoJsonSource("point"))
                style.addLayer(CircleLayer("point-cercle", "point").withProperties(
                    circleRadius(10f), circleColor("#b91c1c"), circleStrokeColor("#ffffff"), circleStrokeWidth(3f)))
                carte = m
            }
            m.addOnMapClickListener { lieu -> choisi = Releve(lieu.latitude, lieu.longitude, System.currentTimeMillis()); true }
        }
        onDispose { vue.onPause(); vue.onStop(); vue.onDestroy() }
    }
    LaunchedEffect(choisi, carte) {
        (carte?.style?.getSource("point") as? GeoJsonSource)?.setGeoJson(
            """{"type":"Point","coordinates":[${choisi.longitude},${choisi.latitude}]}""")
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Touchez la carte là où est le bâtiment, ou placez-le à votre position.", style = MaterialTheme.typography.bodyMedium)
        AndroidView(factory = { vue }, modifier = Modifier.fillMaxWidth().height(320.dp))
        OutlinedButton(onClick = { position?.let { choisi = it } }, enabled = position != null, modifier = Modifier.fillMaxWidth()) { Text("À ma position") }
        Button(onClick = { valider(choisi) }, modifier = Modifier.fillMaxWidth().height(56.dp)) { Text("Valider la position") }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Evaluer(modele: ModeleApplication, crise: String, point: PointTournee?, lieu: Releve?, replace: Boolean,
                    position: Releve?, fini: () -> Unit) {
    val contexte = LocalContext.current
    val types by modele.typesBien.collectAsStateWithLifecycle()
    val identifiant = remember { UUID.randomUUID().toString() }
    var etat by remember { mutableStateOf<EtatBien?>(null) }
    val dangers = remember { mutableStateListOf<Danger>() }
    var personne by remember { mutableStateOf(false) }
    var reloger by remember { mutableStateOf(false) }
    var commentaire by remember { mutableStateOf("") }
    var type by remember { mutableStateOf<String?>(null) }
    var typeLibre by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }
    val photos = remember { mutableStateListOf<File>() }
    var prise by remember { mutableStateOf<File?>(null) }
    val appareil = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { reussie ->
        val fichier = prise
        prise = null
        if (reussie && fichier != null) photos += fichier else fichier?.delete()
    }
    val nouveau = point == null
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(point?.libelle ?: "Nouveau point ici", style = MaterialTheme.typography.titleLarge)
        if (nouveau) {
            Text("Ce que c'est", style = MaterialTheme.typography.titleMedium)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                types.filter { !it.aUneAdresse || it.nom == "Autre" }.forEach { t ->
                    FilterChip(selected = type == t.id, onClick = { type = t.id; typeLibre = "" }, label = { Text(t.nom) })
                }
            }
            OutlinedTextField(value = typeLibre, onValueChange = { typeLibre = it.take(80); if (it.isNotBlank()) type = null },
                              label = { Text("Autre type (ajouté à la liste)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(value = description, onValueChange = { description = it.take(200) },
                              label = { Text("Description (ex. voiture isolée sur le parking)") }, modifier = Modifier.fillMaxWidth())
        }
        Text("État", style = MaterialTheme.typography.titleMedium)
        EtatBien.entries.forEach { e ->
            if (etat == e) Button(onClick = { etat = e }, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text(e.libelle) }
            else OutlinedButton(onClick = { etat = e }, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text(e.libelle) }
        }
        Text("Dangers", style = MaterialTheme.typography.titleMedium)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Danger.entries.forEach { d ->
                FilterChip(selected = d in dangers, onClick = { if (d in dangers) dangers -= d else dangers += d }, label = { Text(d.libelle) })
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(personne, { personne = it }); Text("Personne sur place") }
        Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(reloger, { reloger = it }); Text("À reloger (ouvre un dossier)") }
        OutlinedTextField(value = commentaire, onValueChange = { commentaire = it.take(500) }, label = { Text("Commentaire") }, modifier = Modifier.fillMaxWidth())
        OutlinedButton(onClick = {
            val (fichier, adresse) = Photographe.nouvellePrise(contexte)
            prise = fichier
            runCatching { appareil.launch(adresse) }.onFailure { prise = null; fichier.delete() }
        }, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text(if (photos.isEmpty()) "Prendre une photo" else "Prendre une photo (${photos.size} prise(s))") }
        Spacer(Modifier.height(4.dp))
        Button(
            onClick = {
                val choisi = etat ?: return@Button
                val constat = Constat(
                    id = identifiant, crise = crise, banId = point?.banId,
                    habitation = if (point?.banId == null) point?.habitation else null,
                    latitude = (if (nouveau || replace) lieu else null)?.latitude,
                    longitude = (if (nouveau || replace) lieu else null)?.longitude,
                    positionCorrigee = replace && !nouveau,
                    typeBien = if (nouveau) type else null, typeBienLibre = typeLibre.trim().ifBlank { null },
                    description = description.trim().ifBlank { null }, statutEvaluation = choisi.name,
                    dangers = dangers.map { it.name }, personneSurPlace = personne, aReloger = reloger,
                    ouvrirDossier = reloger, commentaire = commentaire.trim().ifBlank { null },
                    constateLe = Instant.now().toString(),
                )
                modele.constater(constat, "Évaluation : ${point?.libelle ?: description.ifBlank { "point ajouté" }}", photos.toList(), position, fini)
            },
            enabled = etat != null && !modele.photoEnCours && (point?.banId != null || nouveau || point?.habitation != null)
                && (!nouveau || lieu != null),
            modifier = Modifier.fillMaxWidth().height(60.dp),
        ) { Text("Enregistrer l'évaluation") }
    }
}
