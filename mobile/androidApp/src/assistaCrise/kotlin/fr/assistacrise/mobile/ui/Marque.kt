package fr.assistacrise.mobile.ui

import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

// Charte Assista-Crise, relevée sur son emblème : l'anthracite des deux arcs (#253941) et la
// sarcelle de la flamme (#1FB6BB).
//
// Les deux noms ci-dessous sont ceux que le reste de l'application emploie pour « la couleur
// foncée de la marque » et « sa couleur vive » : ils viennent de la première marque (bleu nuit,
// bleu clair), et les garder évite de toucher à tous les écrans pour une question de vocabulaire.
val BleuNuit = Color(0xFF253941)
val BleuClair = Color(0xFF1FB6BB)

val PaletteClaire = lightColorScheme(
    primary = BleuNuit,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD5E3E8),
    onPrimaryContainer = Color(0xFF12222A),
    // La sarcelle vive ne porte pas de texte blanc lisible : on la fonce pour les boutons.
    secondary = Color(0xFF0E7C80),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFCDEFF0),
    onSecondaryContainer = Color(0xFF063B3D),
    background = Color(0xFFF6F9FA),
    onBackground = Color(0xFF172126),
    surface = Color.White,
    onSurface = Color(0xFF172126),
    surfaceVariant = Color(0xFFE1EAED),
    onSurfaceVariant = Color(0xFF45565D),
    outline = Color(0xFF75878E),
    error = Refus,
)

val PaletteSombre = darkColorScheme(
    primary = Color(0xFFA9C5CF),
    onPrimary = Color(0xFF10232B),
    primaryContainer = Color(0xFF2B434D),
    onPrimaryContainer = Color(0xFFD5E3E8),
    secondary = Color(0xFF6FD6D9),
    onSecondary = Color(0xFF04393B),
    secondaryContainer = Color(0xFF0A5558),
    onSecondaryContainer = Color(0xFFCDEFF0),
    background = Color(0xFF101619),
    onBackground = Color(0xFFE1E8EB),
    surface = Color(0xFF172126),
    onSurface = Color(0xFFE1E8EB),
    surfaceVariant = Color(0xFF283439),
    onSurfaceVariant = Color(0xFFBFCDD2),
    outline = Color(0xFF86979D),
)
