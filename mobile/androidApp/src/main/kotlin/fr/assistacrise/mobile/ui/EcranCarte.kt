package fr.assistacrise.mobile.ui

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
import fr.assistacrise.mobile.ServiceSuivi
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
private const val STYLE = """{"version":8,"sources":{"ign":{"type":"raster","tiles":["https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&FORMAT=image/png&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"],"tileSize":256,"maxzoom":19,"attribution":"© IGN"}},"layers":[{"id":"ign","type":"raster","source":"ign"}]}"""

private val FRANCE = LatLng(46.6, 2.4)

@SuppressLint("MissingPermission")   // chaque lecture est précédée de ServiceSuivi.autorise
@Composable
fun EcranCarte(modele: ModeleApplication) {
    val contexte = LocalContext.current
    val cycle = LocalLifecycleOwner.current.lifecycle
    val lien by modele.lien.collectAsStateWithLifecycle()
    val membres = modele.positions

    var autorise by remember { mutableStateOf(ServiceSuivi.autorise(contexte)) }
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
            m.setStyle(Style.Builder().fromJson(STYLE)) { style ->
                style.addSource(GeoJsonSource("membres"))
                style.addSource(GeoJsonSource("moi"))
                style.addLayer(CircleLayer("membres-points", "membres").withProperties(
                    circleRadius(8f), circleColor("#3c4d81"), circleStrokeColor("#ffffff"), circleStrokeWidth(2.5f)))
                style.addLayer(CircleLayer("moi-point", "moi").withProperties(
                    circleRadius(9f), circleColor("#2ea3f2"), circleStrokeColor("#ffffff"), circleStrokeWidth(3f)))
                carte = m
            }
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
    LaunchedEffect(carte, membres, moi) {
        val m = carte ?: return@LaunchedEffect
        val style = m.style ?: return@LaunchedEffect
        (style.getSource("membres") as? GeoJsonSource)?.setGeoJson(
            FeatureCollection.fromFeatures(membres.map { Feature.fromGeometry(Point.fromLngLat(it.longitude!!, it.latitude!!)) }),
        )
        (style.getSource("moi") as? GeoJsonSource)?.setGeoJson(
            FeatureCollection.fromFeatures(listOfNotNull(moi?.let { Feature.fromGeometry(Point.fromLngLat(it.longitude, it.latitude)) })),
        )
        val points = membres.map { LatLng(it.latitude!!, it.longitude!!) } + listOfNotNull(moi?.let { LatLng(it.latitude, it.longitude) })
        if (!cadree && points.isNotEmpty()) {
            cadree = true
            if (points.size == 1) m.moveCamera(CameraUpdateFactory.newLatLngZoom(points[0], 14.0))
            else m.moveCamera(CameraUpdateFactory.newLatLngBounds(LatLngBounds.Builder().includes(points).build(), 120))
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 16.dp, top = 12.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Carte", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
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
            Text(
                "© IGN", style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.align(Alignment.BottomEnd).padding(6.dp).background(MaterialTheme.colorScheme.surface.copy(alpha = 0.8f)).padding(horizontal = 4.dp),
            )
        }
        // Les noms sont dans la liste, pas sur la carte : toucher une ligne y conduit.
        if (membres.isNotEmpty()) {
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 190.dp)) {
                items(membres, key = { it.utilisateur }) { membre ->
                    LigneMembre(membre) {
                        carte?.animateCamera(CameraUpdateFactory.newLatLngZoom(LatLng(membre.latitude!!, membre.longitude!!), 15.0))
                    }
                    HorizontalDivider()
                }
            }
        } else {
            Text(
                "Aucun membre de vos équipes n'a partagé sa position ces trois dernières heures.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp),
            )
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
