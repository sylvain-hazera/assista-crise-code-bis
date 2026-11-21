import { Releve } from './regles-suivi';

/** La position, pour un écran ouvert (tournée, photo) : rien n'est envoyé d'ici, et la
 * surveillance s'arrête quand l'écran se ferme. Le refus est rendu comme tel. */
export function suivrePosition(surReleve: (r: Releve) => void, surRefus: () => void): () => void {
  if (typeof navigator === 'undefined' || !navigator.geolocation) { surRefus(); return () => {}; }
  const id = navigator.geolocation.watchPosition(
    p => surReleve({ latitude: p.coords.latitude, longitude: p.coords.longitude, instant: p.timestamp || Date.now(),
                     precision_m: p.coords.accuracy ?? 0 }),
    e => { if (e.code === e.PERMISSION_DENIED) surRefus(); },
    { enableHighAccuracy: true, maximumAge: 10_000, timeout: 60_000 },
  );
  return () => navigator.geolocation.clearWatch(id);
}

/** Une position, pour une photo : null au bout de `delaiMs` ou en cas de refus (la photo part
 * alors sans lieu, et l'écran le dit). */
export function positionPonctuelle(delaiMs = 15_000): Promise<Releve | null> {
  if (typeof navigator === 'undefined' || !navigator.geolocation) return Promise.resolve(null);
  return new Promise(resolve => navigator.geolocation.getCurrentPosition(
    p => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude, instant: p.timestamp || Date.now(),
                   precision_m: p.coords.accuracy ?? 0 }),
    () => resolve(null),
    { enableHighAccuracy: true, maximumAge: 30_000, timeout: delaiMs },
  ));
}

/** Une position est encore celle « du moment » si elle a moins de deux minutes. */
export function recente(r: Releve | null, maintenant = Date.now()): Releve | null {
  return r && maintenant - r.instant < 120_000 ? r : null;
}
