import type { Polygon } from "geojson";

export interface Zone {
  id: string;
  institution: string;
  institution_nom?: string | null;
  nom: string;
  description?: string | null;
  communes: string[];
  zone_precise?: string | null;          // WKT en écriture
  zone_precise_geojson?: Polygon | null; // GeoJSON natif en lecture
  actif: boolean;
}

export interface ZonePayload {
  nom: string;
  description?: string;
  communes?: string[];
  zone_precise?: string | null;
  institution?: string;
}

/** Une zone, avec le libellé à afficher dans une liste déroulante.
 *
 * `libelle` vaut le nom seul quand il est unique, et « nom — institution » quand il ne l'est
 * pas. Chaque collectivité reçoit automatiquement une zone « Mon territoire » (voir
 * `_assurer_zone_mon_territoire` côté serveur) : dès qu'on voit les zones de plusieurs
 * institutions — un administrateur, ou quelqu'un rattaché à une mairie ET à son EPCI — le
 * sélecteur affichait « Mon territoire » six fois de suite, sans rien pour les distinguer
 * (signalé le 12/11/2026). */
export type ZoneLibellee = Zone & { libelle: string };

/** Désambiguïse une liste de zones. On ne suffixe QUE les noms en double : ajouter
 * l'institution partout alourdirait la liste d'une mairie qui n'a qu'un territoire, pour qui
 * la précision n'apprend rien. */
export function libellerZones(zones: Zone[]): ZoneLibellee[] {
  const comptes = new Map<string, number>();
  for (const z of zones) {
    comptes.set(z.nom, (comptes.get(z.nom) ?? 0) + 1);
  }
  return zones.map(z => ({
    ...z,
    libelle: (comptes.get(z.nom) ?? 0) > 1 && z.institution_nom
      ? `${z.nom} — ${z.institution_nom}`
      : z.nom,
  }));
}
