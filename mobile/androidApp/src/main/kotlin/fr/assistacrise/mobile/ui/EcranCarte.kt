@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package fr.assistacrise.mobile.ui

import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.TextButton
import fr.assistacrise.mobile.domaine.Crise
import fr.assistacrise.mobile.domaine.GenreDepot
import org.maplibre.android.style.expressions.Expression
import org.maplibre.android.style.layers.FillLayer
import org.maplibre.android.style.layers.LineLayer
import org.maplibre.android.style.layers.PropertyFactory.fillColor
import org.maplibre.android.style.layers.PropertyFactory.fillOpacity
import org.maplibre.android.style.layers.PropertyFactory.lineColor
import org.maplibre.android.style.layers.PropertyFactory.lineWidth
import android.Manifest
import android.annotation.SuppressLint
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.background
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.assistacrise.mobile.ModeleApplication
import fr.assistacrise.mobile.ServiceTerrain
import fr.assistacrise.mobile.domaine.Destination
import fr.assistacrise.mobile.domaine.Navigation
import fr.assistacrise.mobile.domaine.PositionMembre
import fr.assistacrise.mobile.domaine.Releve
import org.maplibre.android.MapLibre
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.layers.CircleLayer
import org.maplibre.android.style.layers.PropertyFactory.circleColor
import org.maplibre.android.style.layers.PropertyFactory.circleRadius
import org.maplibre.android.style.layers.PropertyFactory.circleStrokeColor
import org.maplibre.android.style.layers.PropertyFactory.circleStrokeWidth
import org.maplibre.android.style.sources.GeoJsonSource
import org.maplibre.geojson.Feature
import org.maplibre.geojson.FeatureCollection
import org.maplibre.geojson.Point

/**
 * Fond de carte : le Plan IGN de la Géoplateforme (dossier § 8), en tuiles image. Pas de
 * clé, pas de style tiers à charger : le style tient dans cette chaîne. Les tuiles déjà
 * vues restent dans le cache de MapLibre et s'affichent sans réseau.
 */
/** Le fond IGN, en ligne. Le même vit dans assets/style-ign.json pour les cartes embarquées. */
internal const val STYLE = """{"version":8,"sources":{"ign":{"type":"raster","tiles":["https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&FORMAT=image/png&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"],"tileSize":256,"maxzoom":19,"attribution":"© IGN"}},"layers":[{"id":"ign","type":"raster","source":"ign"}]}"""

internal val FRANCE = LatLng(46.6, 2.4)

@SuppressLint("MissingPermission")   // chaque lecture est précédée de ServiceTerrain.autorise
@Composable
fun EcranCarte(modele: ModeleApplication) {
    val contexte = LocalContext.current
    val cycle = LocalLifecycleOwner.current.lifecycle
    val lien by modele.lien.collectAsStateWithLifecycle()
    val membres = modele.positions
    val dossiers by modele.dossiers.collectAsStateWithLifecycle()
    val crises by modele.crises.collectAsStateWithLifecycle()
    val situes = dossiers.filter { it.situe && !it.clos }
    /** Le point maintenu du doigt : c'est là que se créera la demande, le signalement ou l'offre. */
    var lieuTouche by remember { mutableStateOf<LatLng?>(null) }
    val points by modele.pointsCrise.collectAsStateWithLifecycle()
    // Points d'eau incendie (24/11/2026) : gardés sur le téléphone pour la carte hors réseau.
    val pointsEau by modele.pointsEau.collectAsStateWithLifecycle()
    val suiviPointsEau by modele.suiviPointsEau.collectAsStateWithLifecycle()
    var pointEauTouche by remember { mutableStateOf<fr.assistacrise.mobile.domaine.PointEau?>(null) }
    var signalementPei by remember { mutableStateOf<Pair<fr.assistacrise.mobile.domaine.GenreSignalementPei, fr.assistacrise.mobile.domaine.PointEau?>?>(null) }
    var destination by remember { mutableStateOf<Destination?>(null) }
    var horsLigne by remember { mutableStateOf(false) }
    var capGps by remember { mutableStateOf<Float?>(null) }

    var autorise by remember { mutableStateOf(ServiceTerrain.autorise(contexte)) }
    var moi by remember { mutableStateOf<Releve?>(null) }
    var carte by remember { mutableStateOf<MapLibreMap?>(null) }
    var cadree by remember { mutableStateOf(false) }
    val demande = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { accordees ->
        autorise = accordees.values.any { it }
    }

    val vue = remember {
        MapLibre.getInstance(contexte)
        MapView(contexte).apply { onCreate(null) }
    }
    DisposableEffect(cycle) {
        val observateur = LifecycleEventObserver { _, evenement ->
            when (evenement) {
                Lifecycle.Event.ON_START -> vue.onStart()
                Lifecycle.Event.ON_RESUME -> vue.onResume()
                Lifecycle.Event.ON_PAUSE -> vue.onPause()
                Lifecycle.Event.ON_STOP -> vue.onStop()
                else -> Unit
            }
        }
        cycle.addObserver(observateur)
        // L'écran peut s'ouvrir alors que l'activité est déjà affichée : on rattrape.
        if (cycle.currentState.isAtLeast(Lifecycle.State.STARTED)) vue.onStart()
        if (cycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) vue.onResume()
        vue.getMapAsync { m ->
            m.uiSettings.isRotateGesturesEnabled = false
            m.uiSettings.isTiltGesturesEnabled = false
            m.cameraPosition = CameraPosition.Builder().target(FRANCE).zoom(4.5).build()
            // Le style est un fichier de l'application : le même sert aux cartes embarquées.
            m.setStyle(Style.Builder().fromUri(fr.assistacrise.mobile.CartesHorsLigne.STYLE)) { style ->
                style.addSource(GeoJsonSource("zones"))
                style.addSource(GeoJsonSource("pei"))
                style.addSource(GeoJsonSource("points"))
                style.addSource(GeoJsonSource("dossiers"))
                style.addSource(GeoJsonSource("lieu"))
                style.addSource(GeoJsonSource("membres"))
                style.addSource(GeoJsonSource("moi"))
                // Dessous d'abord : les périmètres de crise, puis les dossiers, puis les personnes.
                style.addLayer(FillLayer("zones-fond", "zones").withProperties(fillColor("#b91c1c"), fillOpacity(0.10f)))
                style.addLayer(LineLayer("zones-bord", "zones").withProperties(lineColor("#b91c1c"), lineWidth(2f)))
                // Points d'eau incendie, sous les dossiers : rouge indisponible, orange défaut,
                // bleu clair OpenStreetMap (indicatif), bleu SDIS ou validé par la commune.
                style.addLayer(CircleLayer("pei-points", "pei").withProperties(
                    circleRadius(6f), circleStrokeColor("#ffffff"), circleStrokeWidth(1.5f),
                    circleColor(Expression.switchCase(
                        Expression.eq(Expression.get("etat"), Expression.literal("INDISPONIBLE")), Expression.color(android.graphics.Color.parseColor("#dc2626")),
                        Expression.eq(Expression.get("etat"), Expression.literal("DEFAUT")), Expression.color(android.graphics.Color.parseColor("#f59e0b")),
                        Expression.eq(Expression.get("source"), Expression.literal("OSM")), Expression.color(android.graphics.Color.parseColor("#60a5fa")),
                        Expression.color(android.graphics.Color.parseColor("#1d4ed8"))))))
                // Forme ET couleur : un dossier est un point orange cerclé de sombre, plus gros
                // qu'une personne ; l'urgent est rouge. La liste sous la carte les nomme.
                style.addLayer(CircleLayer("dossiers-points", "dossiers").withProperties(
                    circleRadius(11f), circleStrokeColor("#1a1d29"), circleStrokeWidth(2.5f),
                    circleColor(Expression.match(Expression.get("urgent"), Expression.literal("oui"), Expression.color(android.graphics.Color.parseColor("#dc2626")), Expression.color(android.graphics.Color.parseColor("#f59e0b"))))))
                // Les points de la crise (accueil, PC, rassemblement) : verts, carrés de bord.
                style.addLayer(CircleLayer("points-crise", "points").withProperties(
                    circleRadius(9f), circleColor("#15803d"), circleStrokeColor("#ffffff"), circleStrokeWidth(2.5f)))
                style.addLayer(CircleLayer("lieu-point", "lieu").withProperties(
                    circleRadius(10f), circleColor("#ffffff"), circleStrokeColor("#3c4d81"), circleStrokeWidth(4f)))
                style.addLayer(CircleLayer("membres-points", "membres").withProperties(
                    circleRadius(8f), circleColor("#3c4d81"), circleStrokeColor("#ffffff"), circleStrokeWidth(2.5f)))
                style.addLayer(CircleLayer("moi-point", "moi").withProperties(
                    circleRadius(9f), circleColor("#2ea3f2"), circleStrokeColor("#ffffff"), circleStrokeWidth(3f)))
                carte = m
            }
            // Toucher un dossier l'ouvre ; maintenir le doigt ailleurs propose d'y créer quelque chose.
            m.addOnMapClickListener { point ->
                val ecran = m.projection.toScreenLocation(point)
                val touche = m.queryRenderedFeatures(ecran, "dossiers-points").firstOrNull()?.getStringProperty("id")
                val pointCrise = m.queryRenderedFeatures(ecran, "points-crise").firstOrNull()?.getStringProperty("id")
                val pei = m.queryRenderedFeatures(ecran, "pei-points").firstOrNull()?.getStringProperty("id")?.toLongOrNull()
                when {
                    touche != null -> { modele.ouvrirDossier(touche); true }
                    pointCrise != null -> {
                        points.firstOrNull { it.id == pointCrise }?.let { p -> destination = Destination(p.nom, p.latitude!!, p.longitude!!, "point") }
                        true
                    }
                    pei != null -> { pointEauTouche = modele.pointsEau.value.firstOrNull { it.id == pei }; true }
                    else -> { lieuTouche = null; false }
                }
            }
            m.addOnMapLongClickListener { point -> lieuTouche = point; true }
        }
        onDispose {
            cycle.removeObserver(observateur)
            vue.onPause(); vue.onStop(); vue.onDestroy()
        }
    }

    // Ma position : lue tant que la carte est affichée, et pas une seconde de plus.
    DisposableEffect(autorise) {
        val positions = contexte.getSystemService(LocationManager::class.java)
        var partagee = false
        val ecouteur = object : LocationListener {
            override fun onLocationChanged(p: Location) {
                val releve = Releve(p.latitude, p.longitude, System.currentTimeMillis(), p.accuracy)
                moi = releve
                // En mouvement (plus de 1 m/s), le cap du GPS oriente la flèche « Aller vers ».
                capGps = if (p.hasBearing() && p.hasSpeed() && p.speed > 1f) p.bearing else null
                // Partagée une fois par ouverture de la carte : le suivi continu, c'est le service.
                if (!partagee) { partagee = true; modele.partagerMaPosition(releve) }
            }
            @Deprecated("Deprecated in Java")
            override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
            override fun onProviderEnabled(provider: String) = Unit
            override fun onProviderDisabled(provider: String) = Unit
        }
        if (autorise) {
            for (source in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
                if (positions.allProviders.contains(source)) {
                    positions.getLastKnownLocation(source)?.let(ecouteur::onLocationChanged)
                    positions.requestLocationUpdates(source, 5_000L, 0f, ecouteur)
                }
            }
        }
        onDispose { positions.removeUpdates(ecouteur) }
    }

    LaunchedEffect(Unit) { modele.chargerLesPositions() }

    // Les points suivent les données ; la carte ne se recadre qu'une fois, pour ne pas
    // arracher la vue des mains de quelqu'un qui est en train de la déplacer.
    LaunchedEffect(carte, pointsEau) {
        val style = carte?.style ?: return@LaunchedEffect
        (style.getSource("pei") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(pointsEau.map { p ->
            Feature.fromGeometry(Point.fromLngLat(p.longitude, p.latitude)).apply {
                addStringProperty("id", p.id.toString()); addStringProperty("etat", p.etat); addStringProperty("source", p.source)
            }
        }))
    }

    LaunchedEffect(carte, membres, moi, situes, crises, lieuTouche, points) {
        val m = carte ?: return@LaunchedEffect
        val style = m.style ?: return@LaunchedEffect
        (style.getSource("points") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(points.map { p ->
            Feature.fromGeometry(Point.fromLngLat(p.longitude!!, p.latitude!!)).apply { addStringProperty("id", p.id) }
        }))
        (style.getSource("dossiers") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(situes.map { d ->
            Feature.fromGeometry(Point.fromLngLat(d.longitude!!, d.latitude!!)).apply {
                addStringProperty("id", d.id); addStringProperty("urgent", if (d.priorite == "URGENTE") "oui" else "non")
            }
        }))
        (style.getSource("zones") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(crises.mapNotNull { c ->
            // Un périmètre illisible ne doit pas empêcher la carte de s'afficher.
            c.zone?.takeIf { it !is kotlinx.serialization.json.JsonNull }?.let { z -> runCatching { Feature.fromJson("""{"type":"Feature","properties":{},"geometry":$z}""") }.getOrNull() }
        }))
        (style.getSource("lieu") as? GeoJsonSource)?.setGeoJson(
            FeatureCollection.fromFeatures(listOfNotNull(lieuTouche?.let { Feature.fromGeometry(Point.fromLngLat(it.longitude, it.latitude)) })),
        )
        (style.getSource("membres") as? GeoJsonSource)?.setGeoJson(
            FeatureCollection.fromFeatures(membres.map { Feature.fromGeometry(Point.fromLngLat(it.longitude!!, it.latitude!!)) }),
        )
        (style.getSource("moi") as? GeoJsonSource)?.setGeoJson(
            FeatureCollection.fromFeatures(listOfNotNull(moi?.let { Feature.fromGeometry(Point.fromLngLat(it.longitude, it.latitude)) })),
        )
        val points = membres.map { LatLng(it.latitude!!, it.longitude!!) } + listOfNotNull(moi?.let { LatLng(it.latitude, it.longitude) }) +
            situes.map { LatLng(it.latitude!!, it.longitude!!) }
        if (!cadree && points.isNotEmpty()) {
            cadree = true
            if (points.size == 1) m.moveCamera(CameraUpdateFactory.newLatLngZoom(points[0], 14.0))
            else m.moveCamera(CameraUpdateFactory.newLatLngBounds(LatLngBounds.Builder().includes(points).build(), 120))
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 16.dp, top = 12.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Carte", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            TextButton(onClick = { signalementPei = fr.assistacrise.mobile.domaine.GenreSignalementPei.NOUVEAU to null }) { Text("Point d'eau") }
            TextButton(onClick = { horsLigne = true }) { Text("Hors ligne") }
            PastilleLien(lien)
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            AndroidView(factory = { vue }, modifier = Modifier.fillMaxSize())
            if (!autorise) {
                Surface(shape = MaterialTheme.shapes.medium, shadowElevation = 3.dp, modifier = Modifier.align(Alignment.TopCenter).padding(12.dp)) {
                    Column(Modifier.padding(14.dp)) {
                        Text("Pour vous situer sur la carte, l'application a besoin de votre position. Elle n'est lue que lorsque la carte est ouverte.", style = MaterialTheme.typography.bodyMedium)
                        Button(
                            onClick = { demande.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)) },
                            modifier = Modifier.padding(top = 8.dp),
                        ) { Text("Afficher ma position") }
                    }
                }
            }
            lieuTouche?.let { lieu ->
                // Une fenêtre au-dessus de l'écran, et non posée sur la carte (23/11/2026) : avec
                // plusieurs crises, elle débordait de la carte et écrasait les trois boutons.
                androidx.compose.ui.window.Dialog(onDismissRequest = { lieuTouche = null },
                    properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
                    CreerIci(
                        crises.filter { it.accepteLesDepots },
                        surChoix = { genre, crise -> lieuTouche = null; modele.ouvrirDepot(genre, crise, Releve(lieu.latitude, lieu.longitude, System.currentTimeMillis(), 0f)) },
                        surAbandon = { lieuTouche = null },
                        modifier = Modifier.padding(16.dp),
                    )
                }
            }
            Text(
                "© IGN", style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.align(Alignment.BottomEnd).padding(6.dp).background(MaterialTheme.colorScheme.surface.copy(alpha = 0.8f)).padding(horizontal = 4.dp),
            )
        }
        Text(
            "Maintenez le doigt sur la carte pour y créer une demande, un signalement ou une offre d'aide.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
        )
        // Les noms sont dans la liste, pas sur la carte : toucher une ligne y conduit.
        if (membres.isNotEmpty() || situes.isNotEmpty() || points.isNotEmpty()) {
            // « Autour de moi » : les points de la crise, du plus proche au plus loin.
            val autour = moi?.let { r -> Navigation.autourDe(r.latitude, r.longitude, points.map { Destination(it.nom, it.latitude!!, it.longitude!!, it.type ?: "Point") }) }
                ?: points.map { Destination(it.nom, it.latitude!!, it.longitude!!, it.type ?: "Point") to null }
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 220.dp)) {
                items(autour, key = { "p-${it.first.nom}-${it.first.latitude}" }) { (d, distance) ->
                    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 6.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(14.dp).clip(CircleShape).background(androidx.compose.ui.graphics.Color(0xFF15803D)))
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(d.nom.ifBlank { "Point" }, style = MaterialTheme.typography.bodyLarge)
                            Text(listOfNotNull(d.genre, distance?.let { Navigation.distanceLisible(it) }).joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        TextButton(onClick = { destination = d }) { Text("Aller vers") }
                    }
                    HorizontalDivider()
                }
                items(situes, key = { "d-${it.id}" }) { d ->
                    Row(
                        Modifier.fillMaxWidth().clickable { carte?.animateCamera(CameraUpdateFactory.newLatLngZoom(LatLng(d.latitude!!, d.longitude!!), 16.0)) }
                            .padding(start = 20.dp, end = 8.dp, top = 6.dp, bottom = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(14.dp).clip(CircleShape).background(if (d.priorite == "URGENTE") Refus else Attente))
                        Spacer(Modifier.width(12.dp))
                        LigneDossier(d, Modifier.weight(1f))
                        TextButton(onClick = { destination = Destination(d.titre, d.latitude!!, d.longitude!!, "Dossier", d.id) }) { Text("Aller") }
                        TextButton(onClick = { modele.ouvrirDossier(d.id) }) { Text("Ouvrir") }
                    }
                    HorizontalDivider()
                }
                items(membres, key = { it.utilisateur }) { membre ->
                    LigneMembre(membre) {
                        carte?.animateCamera(CameraUpdateFactory.newLatLngZoom(LatLng(membre.latitude!!, membre.longitude!!), 15.0))
                    }
                    HorizontalDivider()
                }
            }
        } else {
            Text(
                "Aucun dossier situé, et aucun membre de vos équipes n'a partagé sa position ces trois dernières heures.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp),
            )
        }
    }
    if (horsLigne) DialogueHorsLigne(modele, carte, crises, situes, points) { horsLigne = false }
    pointEauTouche?.let { p ->
        androidx.compose.ui.window.Dialog(onDismissRequest = { pointEauTouche = null },
            properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
            FichePointEau(p, moi, suiviPointsEau, surSignaler = { g -> pointEauTouche = null; signalementPei = g to p },
                          surFermer = { pointEauTouche = null }, modifier = Modifier.padding(16.dp))
        }
    }
    signalementPei?.let { (genre, p) ->
        androidx.compose.ui.window.Dialog(onDismissRequest = { signalementPei = null },
            properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
            SignalerPointEau(modele, genre, p, moi, pointsEau, crises.firstOrNull { it.ouverte }?.id,
                             surFin = { signalementPei = null }, modifier = Modifier.padding(16.dp))
        }
    }
    destination?.let { d ->
        androidx.compose.ui.window.Dialog(onDismissRequest = { destination = null },
            properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
            AllerVers(d, moi, capGps, surArrivee = { modele.arriveSurLesLieux(d.dossier) }, surFermeture = { destination = null })
        }
    }
}

/** Ce qu'on peut créer à l'endroit touché, et sur quelle crise. */
@Composable
private fun CreerIci(crises: List<Crise>, surChoix: (GenreDepot, Crise) -> Unit, surAbandon: () -> Unit, modifier: Modifier = Modifier) {
    var choisie by remember(crises) { mutableStateOf(crises.singleOrNull()) }
    Surface(shape = MaterialTheme.shapes.large, shadowElevation = 6.dp, modifier = modifier.fillMaxWidth()) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Créer à cet endroit", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                TextButton(onClick = surAbandon) { Text("Annuler") }
            }
            if (crises.isEmpty()) {
                // Le serveur refuse tout dépôt hors d'une crise ouverte et suivie : on le dit ici plutôt qu'après la saisie.
                Text("Aucune crise ouverte n'accepte de dépôt pour l'instant.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                return@Column
            }
            if (crises.size > 1) {
                Text("Pour quelle crise ?", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    crises.forEach { c -> FilterChip(selected = choisie?.id == c.id, onClick = { choisie = c }, label = { Text(c.nom) }) }
                }
            } else {
                Text(crises.single().nom, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(8.dp))
            listOf(GenreDepot.DEMANDE to "Une demande d'aide", GenreDepot.SIGNALEMENT to "Un signalement", GenreDepot.OFFRE to "Une offre d'aide").forEach { (genre, nom) ->
                OutlinedButton(onClick = { choisie?.let { surChoix(genre, it) } }, enabled = choisie != null, modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) { Text(nom) }
            }
        }
    }
}

@Composable
private fun LigneMembre(membre: PositionMembre, surClic: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = surClic).padding(horizontal = 20.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(12.dp).clip(CircleShape).background(BleuNuit))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(membre.nom.ifBlank { "Membre" }, style = MaterialTheme.typography.bodyLarge)
            if (membre.equipes.isNotEmpty()) {
                Text(membre.equipes.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        // Une position vieille de deux heures n'est pas une position : on dit son âge.
        instantDe(membre.horodatage)?.let {
            Text(ilYA(it), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
