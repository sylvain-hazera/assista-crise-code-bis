package fr.assistacrise.mobile.domaine

/**
 * Export GPX des points de la carte (26/11/2026) : marqueurs reçus par la radio, nœuds radio,
 * ma position. Des points de passage (`wpt`), que lisent OsmAnd, les outils des SDIS, Google
 * Earth… Aucune donnée personnelle n'y est ajoutée : seulement ce que la carte montre.
 */
object Gpx {
    /** `instant` : date ISO 8601 en UTC (« 2026-11-26T18:30:00Z »), ou null. */
    data class Point(val nom: String, val latitude: Double, val longitude: Double, val description: String? = null,
                     val instant: String? = null, val symbole: String? = null)

    fun ecrire(points: List<Point>, nom: String): String = buildString {
        append("""<?xml version="1.0" encoding="UTF-8"?>""").append('\n')
        append("""<gpx version="1.1" creator="Assista-Crise" xmlns="http://www.topografix.com/GPX/1/1">""").append('\n')
        append("  <metadata><name>").append(echapper(nom)).append("</name></metadata>\n")
        points.forEach { p ->
            append("""  <wpt lat="${MarqueursRadio.cinqDecimales(p.latitude)}" lon="${MarqueursRadio.cinqDecimales(p.longitude)}">""")
            p.instant?.let { append("<time>").append(echapper(it)).append("</time>") }
            append("<name>").append(echapper(p.nom)).append("</name>")
            p.description?.let { append("<desc>").append(echapper(it)).append("</desc>") }
            p.symbole?.let { append("<sym>").append(echapper(it)).append("</sym>") }
            append("</wpt>\n")
        }
        append("</gpx>\n")
    }

    private fun echapper(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")
}
