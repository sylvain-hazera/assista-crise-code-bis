import { Injectable, OnDestroy } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

import { RelaisSerieService } from './relais-serie.service';
import {
  CMD, DecoupeurDeTrames, REP, commandeEnvoiMessage, commandeSimple, encadrer, lireMessageRecu,
} from '../shared/mesh/meshcore-trames';
import {
  PortSerie, VerrouEcran, apiSerie, prendreVerrouEcran, serieDisponible,
} from '../shared/mesh/web-serial';

/** Débit du lien série companion. Valeur de la bibliothèque Python utilisée par notre pont. */
const DEBIT_SERIE = 115200;

/** Cadence du cycle de relais. La radio est lente (LoRa) : interroger plus vite ne sert à rien
 * et consomme du temps d'antenne. */
const CYCLE_MS = 3000;

/** Délai avant nouvelle tentative après une coupure. Croissant, borné. */
const RECONNEXION_MS = [2000, 5000, 10000, 30000];

export type EtatRelais = 'connexion' | 'relais' | 'erreur';

/** Ce qu'un écran a besoin de savoir d'un relais en cours. Sans port ni flux : la vue ne
 * touche jamais au matériel. */
export interface RelaisVisible {
  compagnonId: string;
  nom: string;
  etat: EtatRelais;
  tramesRecues: number;
  tramesEnvoyees: number;
  messagesRelayes: number;
  derniereActivite: Date | null;
  erreur: string;
}

/** L'état interne d'un relais, matériel compris. Ne sort jamais du service. */
interface Relais extends RelaisVisible {
  port: PortSerie;
  lecteur: ReadableStreamDefaultReader<Uint8Array> | null;
  ecrivain: WritableStreamDefaultWriter<Uint8Array> | null;
  decoupeur: DecoupeurDeTrames;
  minuterie: ReturnType<typeof setInterval> | null;
  essais: number;
  arrete: boolean;
}

/**
 * Le moteur du relais navigateur : **plusieurs radios à la fois, depuis n'importe quel écran**.
 *
 * Demande de Sylvain du 14/11/2026 : « sur la même page je peux connecter plusieurs nœuds
 * locaux sans changer d'onglet et avoir la liste des nœuds locaux que je connecte ». La
 * première version tenait le port, le lecteur et la minuterie dans le composant d'une page
 * dédiée : un seul relais, et il mourait au changement de route.
 *
 * Deux conséquences de ce déplacement, et ce sont les deux raisons de le faire :
 *
 * 1. **un service `providedIn: 'root'` survit à la navigation.** On branche une radio depuis la
 *    page des companions, on va voir la carte, le relais continue. Un moteur dans un composant
 *    s'arrête à `ngOnDestroy` — c'est-à-dire au premier clic ailleurs ;
 * 2. **N relais simultanés** : chacun a son port, son découpeur et sa minuterie. Le découpeur
 *    doit être par relais — c'est lui qui garde le reliquat d'une trame coupée, et deux radios
 *    qui le partageraient mélangeraient leurs octets.
 *
 * **Ce n'est pas un satellite** : si internet tombe, la page ne joint plus l'API non plus.
 */
@Injectable({ providedIn: 'root' })
export class RelaisLocalService implements OnDestroy {

  private relais = new Map<string, Relais>();
  private sujet = new BehaviorSubject<RelaisVisible[]>([]);
  private verrou: VerrouEcran | null = null;

  /** Web Serial n'existe ni sur Firefox, ni sur Safari, ni sur iOS. */
  readonly supporte = serieDisponible();

  constructor(private service: RelaisSerieService) {}

  ngOnDestroy(): void {
    // Le service vit aussi longtemps que l'application : on n'arrive ici qu'à la fermeture.
    for (const id of [...this.relais.keys()]) { void this.debrancher(id); }
  }

  /** La liste des radios relayées depuis CE poste, pour l'affichage. */
  liste(): Observable<RelaisVisible[]> {
    return this.sujet.asObservable();
  }

  actif(compagnonId: string): boolean {
    return this.relais.has(compagnonId);
  }

  // ══ Brancher ══════════════════════════════════════════════════════════════

  /**
   * Branche une radio : demande le port, ouvre la session, démarre le cycle.
   *
   * `radio.genre` vaut `noeud` pour un nœud personnel pas encore déclaré comme passerelle — le
   * serveur le promeut alors et rend l'identifiant du companion à utiliser ensuite. Voir
   * `core/relais_navigateur.py`.
   */
  /** Renseigné par le dernier branchement quand le serveur a un avertissement à passer —
   * typiquement une radio promue sans institution, donc relayable par son seul propriétaire. */
  dernierAvertissement = '';

  async brancher(radio: { genre: 'compagnon' | 'noeud'; id: string; nom: string })
      : Promise<string> {
    if (!this.supporte) {
      throw new Error("Ce navigateur n'expose pas l'accès au port USB. Utilisez Chrome ou Edge.");
    }

    // Le choix du port EXIGE un geste de l'utilisateur, et c'est voulu par la norme : aucune
    // page ne peut ouvrir un périphérique sans un clic.
    const port = await apiSerie().requestPort();

    const ouverture = await this.service.ouvrirOuBattre(radio).toPromise();
    const compagnonId = ouverture?.compagnon || radio.id;
    this.dernierAvertissement = ouverture?.avertissement || '';

    if (this.relais.has(compagnonId)) {
      // Déjà relayée depuis ce poste : on ne la branche pas deux fois, chaque message partirait
      // en double. Le port tout juste choisi est relâché.
      try { await port.close(); } catch { /* jamais ouvert */ }
      throw new Error('Cette radio est déjà relayée depuis ce poste.');
    }

    const r: Relais = {
      compagnonId, nom: ouverture?.nom || radio.nom, etat: 'connexion',
      tramesRecues: 0, tramesEnvoyees: 0, messagesRelayes: 0, derniereActivite: null, erreur: '',
      port, lecteur: null, ecrivain: null, decoupeur: new DecoupeurDeTrames(),
      minuterie: null, essais: 0, arrete: false,
    };
    this.relais.set(compagnonId, r);

    try {
      await this.ouvrirLePort(r);
    } catch (e) {
      this.relais.delete(compagnonId);
      this.publier();
      throw e;
    }

    await this.prendreLeVerrou();
    r.etat = 'relais';
    this.publier();
    void this.envoyer(r, commandeSimple(CMD.APP_START));
    r.minuterie = setInterval(() => void this.unCycle(r), CYCLE_MS);
    void this.unCycle(r);
    void this.lireEnContinu(r);
    return compagnonId;
  }

  async debrancher(compagnonId: string): Promise<void> {
    const r = this.relais.get(compagnonId);
    if (!r) { return; }
    r.arrete = true;
    if (r.minuterie) { clearInterval(r.minuterie); r.minuterie = null; }
    await this.libererLePort(r);
    this.relais.delete(compagnonId);
    this.service.fermer({ genre: 'compagnon', id: compagnonId })
      .subscribe({ error: () => undefined });
    if (!this.relais.size) { await this.relacherLeVerrou(); }
    this.publier();
  }

  // ══ Port ══════════════════════════════════════════════════════════════════

  private async ouvrirLePort(r: Relais): Promise<void> {
    await r.port.open({ baudRate: DEBIT_SERIE });
    r.decoupeur.reinitialiser();
    r.lecteur = r.port.readable?.getReader() ?? null;
    r.ecrivain = r.port.writable?.getWriter() ?? null;
    if (!r.lecteur || !r.ecrivain) {
      throw new Error('Ce port ne peut pas être lu et écrit.');
    }
  }

  private async libererLePort(r: Relais): Promise<void> {
    try { await r.lecteur?.cancel(); } catch { /* déjà fermé */ }
    try { r.lecteur?.releaseLock(); } catch { /* déjà relâché */ }
    try { r.ecrivain?.releaseLock(); } catch { /* déjà relâché */ }
    try { await r.port.close(); } catch { /* déjà fermé */ }
    r.lecteur = null;
    r.ecrivain = null;
  }

  // ══ Verrou d'écran ════════════════════════════════════════════════════════
  //
  // Un seul verrou pour tous les relais : il porte sur l'écran, pas sur une radio. Demandé,
  // jamais exigé — tous les navigateurs ne l'ont pas, et l'écran dit de toute façon de ne pas
  // fermer l'onglet.

  private async prendreLeVerrou(): Promise<void> {
    if (!this.verrou) { this.verrou = await prendreVerrouEcran(); }
  }

  private async relacherLeVerrou(): Promise<void> {
    try { await this.verrou?.release(); } catch { /* sans importance */ }
    this.verrou = null;
  }

  // ══ Lecture ═══════════════════════════════════════════════════════════════

  private async lireEnContinu(r: Relais): Promise<void> {
    while (!r.arrete && r.lecteur) {
      try {
        const { value, done } = await r.lecteur.read();
        if (done) { break; }
        if (value) { this.traiter(r, value); }
      } catch (e) {
        if (r.arrete) { return; }
        // Nœud débranché, port repris par un autre logiciel : on retente, sans boucler vite.
        r.erreur = this.lisible(e);
        this.publier();
        void this.reconnecter(r);
        return;
      }
    }
    if (!r.arrete) { void this.reconnecter(r); }
  }

  private traiter(r: Relais, octets: Uint8Array): void {
    for (const charge of r.decoupeur.pousser(octets)) {
      r.tramesRecues++;
      r.derniereActivite = new Date();
      const recu = lireMessageRecu(charge);
      if (recu && recu.texte) {
        r.messagesRelayes++;
        this.service.deposerEntrant(r.compagnonId, recu.pubkeyPrefix, recu.texte).subscribe({
          error: () => { r.erreur = "Un message reçu n'a pas pu être transmis."; this.publier(); },
        });
        // Il y en a peut-être d'autres en attente dans la radio.
        void this.envoyer(r, commandeSimple(CMD.SYNC_NEXT_MESSAGE));
      } else if (charge[0] === REP.MESSAGES_WAITING) {
        void this.envoyer(r, commandeSimple(CMD.SYNC_NEXT_MESSAGE));
      }
    }
    this.publier();
  }

  private async envoyer(r: Relais, charge: Uint8Array): Promise<void> {
    if (!r.ecrivain) { return; }
    try {
      await r.ecrivain.write(encadrer(charge));
      r.tramesEnvoyees++;
    } catch (e) {
      r.erreur = this.lisible(e);
      this.publier();
    }
  }

  // ══ Cycle ═════════════════════════════════════════════════════════════════

  private async unCycle(r: Relais): Promise<void> {
    if (r.arrete || r.etat !== 'relais') { return; }

    // Le battement maintient la session vivante ET remonte les compteurs. Il doit être
    // nettement plus fréquent que le délai de mort côté serveur, sinon le relais se fait
    // fermer en pleine activité.
    this.service.ouvrirOuBattre({ genre: 'compagnon', id: r.compagnonId },
                                r.tramesRecues, r.tramesEnvoyees)
      .subscribe({
        error: () => {
          r.erreur = "Le central ne répond plus. Le relais continue d'écouter la radio, mais "
            + "rien ne remonte pour l'instant.";
          this.publier();
        },
      });

    // Relever ce que la radio garde en attente, puis dépiler la file sortante.
    await this.envoyer(r, commandeSimple(CMD.SYNC_NEXT_MESSAGE));
    this.service.aEnvoyer(r.compagnonId).subscribe({
      next: (messages) => messages.forEach(m => void this.transmettre(r, m)),
      error: () => undefined,
    });
  }

  private async transmettre(r: Relais,
                            m: { id: string; contact_pubkey_hex: string; contenu: string })
      : Promise<void> {
    try {
      await this.envoyer(r, commandeEnvoiMessage(m.contact_pubkey_hex, m.contenu));
      this.service.marquer(m.id, 'ENVOYE').subscribe({ error: () => undefined });
      r.messagesRelayes++;
      r.derniereActivite = new Date();
      this.publier();
    } catch (e) {
      // Marqué en échec plutôt que laissé en attente : un message qui reste indéfiniment dans
      // la file sans que personne ne le sache est pire qu'un échec annoncé.
      this.service.marquer(m.id, 'ECHEC', this.lisible(e)).subscribe({ error: () => undefined });
    }
  }

  // ══ Reconnexion ═══════════════════════════════════════════════════════════

  private async reconnecter(r: Relais): Promise<void> {
    if (r.arrete) { return; }
    r.etat = 'connexion';
    await this.libererLePort(r);
    const delai = RECONNEXION_MS[Math.min(r.essais, RECONNEXION_MS.length - 1)];
    r.essais++;
    this.publier();
    setTimeout(() => {
      if (r.arrete) { return; }
      void this.reprendreLePort(r);
    }, delai);
  }

  /**
   * Reprise SANS geste de l'utilisateur, en réouvrant **le port de CE relais**.
   *
   * On garde la référence au `SerialPort` plutôt que de reprendre `getPorts()[0]` : avec
   * plusieurs radios branchées, le premier port autorisé n'est pas forcément celui de ce
   * relais — on parlerait à la mauvaise radio. L'objet reste valide après un débranchement,
   * c'est ce qui permet de rouvrir au rebranchement sans rien demander.
   */
  private async reprendreLePort(r: Relais): Promise<void> {
    try {
      await this.ouvrirLePort(r);
      r.essais = 0;
      r.etat = 'relais';
      r.erreur = '';
      this.publier();
      void this.envoyer(r, commandeSimple(CMD.APP_START));
      void this.lireEnContinu(r);
    } catch (e) {
      r.erreur = this.lisible(e);
      void this.reconnecter(r);
    }
  }

  // ══ Divers ════════════════════════════════════════════════════════════════

  private publier(): void {
    this.sujet.next([...this.relais.values()].map(r => ({
      compagnonId: r.compagnonId, nom: r.nom, etat: r.etat,
      tramesRecues: r.tramesRecues, tramesEnvoyees: r.tramesEnvoyees,
      messagesRelayes: r.messagesRelayes, derniereActivite: r.derniereActivite,
      erreur: r.erreur,
    })));
  }

  lisible(e: unknown): string {
    const brut = e instanceof Error ? e.message : String(e);
    if (/No port selected|cancel/i.test(brut)) { return 'Aucun port choisi.'; }
    if (/Failed to open|already open|in use/i.test(brut)) {
      return 'Ce port est déjà ouvert par un autre logiciel. Fermez l\'autre application qui '
        + 'utilise la radio, puis réessayez.';
    }
    return brut;
  }
}
