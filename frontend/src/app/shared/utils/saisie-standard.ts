/**
 * Saisie « pour autrui » par le standard de crise d'une collectivité (18/11/2026).
 *
 * Quand un habitant téléphone à la mairie pour demander de l'aide, en proposer, signaler un
 * danger ou une disparition, l'agent remplit **le même formulaire que le public**, à sa place :
 * c'est la vraie fiche qui est créée, pas une note à part. Le standard ouvre le formulaire
 * avec `?standard=1`, et les quatre formulaires lisent cela ici.
 *
 * Ce que le mode change, et rien d'autre : les coordonnées ne sont pas préremplies avec celles
 * de l'agent, l'adresse électronique devient facultative (le serveur ne l'accepte que d'un
 * compte institutionnel), et l'on revient au standard une fois la fiche enregistrée.
 */
export interface SaisieStandard {
  /** Crise choisie au standard, pour la proposer d'emblée. */
  crise: string | null;
  /** Identifiant de cet appel : plusieurs fiches créées par un même formulaire ne laissent
   * qu'une trace d'appel. */
  appel: string;
}

export const RETOUR_STANDARD = '/admin/standard-crise';

export function lireSaisieStandard(auth: { isInstitutionalEffective?: () => boolean }): SaisieStandard | null {
  const parametres = new URLSearchParams(window.location.search);
  if (parametres.get('standard') !== '1' || !auth.isInstitutionalEffective?.()) return null;
  const appel = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () => Math.floor(Math.random() * 16).toString(16));
  return { crise: parametres.get('crise'), appel };
}

/** Le même mode, enclenché par la case « Enregistré par la collectivité à la demande de la
 * personne » : un agent n'a pas besoin de passer par la page du standard pour cela. */
export function nouvelleSaisiePourAutrui(crise: string | null = null): SaisieStandard {
  const appel = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () => Math.floor(Math.random() * 16).toString(16));
  return { crise, appel };
}

/** À ajouter à chaque envoi fait pendant cet appel. */
export function marquerSaisieStandard(formData: FormData, saisie: SaisieStandard | null): void {
  if (!saisie) return;
  formData.append('via_standard', '1');
  formData.append('standard_appel', saisie.appel);
}
