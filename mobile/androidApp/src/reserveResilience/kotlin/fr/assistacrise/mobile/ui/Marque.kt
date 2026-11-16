package fr.assistacrise.mobile.ui

import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

// Charte Réserve Résilience, telle que le serveur la connaît (migration 0199) :
// bleu nuit #3c4d81, bleu clair #2ea3f2, Quicksand pour les titres, Open Sans pour le texte.
val BleuNuit = Color(0xFF3C4D81)
val BleuClair = Color(0xFF2EA3F2)

val PaletteClaire = lightColorScheme(
    primary = BleuNuit,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDCE2F5),
    onPrimaryContainer = Color(0xFF1B2547),
    secondary = Color(0xFF14689F),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFD6ECFC),
    onSecondaryContainer = Color(0xFF0B3654),
    background = Color(0xFFF7F8FC),
    onBackground = Color(0xFF1A1D29),
    surface = Color.White,
    onSurface = Color(0xFF1A1D29),
    surfaceVariant = Color(0xFFE6E9F3),
    onSurfaceVariant = Color(0xFF4A5068),
    outline = Color(0xFF7C839C),
    error = Refus,
)

val PaletteSombre = darkColorScheme(
    primary = Color(0xFFAEBBE8),
    onPrimary = Color(0xFF16204A),
    primaryContainer = Color(0xFF2E3C68),
    onPrimaryContainer = Color(0xFFDCE2F5),
    secondary = Color(0xFF8CCBF7),
    onSecondary = Color(0xFF07304C),
    secondaryContainer = Color(0xFF12496F),
    onSecondaryContainer = Color(0xFFD6ECFC),
    background = Color(0xFF12141C),
    onBackground = Color(0xFFE4E6EF),
    surface = Color(0xFF1A1D29),
    onSurface = Color(0xFFE4E6EF),
    surfaceVariant = Color(0xFF2A2E3D),
    onSurfaceVariant = Color(0xFFC1C6D8),
    outline = Color(0xFF8B91A8),
)
