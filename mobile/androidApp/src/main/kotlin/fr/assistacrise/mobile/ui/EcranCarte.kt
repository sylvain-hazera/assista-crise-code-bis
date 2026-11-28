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
import org.maplibre.android.style.layers.PropertyFactory.circleOpacity
import org.maplibre.android.style.sources.GeoJsonSource
import fr.assistacrise.mobile.donnees.DepotMeteo
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

/** Une couche que l'on peut masquer : ses calques MapLibre, et sa couleur pour la légende. */
internal class CoucheCarte(val cle: String, val libelle: String, val couleur: Long, val calques: List<String>,
                           /** Couche météo : masquée tant qu'on ne la coche pas, lue seulement avec Internet. */
                           val meteo: DepotMeteo.Couche? = null)

/** Ma position et le point touché restent toujours visibles. */
internal val COUCHES = listOf(
    CoucheCarte("dossiers", "Dossiers et interventions", 0xFFF59E0B, listOf("dossiers-points")),
    CoucheCarte("marqueurs", "Marqueurs du terrain", 0xFF111827, listOf("radio-marqueurs-points")),
    CoucheCarte("points", "Points clés (crise, manifestation)", 0xFF15803D, listOf("points-crise", "manif-points-cercles")),
    CoucheCarte("membres", "Membres des équipes", 0xFF3C4D81, listOf("membres-points")),
    CoucheCarte("noeuds", "Nœuds radio", 0xFF7C3AED, listOf("radio-noeuds-points")),
    CoucheCarte("pei", "Points d'eau incendie", 0xFF1D4ED8, listOf("pei-points")),
    CoucheCarte("zones", "Périmètres de crise", 0xFFB91C1C, listOf("zones-fond", "zones-bord")),
    // Météo (27/11/2026), avec Internet : les données publiques de notre serveur.
    CoucheCarte("meteo-pluie", "Pluie (radar)", 0xFF2563EB, listOf("meteo-pluie"), DepotMeteo.Couche.PLUIE),
    CoucheCarte("meteo-rafales", "Rafales prévues", 0xFF0891B2, listOf("meteo-rafales"), DepotMeteo.Couche.RAFALES),
    CoucheCarte("meteo-orages", "Orages (et couloir estimé)", 0xFFDC2626, listOf("meteo-orages-fond", "meteo-orages-bord", "meteo-couloirs"), DepotMeteo.Couche.ORAGES),
    CoucheCarte("meteo-eclairs", "Éclairs (dernière heure)", 0xFFEAB308, listOf("meteo-eclairs"), DepotMeteo.Couche.ECLAIRS),
)

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
    // Interventions annoncées par radio (📋, 26/11/2026) : sur la carte en violet, jusqu'au vrai dossier.
    val parRadio by modele.interventionsRadio.collectAsStateWithLifecycle()
    val parRadioSituees = parRadio.filter { it.annonce.situee }
    /** Le point maintenu du doigt : c'est là que se créera la demande, le signalement ou l'offre. */
    var lieuTouche by remember { mutableStateOf<LatLng?>(null) }
    val tousLesPoints by modele.pointsCrise.collectAsStateWithLifecycle()
    // Seulement la crise en cours, sinon celles de ma commune (27/11/2026) : plus les centres
    // d'accueil de toutes les crises ouvertes, à des centaines de kilomètres.
    val perimetre by modele.perimetreCarte.collectAsStateWithLifecycle()
    val idsPerimetre = perimetre.crises.map { it.id }.toSet()
    val points = tousLesPoints.filter { it.crise in idsPerimetre }
    // Points d'eau incendie (24/11/2026) : gardés sur le téléphone pour la carte hors réseau.
    val pointsEau by modele.pointsEau.collectAsStateWithLifecycle()
    val suiviPointsEau by modele.suiviPointsEau.collectAsStateWithLifecycle()
    var pointEauTouche by remember { mutableStateOf<fr.assistacrise.mobile.domaine.PointEau?>(null) }
    var signalementPei by remember { mutableStateOf<Pair<fr.assistacrise.mobile.domaine.GenreSignalementPei, fr.assistacrise.mobile.domaine.PointEau?>?>(null) }
    var destination by remember { mutableStateOf<Destination?>(null) }
    // La radio sur la carte (26/11/2026) : nœuds qui ont donné leur position, marqueurs d'incident.
    val positionsRadio by modele.positionsRadio.collectAsStateWithLifecycle()
    val marqueursRadio by modele.marqueursRadio.collectAsStateWithLifecycle()
    var noeudTouche by remember { mutableStateOf<ModeleApplication.PositionRadio?>(null) }
    var marqueurTouche by remember { mutableStateOf<ModeleApplication.MarqueurRadio?>(null) }
    var marqueurIci by remember { mutableStateOf<LatLng?>(null) }
    // Points clés des manifestations du jour (27/11/2026) : PC, signalisation, transit…
    val pointsManif by modele.pointsManifestation.collectAsStateWithLifecycle()
    var horsLigne by remember { mutableStateOf(false) }
    var listeRepliee by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    // Couches affichées (27/11/2026) : le choix est gardé d'une ouverture à l'autre.
    val reglages = remember { contexte.getSharedPreferences("carte", android.content.Context.MODE_PRIVATE) }
    var couchesMasquees by remember { mutableStateOf(reglages.getStringSet("couches-masquees", emptySet())!!.toSet()) }
    var menuCouches by remember { mutableStateOf(false) }
    // Couches météo cochées (aucune par défaut) ; ce qu'on en a lu ; où regarde la carte.
    var couchesMeteo by remember { mutableStateOf(reglages.getStringSet("couches-meteo", emptySet())!!.toSet()) }
    var meteo by remember { mutableStateOf<DepotMeteo.Resultat?>(null) }
    var emprise by remember { mutableStateOf<DepotMeteo.Emprise?>(null) }
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
                style.addSource(GeoJsonSource("radio-noeuds"))
                style.addSource(GeoJsonSource("radio-marqueurs"))
                style.addSource(GeoJsonSource("manif-points"))
                style.addSource(GeoJsonSource("meteo-orages"))
                style.addSource(GeoJsonSource("meteo-eclairs"))
                // La météo tout en dessous : les images du radar et des rafales viendront sous elle
                // (ajoutées à la première lecture), puis les orages et les éclairs.
                style.addLayer(FillLayer("meteo-orages-fond", "meteo-orages").withFilter(Expression.eq(Expression.get("nature"), "cellule")).withProperties(
                    fillColor(Expression.step(Expression.get("mmh"), Expression.color(android.graphics.Color.parseColor("#facc15")),
                        Expression.stop(10, Expression.color(android.graphics.Color.parseColor("#f97316"))),
                        Expression.stop(30, Expression.color(android.graphics.Color.parseColor("#dc2626"))),
                        Expression.stop(50, Expression.color(android.graphics.Color.parseColor("#a21caf"))))),
                    fillOpacity(0.35f), org.maplibre.android.style.layers.PropertyFactory.visibility(org.maplibre.android.style.layers.Property.NONE)))
                style.addLayer(LineLayer("meteo-orages-bord", "meteo-orages").withFilter(Expression.eq(Expression.get("nature"), "cellule")).withProperties(
                    lineColor("#7f1d1d"), lineWidth(1.5f), org.maplibre.android.style.layers.PropertyFactory.visibility(org.maplibre.android.style.layers.Property.NONE)))
                style.addLayer(LineLayer("meteo-couloirs", "meteo-orages").withFilter(Expression.eq(Expression.get("nature"), "couloir")).withProperties(
                    lineColor("#7f1d1d"), lineWidth(1.5f), org.maplibre.android.style.layers.PropertyFactory.lineDasharray(arrayOf(2f, 2f)),
                    org.maplibre.android.style.layers.PropertyFactory.visibility(org.maplibre.android.style.layers.Property.NONE)))
                style.addLayer(CircleLayer("meteo-eclairs", "meteo-eclairs").withProperties(
                    circleRadius(4f), circleColor("#facc15"), circleStrokeColor("#713f12"), circleStrokeWidth(1f),
                    circleOpacity(Expression.interpolate(Expression.linear(), Expression.get("age_min"), Expression.stop(0, 1f), Expression.stop(60, 0.3f))),
                    org.maplibre.android.style.layers.PropertyFactory.visibility(org.maplibre.android.style.layers.Property.NONE)))
                // Dessous d'abord : les périmètres de crise, puis les dossiers, puis les personnes.
                style.addLayer(FillLayer("zones-fond", "zones").withProperties(fillColor("#b91c1c"), fillOpacity(0.10f)))
                style.addLayer(LineLayer("zones-bord", "zones").withProperties(lineColor("#b91c1c"), lineWidth(2f)))
                // Points d'eau incendie, sous les dossiers : rouge indisponible, orange défaut,
                // bleu clair OpenStreetMap (indicatif), bleu SDIS ou validé par la commune.
                style.addLayer(CircleLayer("pei-points", "pei").withProperties(
                    circleRadius(6f), circleStrokeColor("#ffffff"), circleStrokeWidth(1.5f),
                    circleColor(Expression.switchCase(
                        Expression.eq(Expression.get("actif"), Expression.literal("oui")), Expression.color(android.graphics.Color.parseColor("#15803d")),
                        Expression.eq(Expression.get("etat"), Expression.literal("INDISPONIBLE")), Expression.color(android.graphics.Color.parseColor("#dc2626")),
                        Expression.eq(Expression.get("etat"), Expression.literal("DEFAUT")), Expression.color(android.graphics.Color.parseColor("#f59e0b")),
                        Expression.eq(Expression.get("source"), Expression.literal("OSM")), Expression.color(android.graphics.Color.parseColor("#60a5fa")),
                        Expression.color(android.graphics.Color.parseColor("#1d4ed8"))))))
                // Forme ET couleur : un dossier est un point orange cerclé de sombre, plus gros
                // qu'une personne ; l'urgent est rouge. La liste sous la carte les nomme.
                style.addLayer(CircleLayer("dossiers-points", "dossiers").withProperties(
                    circleRadius(11f), circleStrokeColor("#1a1d29"), circleStrokeWidth(2.5f),
                    circleColor(Expression.match(Expression.get("urgent"),
                        Expression.literal("oui"), Expression.color(android.graphics.Color.parseColor("#dc2626")),
                        Expression.literal("radio"), Expression.color(android.graphics.Color.parseColor("#7c3aed")),
                        Expression.color(android.graphics.Color.parseColor("#f59e0b"))))))
                // Les points de la crise (accueil, PC, rassemblement) : verts, carrés de bord.
                style.addLayer(CircleLayer("points-crise", "points").withProperties(
                    circleRadius(9f), circleColor("#15803d"), circleStrokeColor("#ffffff"), circleStrokeWidth(2.5f)))
                // Points clés d'une manifestation : verts comme ceux d'une crise, le PC en rouge.
                style.addLayer(CircleLayer("manif-points-cercles", "manif-points").withProperties(
                    circleRadius(8f), circleStrokeColor("#ffffff"), circleStrokeWidth(2.5f),
                    circleColor(Expression.match(Expression.get("pc"), Expression.literal("oui"),
                        Expression.color(android.graphics.Color.parseColor("#dc2626")), Expression.color(android.graphics.Color.parseColor("#15803d"))))))
                // Nœuds radio : petits, violets, estompés quand la position date de plus d'une heure.
                style.addLayer(CircleLayer("radio-noeuds-points", "radio-noeuds").withProperties(
                    circleRadius(6f), circleColor("#7c3aed"), circleStrokeColor("#ffffff"), circleStrokeWidth(1.5f),
                    circleOpacity(Expression.match(Expression.get("recent"), Expression.literal("oui"), Expression.literal(1f), Expression.literal(0.45f)))))
                // Marqueurs d'incident reçus par la radio : gros, cerclés de noir, couleur selon le genre.
                style.addLayer(CircleLayer("radio-marqueurs-points", "radio-marqueurs").withProperties(
                    circleRadius(10f), circleStrokeColor("#111827"), circleStrokeWidth(2.5f),
                    circleColor(Expression.match(Expression.get("emoji"),
                        Expression.literal("🔥"), Expression.color(android.graphics.Color.parseColor("#dc2626")),
                        Expression.literal("⛔"), Expression.color(android.graphics.Color.parseColor("#dc2626")),
                        Expression.literal("✅"), Expression.color(android.graphics.Color.parseColor("#16a34a")),
                        Expression.literal("🧑"), Expression.color(android.graphics.Color.parseColor("#16a34a")),
                        Expression.literal("🚑"), Expression.color(android.graphics.Color.parseColor("#16a34a")),
                        Expression.literal("🌊"), Expression.color(android.graphics.Color.parseColor("#0284c7")),
                        Expression.literal("🏕️"), Expression.color(android.graphics.Color.parseColor("#a16207")),
                        Expression.color(android.graphics.Color.parseColor("#f59e0b"))))))
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
                val marqueur = m.queryRenderedFeatures(ecran, "radio-marqueurs-points").firstOrNull()?.getNumberProperty("rang")?.toInt()
                val noeud = m.queryRenderedFeatures(ecran, "radio-noeuds-points").firstOrNull()?.getStringProperty("cle")
                val pointManif = m.queryRenderedFeatures(ecran, "manif-points-cercles").firstOrNull()?.getNumberProperty("rang")?.toInt()
                when {
                    touche != null && touche.startsWith("radio:") -> {
                        modele.interventionsRadio.value.firstOrNull { "radio:" + it.annonce.numero == touche }?.let(modele::decrireInterventionRadio); true
                    }
                    touche != null -> { modele.ouvrirDossier(touche); true }
                    marqueur != null -> { marqueurTouche = modele.marqueursRadio.value.getOrNull(marqueur); true }
                    pointManif != null -> {
                        modele.pointsManifestation.value.getOrNull(pointManif)?.let { p -> destination = Destination("${p.nom} (${p.genre})", p.latitude, p.longitude, "point") }
                        true
                    }
                    noeud != null -> { noeudTouche = modele.positionsRadio.value.firstOrNull { it.cleConversation == noeud }; true }
                    pointCrise != null -> {
                        points.firstOrNull { it.id == pointCrise }?.let { p -> destination = Destination(p.nom, p.latitude!!, p.longitude!!, "point") }
                        true
                    }
                    pei != null -> { pointEauTouche = modele.pointsEau.value.firstOrNull { it.id == pei }; true }
                    else -> { lieuTouche = null; false }
                }
            }
            m.addOnMapLongClickListener { point -> lieuTouche = point; true }
            // Où regarde la carte, arrondi : un petit déplacement ne relit pas la météo.
            m.addOnCameraIdleListener {
                val b = m.projection.visibleRegion.latLngBounds
                fun a(x: Double) = kotlin.math.round(x * 10) / 10
                emprise = DepotMeteo.Emprise.de(a(b.longitudeWest) - 0.1, a(b.latitudeSouth) - 0.1, a(b.longitudeEast) + 0.1, a(b.latitudeNorth) + 0.1)
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
    // Une couche masquée ne se dessine plus, et ne répond plus au toucher.
    LaunchedEffect(carte, couchesMasquees) {
        val style = carte?.style ?: return@LaunchedEffect
        for (couche in COUCHES) {
            val masquee = if (couche.meteo != null) couche.cle !in couchesMeteo else couche.cle in couchesMasquees
            val etat = if (masquee) org.maplibre.android.style.layers.Property.NONE else org.maplibre.android.style.layers.Property.VISIBLE
            couche.calques.forEach { id -> style.getLayer(id)?.setProperties(org.maplibre.android.style.layers.PropertyFactory.visibility(etat)) }
        }
    }

    // Météo (27/11/2026) : relue toutes les deux minutes tant qu'une couche est cochée, et quand
    // la carte se déplace. Sans Internet, les couches se vident plutôt que de montrer du périmé.
    LaunchedEffect(carte, couchesMeteo, emprise) {
        val m = carte ?: return@LaunchedEffect
        val voulues = COUCHES.filter { it.cle in couchesMeteo }.mapNotNull { it.meteo }.toSet()
        if (voulues.isEmpty()) { meteo = null; poserMeteo(m, DepotMeteo.Resultat()); return@LaunchedEffect }
        val zone = emprise ?: return@LaunchedEffect
        while (true) {
            val r = modele.lireMeteo(voulues, zone)
            meteo = r
            poserMeteo(m, r)
            kotlinx.coroutines.delay(120_000)
        }
    }

    // Les points suivent les données ; la carte ne se recadre qu'une fois, pour ne pas
    // arracher la vue des mains de quelqu'un qui est en train de la déplacer.
    LaunchedEffect(carte, pointsEau) {
        val style = carte?.style ?: return@LaunchedEffect
        (style.getSource("pei") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(pointsEau.map { p ->
            Feature.fromGeometry(Point.fromLngLat(p.longitude, p.latitude)).apply {
                addStringProperty("id", p.id.toString()); addStringProperty("etat", p.etat); addStringProperty("source", p.source)
                addStringProperty("actif", if (p.actifCrise) "oui" else "non")
            }
        }))
    }

    LaunchedEffect(carte, pointsManif) {
        val style = carte?.style ?: return@LaunchedEffect
        (style.getSource("manif-points") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(pointsManif.mapIndexed { i, p ->
            Feature.fromGeometry(Point.fromLngLat(p.longitude, p.latitude)).apply { addNumberProperty("rang", i); addStringProperty("pc", if (p.pc) "oui" else "non") }
        }))
    }

    LaunchedEffect(carte, positionsRadio, marqueursRadio) {
        val style = carte?.style ?: return@LaunchedEffect
        val recent = System.currentTimeMillis() / 1000 - 3600
        (style.getSource("radio-noeuds") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(positionsRadio.map { p ->
            Feature.fromGeometry(Point.fromLngLat(p.longitude, p.latitude)).apply {
                addStringProperty("cle", p.cleConversation); addStringProperty("recent", if ((p.vuS ?: 0) >= recent) "oui" else "non")
            }
        }))
        (style.getSource("radio-marqueurs") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(marqueursRadio.mapIndexed { i, r ->
            Feature.fromGeometry(Point.fromLngLat(r.marqueur.longitude, r.marqueur.latitude)).apply {
                addNumberProperty("rang", i); addStringProperty("emoji", r.marqueur.emoji)
            }
        }))
    }

    LaunchedEffect(carte, membres, moi, situes, parRadioSituees, crises, lieuTouche, points) {
        val m = carte ?: return@LaunchedEffect
        val style = m.style ?: return@LaunchedEffect
        (style.getSource("points") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(points.map { p ->
            Feature.fromGeometry(Point.fromLngLat(p.longitude!!, p.latitude!!)).apply { addStringProperty("id", p.id) }
        }))
        (style.getSource("dossiers") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(situes.map { d ->
            Feature.fromGeometry(Point.fromLngLat(d.longitude!!, d.latitude!!)).apply {
                addStringProperty("id", d.id); addStringProperty("urgent", if (d.priorite == "URGENTE") "oui" else "non")
            }
        } + parRadioSituees.map { i ->
            Feature.fromGeometry(Point.fromLngLat(i.annonce.longitude!!, i.annonce.latitude!!)).apply {
                addStringProperty("id", "radio:" + i.annonce.numero); addStringProperty("urgent", "radio")
            }
        }))
        (style.getSource("zones") as? GeoJsonSource)?.setGeoJson(FeatureCollection.fromFeatures(crises.filter { it.id in idsPerimetre }.mapNotNull { c ->
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
        // Deux lignes (27/11/2026) : le titre et le lien, puis les gestes, qui reviennent à la ligne
        // sur un petit écran — sur une seule, « Carte » s'écrasait lettre par lettre.
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 16.dp, top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Carte", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            PastilleLien(lien)
        }
        FlowRow(Modifier.fillMaxWidth().padding(start = 8.dp, end = 8.dp, bottom = 4.dp)) {
            TextButton(onClick = { signalementPei = fr.assistacrise.mobile.domaine.GenreSignalementPei.NOUVEAU to null }) { Text("Point d'eau") }
            Box {
                TextButton(onClick = { menuCouches = true }) {
                    val dessus = COUCHES.filter { it.meteo == null }
                    Text(if (couchesMasquees.isEmpty()) "Couches ▾" else "Couches (${dessus.size - couchesMasquees.size}/${dessus.size}) ▾")
                }
                androidx.compose.material3.DropdownMenu(expanded = menuCouches, onDismissRequest = { menuCouches = false }) {
                    COUCHES.filter { it.meteo == null }.forEach { couche ->
                        val visible = couche.cle !in couchesMasquees
                        androidx.compose.material3.DropdownMenuItem(
                            text = { Text(couche.libelle) },
                            leadingIcon = { androidx.compose.material3.Checkbox(checked = visible, onCheckedChange = null) },
                            trailingIcon = { Box(Modifier.size(12.dp).clip(CircleShape).background(androidx.compose.ui.graphics.Color(couche.couleur))) },
                            onClick = {
                                couchesMasquees = if (visible) couchesMasquees + couche.cle else couchesMasquees - couche.cle
                                reglages.edit().putStringSet("couches-masquees", couchesMasquees).apply()
                            },
                        )
                    }
                    if (couchesMasquees.isNotEmpty()) {
                        HorizontalDivider()
                        androidx.compose.material3.DropdownMenuItem(text = { Text("Tout afficher") }, onClick = {
                            couchesMasquees = emptySet()
                            reglages.edit().putStringSet("couches-masquees", emptySet()).apply()
                        })
                    }
                    HorizontalDivider()
                    Text("Météo (avec Internet)", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp))
                    COUCHES.filter { it.meteo != null }.forEach { couche ->
                        val cochee = couche.cle in couchesMeteo
                        androidx.compose.material3.DropdownMenuItem(
                            text = { Text(couche.libelle) },
                            leadingIcon = { androidx.compose.material3.Checkbox(checked = cochee, onCheckedChange = null) },
                            trailingIcon = { Box(Modifier.size(12.dp).clip(CircleShape).background(androidx.compose.ui.graphics.Color(couche.couleur))) },
                            onClick = {
                                couchesMeteo = if (cochee) couchesMeteo - couche.cle else couchesMeteo + couche.cle
                                reglages.edit().putStringSet("couches-meteo", couchesMeteo).apply()
                            },
                        )
                    }
                }
            }
            TextButton(onClick = { modele.ouvrirVeille() }) { Text("Veille") }
            TextButton(onClick = { horsLigne = true }) { Text("Télécharger pour le hors-ligne") }
            if (marqueursRadio.isNotEmpty() || positionsRadio.isNotEmpty()) {
                TextButton(onClick = { partagerGpx(contexte, marqueursRadio, positionsRadio, moi) }) { Text("GPX") }
            }
        }
        // La carte de la zone en cours, proposée en données mobiles (en Wi-Fi, elle se télécharge seule).
        modele.propositionZone?.let { (_, octets) ->
            Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.secondaryContainer).padding(horizontal = 16.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("Carte de la zone en cours pour le hors-ligne : environ ${fr.assistacrise.mobile.domaine.CartesEmbarquees.tailleLisible(octets)} (données mobiles).",
                    style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                TextButton(onClick = { modele.telechargerZone() }) { Text("Télécharger") }
            }
        }
        if (couchesMeteo.isNotEmpty()) meteo?.let { r ->
            Text(resumeMeteo(r), style = MaterialTheme.typography.labelSmall,
                color = if (r.injoignable || r.manques.isNotEmpty()) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp))
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
                    Column {
                        CreerIci(
                            crises.filter { it.accepteLesDepots },
                            surChoix = { genre, crise -> lieuTouche = null; modele.ouvrirDepot(genre, crise, Releve(lieu.latitude, lieu.longitude, System.currentTimeMillis(), 0f)) },
                            surAbandon = { lieuTouche = null },
                            modifier = Modifier.padding(16.dp),
                        )
                        // Sans réseau, la radio porte un marqueur jusqu'aux équipes (format MeshCore SAR).
                        // Seulement en phase de crise ou de manifestation, et rattaché à l'une ou à
                        // l'autre (28/11/2026).
                        if (modele.marqueurPossible(lieu.latitude, lieu.longitude)) {
                            Button(onClick = { marqueurIci = lieu; lieuTouche = null }, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                                Text("Poser un marqueur (feu, route coupée…)")
                            }
                        } else {
                            Surface(shape = MaterialTheme.shapes.medium, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                                Text("Cet endroit n'est dans la zone d'aucune crise ni manifestation en cours : pas de marqueur ici.",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(12.dp))
                            }
                        }
                    }
                }
            }
            Text(
                "© IGN", style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.align(Alignment.BottomEnd).padding(6.dp).background(MaterialTheme.colorScheme.surface.copy(alpha = 0.8f)).padding(horizontal = 4.dp),
            )
        }
        // La liste se replie vers le bas (27/11/2026) : la carte prend alors toute la hauteur.
        val nbLignes = points.size + pointsManif.size + situes.size + membres.size
        Row(
            Modifier.fillMaxWidth().clickable { listeRepliee = !listeRepliee }
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .padding(start = 20.dp, end = 16.dp, top = 8.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(if (nbLignes > 0) "Points, dossiers et équipes ($nbLignes)" else "Aide de la carte",
                style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            Text(if (listeRepliee) "Afficher ▴" else "Masquer ▾", style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary)
        }
        if (!listeRepliee) {
            Text(
                "Maintenez le doigt sur la carte pour y créer une demande, un signalement, une offre d'aide ou, pendant une crise ou une manifestation, un marqueur." +
                    if (positionsRadio.isNotEmpty() || marqueursRadio.isNotEmpty() || pointsManif.isNotEmpty())
                        " En violet : nœuds radio ; cerclés de noir : marqueurs du terrain ; verts : points clés (PC de manifestation en rouge)." else "",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
            )
            // Les noms sont dans la liste, pas sur la carte : toucher une ligne y conduit.
            if (membres.isNotEmpty() || situes.isNotEmpty() || points.isNotEmpty() || pointsManif.isNotEmpty()) {
                // « Autour de moi » : les points de la crise en cours et ceux de la manifestation du
                // jour, du plus proche au plus loin.
                val destinations = points.map { Destination(it.nom, it.latitude!!, it.longitude!!, it.type ?: "Point") } +
                    pointsManif.map { Destination(it.nom, it.latitude, it.longitude, "${it.genre} · ${it.manifestation}") }
                val autour = moi?.let { r -> Navigation.autourDe(r.latitude, r.longitude, destinations) } ?: destinations.map { it to null }
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
    marqueurIci?.let { lieu ->
        androidx.compose.ui.window.Dialog(onDismissRequest = { marqueurIci = null },
            properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
            EnvoyerMarqueur(lieu, modele.destinationsMarqueur(), modele.rattachementsMarqueur(lieu.latitude, lieu.longitude),
                            modele.rattachementPropose(lieu.latitude, lieu.longitude),
                            surEnvoi = { cles, m, r -> modele.envoyerMarqueur(cles, m, r); marqueurIci = null },
                            surAbandon = { marqueurIci = null }, modifier = Modifier.padding(16.dp))
        }
    }
    marqueurTouche?.let { r ->
        val mq = r.marqueur
        androidx.compose.material3.AlertDialog(onDismissRequest = { marqueurTouche = null },
            title = { Text("${mq.emoji} ${fr.assistacrise.mobile.domaine.MarqueursRadio.libelleDe(mq)}") },
            text = {
                Column {
                    fr.assistacrise.mobile.domaine.MarqueursRadio.noteLibre(mq)?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
                    Text("De ${r.auteur}, ${ilYA(r.horodatage)} · ${r.source}", style = MaterialTheme.typography.bodySmall)
                    Text("${"%.5f".format(java.util.Locale.ROOT, mq.latitude)}, ${"%.5f".format(java.util.Locale.ROOT, mq.longitude)}", style = MaterialTheme.typography.bodySmall)
                    // Une route : son état se change d'ici, par la radio et la plateforme (27/11/2026).
                    if (fr.assistacrise.mobile.domaine.MarqueursRadio.estRoute(mq.emoji)) {
                        Text("Changer l'état de la route", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(top = 8.dp))
                        fr.assistacrise.mobile.domaine.MarqueursRadio.ETATS_ROUTE.forEach { e ->
                            OutlinedButton(enabled = e != fr.assistacrise.mobile.domaine.MarqueursRadio.etatDe(mq), onClick = { modele.changerEtatRoute(r, e); marqueurTouche = null },
                                modifier = Modifier.fillMaxWidth()) { Text("${e.emoji} ${e.libelle}") }
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { destination = Destination(fr.assistacrise.mobile.domaine.MarqueursRadio.libelleDe(mq), mq.latitude, mq.longitude, "Marqueur"); marqueurTouche = null }) { Text("Aller") } },
            dismissButton = { if (r.cleConversation.isNotBlank()) TextButton(onClick = { modele.ouvrirConversationRadio(r.cleConversation); marqueurTouche = null }) { Text("Conversation") } },
        )
    }
    noeudTouche?.let { n ->
        androidx.compose.material3.AlertDialog(onDismissRequest = { noeudTouche = null },
            title = { Text(n.nom) },
            text = { Text("${n.genre} ${n.protocole.libelle} · position ${n.vuS?.let { ilYA(it * 1000) } ?: "d'âge inconnu"}", style = MaterialTheme.typography.bodyMedium) },
            confirmButton = { TextButton(onClick = { destination = Destination(n.nom, n.latitude, n.longitude, "Radio"); noeudTouche = null }) { Text("Aller") } },
            dismissButton = { TextButton(onClick = { modele.ouvrirConversationRadio(n.cleConversation); noeudTouche = null }) { Text("Message") } },
        )
    }
    destination?.let { d ->
        androidx.compose.ui.window.Dialog(onDismissRequest = { destination = null },
            properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
            AllerVers(d, moi, capGps, surArrivee = { modele.arriveSurLesLieux(d.dossier) }, surFermeture = { destination = null })
        }
    }
}

/** Exporte en GPX ce que la carte montre de la radio (marqueurs, nœuds) et ma position, puis
 * propose de le partager (courriel, OsmAnd, messagerie…). Le fichier est remplacé au suivant. */
private fun partagerGpx(contexte: android.content.Context, marqueurs: List<ModeleApplication.MarqueurRadio>,
                        noeuds: List<ModeleApplication.PositionRadio>, moi: Releve?) {
    fun iso(ms: Long) = java.time.Instant.ofEpochMilli(ms).truncatedTo(java.time.temporal.ChronoUnit.SECONDS).toString()
    val points = marqueurs.map { r ->
        val mq = r.marqueur
        fr.assistacrise.mobile.domaine.Gpx.Point("${mq.emoji} ${fr.assistacrise.mobile.domaine.MarqueursRadio.libelleDe(mq)}", mq.latitude, mq.longitude,
            listOfNotNull(mq.note, "de ${r.auteur}").joinToString(" · "), iso(r.horodatage), "Flag")
    } + noeuds.map { n ->
        fr.assistacrise.mobile.domaine.Gpx.Point(n.nom, n.latitude, n.longitude, "${n.genre} ${n.protocole.libelle}", n.vuS?.let { iso(it * 1000) }, "Radio Beacon")
    } + listOfNotNull(moi?.let { fr.assistacrise.mobile.domaine.Gpx.Point("Ma position", it.latitude, it.longitude, null, iso(it.instant)) })
    val dossier = java.io.File(contexte.cacheDir, "partages").apply { mkdirs() }
    val fichier = java.io.File(dossier, "carte-radio.gpx")
    fichier.writeText(fr.assistacrise.mobile.domaine.Gpx.ecrire(points, "Carte radio " + iso(System.currentTimeMillis())))
    val uri = androidx.core.content.FileProvider.getUriForFile(contexte, "${contexte.packageName}.prises", fichier)
    val envoi = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
        type = "application/gpx+xml"
        putExtra(android.content.Intent.EXTRA_STREAM, uri)
        addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    contexte.startActivity(android.content.Intent.createChooser(envoi, "Partager la carte (GPX)"))
}

/** Un marqueur d'incident envoyé par la radio, à l'endroit touché : genre, note, conversation. */
@Composable
private fun EnvoyerMarqueur(lieu: LatLng, destinations: List<Pair<String, String>>,
                            rattachements: List<fr.assistacrise.mobile.domaine.Rattachement>,
                            propose: fr.assistacrise.mobile.domaine.Rattachement?,
                            surEnvoi: (List<String>, fr.assistacrise.mobile.domaine.MarqueursRadio.Marqueur, fr.assistacrise.mobile.domaine.Rattachement) -> Unit,
                            surAbandon: () -> Unit, modifier: Modifier = Modifier) {
    var genre by remember { mutableStateOf(fr.assistacrise.mobile.domaine.MarqueursRadio.GENRES.first()) }
    // Toujours rattaché à une crise ouverte ou à une manifestation en cours (28/11/2026).
    var rattache by remember(rattachements) { mutableStateOf(propose ?: rattachements.singleOrNull()) }
    var note by remember { mutableStateOf("") }
    // Plusieurs canaux à la fois (27/11/2026), MeshCore et Meshtastic : le canal de l'équipe coché d'office.
    var cles by remember { mutableStateOf(listOfNotNull(destinations.firstOrNull()?.first).toSet()) }
    Surface(shape = MaterialTheme.shapes.large, shadowElevation = 6.dp, modifier = modifier.fillMaxWidth()) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Poser un marqueur", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                TextButton(onClick = surAbandon) { Text("Annuler") }
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                fr.assistacrise.mobile.domaine.MarqueursRadio.GENRES.forEach { g ->
                    FilterChip(selected = genre == g, onClick = { genre = g }, label = { Text("${g.emoji} ${g.libelle}") })
                }
            }
            androidx.compose.material3.OutlinedTextField(note, { note = it.take(80) }, label = { Text("Précision (facultatif)") }, singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
            if (rattachements.size > 1) {
                Text("Pour quelle crise ou manifestation ?", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    rattachements.forEach { r ->
                        FilterChip(selected = rattache?.cle == r.cle, onClick = { rattache = r },
                            label = { Text((if (r.crise != null) "Crise · " else "Manifestation · ") + r.nom) })
                    }
                }
            } else rattachements.singleOrNull()?.let { r ->
                Text((if (r.crise != null) "Crise : " else "Manifestation : ") + r.nom, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp))
            }
            Text(if (destinations.isEmpty()) "Aucune radio prête : le marqueur part par le réseau, vers la plateforme qui le relaie par la radio."
                 else "Sur quels canaux radio ? Cochez-en autant qu'il faut, MeshCore et Meshtastic (avec du réseau, il part aussi vers la plateforme).",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 8.dp))
            destinations.forEach { (k, libelle) ->
                val coche = k in cles
                fun basculer() { cles = if (coche) cles - k else cles + k }
                Row(Modifier.fillMaxWidth().clickable { basculer() }.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.material3.Checkbox(checked = coche, onCheckedChange = { basculer() })
                    Text(libelle, style = MaterialTheme.typography.bodyMedium)
                }
            }
            Text("Tous ceux qui ont ces canaux le verront : n'y mettez aucun nom de personne.", style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
            Button(onClick = {
                val r = rattache ?: return@Button
                // Une route : son sens ouvre la note (« 1 sens · arbre en travers »).
                surEnvoi(destinations.map { it.first }.filter { it in cles }, fr.assistacrise.mobile.domaine.MarqueursRadio.Marqueur(genre.emoji, lieu.latitude, lieu.longitude,
                    fr.assistacrise.mobile.domaine.MarqueursRadio.noteDeRoute(genre.precision, note)), r)
            }, enabled = rattache != null, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
                Text(when (cles.size) { 0 -> "Envoyer (par le réseau seulement)"; 1 -> "Envoyer"; else -> "Envoyer sur ${cles.size} canaux" })
            }
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

/** Pose sur la carte ce que la météo a donné ; une couche non lue est vidée. */
private fun poserMeteo(m: MapLibreMap, r: DepotMeteo.Resultat) {
    val style = m.style ?: return
    val vide = FeatureCollection.fromFeatures(emptyList())
    (style.getSource("meteo-orages") as? GeoJsonSource)?.let { s -> r.orages?.let { s.setGeoJson(it) } ?: s.setGeoJson(vide) }
    (style.getSource("meteo-eclairs") as? GeoJsonSource)?.let { s -> r.eclairs?.let { s.setGeoJson(it) } ?: s.setGeoJson(vide) }
    poserImage(style, "meteo-pluie", r.pluie, 0.7f)
    poserImage(style, "meteo-rafales", r.rafales, 0.6f)
}

/** Une image géoréférencée (radar, rafales), sous la météo vectorielle et tout le reste. La couche
 * est créée à la première image ; sans image, elle est masquée. */
private fun poserImage(style: Style, id: String, image: DepotMeteo.ImageMeteo?, opacite: Float) {
    val couche = style.getLayer(id)
    if (image == null) {
        (style.getSource(id) as? org.maplibre.android.style.sources.ImageSource)?.let { style.removeLayer(id); style.removeSource(it) }
        return
    }
    val bitmap = android.graphics.BitmapFactory.decodeByteArray(image.octets, 0, image.octets.size) ?: return
    val (hg, hd, bd, bg) = image.coins.map { (lon, lat) -> LatLng(lat, lon) }
    val quad = org.maplibre.android.geometry.LatLngQuad(hg, hd, bd, bg)
    val source = style.getSource(id) as? org.maplibre.android.style.sources.ImageSource
    if (source == null) {
        style.addSource(org.maplibre.android.style.sources.ImageSource(id, quad, bitmap))
        // Les rafales sous la pluie, les deux sous les orages.
        val dessous = if (id == "meteo-rafales" && style.getLayer("meteo-pluie") != null) "meteo-pluie" else "meteo-orages-fond"
        style.addLayerBelow(org.maplibre.android.style.layers.RasterLayer(id, id).withProperties(
            org.maplibre.android.style.layers.PropertyFactory.rasterOpacity(opacite)), dessous)
    } else {
        source.setCoordinates(quad)
        source.setImage(bitmap)
        if (couche == null) style.addLayerBelow(org.maplibre.android.style.layers.RasterLayer(id, id), "meteo-orages-fond")
    }
}

/** « Pluie 22:35 · rafales 22:45 · 2 orages · 37 éclairs — Météo-France, EUMETSAT ». */
private fun resumeMeteo(r: DepotMeteo.Resultat): String {
    if (r.injoignable) return "Météo indisponible : pas d'Internet (les couches météo restent vides)."
    fun h(iso: String) = runCatching {
        java.time.OffsetDateTime.parse(iso).atZoneSameInstant(java.time.ZoneId.systemDefault()).toLocalTime().toString().take(5)
    }.getOrDefault("?")
    val parties = listOfNotNull(
        r.pluie?.let { "pluie observée à ${h(it.heure)}" },
        r.rafales?.let { "rafales prévues pour ${h(it.heure)}" },
        r.orages?.let { if (r.nombreCellules == 0) "aucun orage dans la vue" else "${r.nombreCellules} orage" + if (r.nombreCellules > 1) "s" else "" },
        r.eclairs?.let { "${r.nombreEclairs} éclair" + (if (r.nombreEclairs > 1) "s" else "") + " en une heure" },
    )
    val manque = if (r.manques.isEmpty()) "" else " · non lu : " + r.manques.joinToString(", ")
    val sources = if (r.sources.isEmpty()) "" else " — " + r.sources.joinToString(", ")
    return "Météo : " + parties.joinToString(" · ").ifEmpty { "rien à afficher" } + manque + sources
}
