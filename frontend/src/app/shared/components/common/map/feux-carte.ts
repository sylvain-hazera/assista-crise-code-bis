/** Feux en cours suivis par le satellite MTG, et potentiel d'orage de feu : ce que la carte en
 * dessine (fonctions pures, testées sans carte). */
import { Feature, FeatureCollection, Point } from 'geojson';
import { FeuSuivi, PotentielOrageFeu } from '../../../models/veille.model';

/** « 850 MW », « 3,3 GW ». */
export function libellePuissance(mw: number): string {
  if (mw >= 1000) return `${(mw / 1000).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} GW`;
  return `${Math.round(mw)} MW`;
}

/** Tendance sur la dernière heure de la courbe : rapport entre la dernière valeur et la moyenne
 * de l'heure qui précède. */
export function tendance(feu: FeuSuivi): 'hausse' | 'baisse' | 'stable' | null {
  const points = feu.courbe;
  if (points.length < 3) return null;
  const derniere = new Date(points[points.length - 1][0]).getTime();
  const avant = points.slice(0, -1).filter(p => derniere - new Date(p[0]).getTime() <= 60 * 60_000).map(p => p[1]);
  if (!avant.length) return null;
  const moyenne = avant.reduce((a, b) => a + b, 0) / avant.length;
  const rapport = points[points.length - 1][1] / Math.max(moyenne, 1);
  return rapport >= 1.5 ? 'hausse' : rapport <= 0.67 ? 'baisse' : 'stable';
}

/** Ce qui, autour d'un feu, mérite d'être signalé d'un mot (puces de la fiche et infobulle). */
export function signaux(feu: FeuSuivi): string[] {
  const ctx = feu.contexte || {};
  const liste: string[] = [];
  if (ctx.orage) {
    liste.push(ctx.orage.au_dessus ? 'orage au-dessus du feu' : `orage à ${ctx.orage.distance_km} km`);
    if (ctx.orage.rafale_descendante) liste.push('rafales descendantes (Doppler)');
  }
  if (ctx.eclairs_30_min) liste.push(`${ctx.eclairs_30_min} éclair${ctx.eclairs_30_min > 1 ? 's' : ''} en 30 min`);
  if (ctx.masque_par_nuage) liste.push('le nuage masque peut-être le feu');
  if (ctx.potentiel?.atteint_le_seuil) liste.push("assez puissant pour un orage de feu (nos estimations)");
  return liste;
}

function echapper(texte: string): string {
  return texte.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
}

export function infobulleFeu(feu: FeuSuivi): string {
  const heure = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  const lignes = [
    `<strong>Feu suivi par satellite — à confirmer</strong>`,
    feu.statut === 'actif'
      ? `${libellePuissance(feu.puissance_mw)} rayonnés à ${heure(feu.dernier_vu)} (maximum ${libellePuissance(feu.puissance_max_mw)} à ${heure(feu.instant_max)})`
      : `Plus vu depuis ${heure(feu.dernier_vu)} : éteint, ou caché par les nuages`,
    `Vu pour la première fois à ${heure(feu.premier_vu)}${feu.confirme ? '' : ', une seule image'}`,
    ...signaux(feu).map(s => `• ${echapper(s)}`),
    '<small>Source : EUMETSAT LSA SAF (satellite MTG), une image toutes les 10 minutes</small>',
  ];
  return lignes.join('<br>');
}

export function feuxVersGeoJSON(feux: FeuSuivi[]): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: feux.map((feu): Feature<Point> => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [feu.longitude, feu.latitude] },
      properties: {
        identifiant: feu.identifiant,
        puissance_mw: feu.puissance_mw,
        actif: feu.statut === 'actif',
        orage: !!feu.contexte?.orage,
        etiquette: feu.statut === 'actif' ? libellePuissance(feu.puissance_mw) : 'plus vu',
        infobulle: infobulleFeu(feu),
      },
    })),
  };
}

/** L'heure du potentiel à montrer d'entrée : la prochaine heure calculée (ou celle en cours, à
 * une heure et demie près), sinon la dernière. */
export function echeanceParDefaut(potentiel: PotentielOrageFeu, maintenant = Date.now()): string | null {
  const heures = potentiel.echeances.map(e => e.echeance);
  if (!heures.length) return null;
  return heures.find(h => new Date(h).getTime() >= maintenant - 90 * 60_000) ?? heures[heures.length - 1];
}

/** Points d'une courbe de puissance pour une petite courbe SVG (largeur × hauteur). */
export function cheminCourbe(feu: FeuSuivi, largeur: number, hauteur: number): string {
  const points = feu.courbe;
  if (points.length < 2) return '';
  const t0 = new Date(points[0][0]).getTime();
  const t1 = new Date(points[points.length - 1][0]).getTime();
  const maximum = Math.max(...points.map(p => p[1]), 1);
  return points.map((p, i) => {
    const x = t1 > t0 ? (new Date(p[0]).getTime() - t0) / (t1 - t0) * largeur : 0;
    const y = hauteur - p[1] / maximum * hauteur;
    return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}
