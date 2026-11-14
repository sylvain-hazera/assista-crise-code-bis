import { Injectable, OnDestroy } from '@angular/core';
import { BehaviorSubject, Observable, firstValueFrom } from 'rxjs';

import { DesignationRadio, RelaisSerieService } from './relais-serie.service';
import { IdentiteRadio, MessageRadio, Pilote, Protocole, creerPilote } from '../shared/mesh/pilotes';
import { MESHCORE_BLE } from '../shared/mesh/meshcore-trames';
import { MESHTASTIC_BLE } from '../shared/mesh/meshtastic-trames';
import {
  NomTransport, ProfilBle, Transport, TransportBle, TransportHttpMeshtastic, TransportSerie,
  bluetoothDisponible,
} from '../shared/mesh/transports';
import { VerrouEcran, prendreVerrouEcran, serieDisponible } from '../shared/mesh/web-serial';

/** Débit du lien série. 115 200 pour les deux protocoles (meshcore et meshtastic, Python). */
const DEBIT_SERIE = 115200;

/** Cadence du cycle de relais. La radio est lente (LoRa) : interroger plus vite ne sert à rien. */
const CYCLE_MS = 3000;

/** Délai avant nouvelle tentative après une coupure. Croissant, borné. */
const RECONNEXION_MS = [2000, 5000, 10000, 30000];

const PROFILS_BLE: Record<Protocole, ProfilBle> = {
  MESHCORE: { service: MESHCORE_BLE.SERVICE, ecriture: MESHCORE_BLE.RX, notification: MESHCORE_BLE.TX },
  MESHTASTIC: {
    service: MESHTASTIC_BLE.SERVICE, ecriture: MESHTASTIC_BLE.TO_RADIO,
    signal: MESHTASTIC_BLE.FROM_NUM, lecture: MESHTASTIC_BLE.FROM_RADIO,
  },
};

export type EtatRelais = 'connexion' | 'relais' | 'erreur';

/** Ce qu'un écran a besoin de savoir d'un relais. Sans transport ni pilote : la vue ne touche
 * jamais au matériel. */
export interface RelaisVisible {
  compagnonId: string;
  protocole: Protocole;
  transport: NomTransport;
  liaison: string;
  nom: string;
  etat: EtatRelais;
  tramesRecues: number;
  tramesEnvoyees: number;
  messagesRelayes: number;
  /** Messages de canal entendus mais non enregistrés : canal inconnu d'Assista-Crise. */
  canauxIgnores: string[];
  derniereActivite: Date | null;
  erreur: string;
}

interface Relais extends RelaisVisible {
  transportObj: Transport;
  pilote: Pilote;
  identite: IdentiteRadio;
  minuterie: ReturnType<typeof setInterval> | null;
  essais: number;
  arrete: boolean;
  canaux: Map<string, string> | null;
  /** Identifiants des messages en cours d'émission : un cycle ne doit pas réémettre celui que
   * le précédent n'a pas fini d'envoyer. */
  enCours: Set<string>;
}

/** Ce qu'il faut pour brancher une radio. `radio` désigne une ligne précise ; sans elle, la radio
 * est identifiée par ce qu'elle dit d'elle-même. */
export interface Branchement {
  protocole: Protocole;
  transport: NomTransport;
  /** Réseau local (Meshtastic) : IP ou nom en `.local`. */
  adresse?: string;
  radio?: { genre: 'compagnon' | 'noeud'; id: string };
}

/**
 * Le moteur du relais navigateur : **plusieurs radios, deux protocoles, trois transports**, et il
 * survit à la navigation (`providedIn: 'root'`).
 *
 * Pour chaque radio : un transport (USB, Bluetooth, réseau local), un pilote (MeshCore,
 * Meshtastic), et le cycle qui fait le lien avec le serveur. **L'ordre du branchement est le
 * garde-fou** : on ouvre la liaison, la radio dit qui elle est, et c'est seulement alors que le
 * serveur ouvre la session — sur la radio réellement branchée, pas sur celle qu'on a cliquée.
 */
@Injectable({ providedIn: 'root' })
export class RelaisLocalService implements OnDestroy {

  private relais = new Map<string, Relais>();
  private sujet = new BehaviorSubject<RelaisVisible[]>([]);
  private verrou: VerrouEcran | null = null;

  readonly usbDisponible = serieDisponible();
  readonly bleDisponible = bluetoothDisponible();
  /** Gardé pour les écrans existants : « au moins un transport navigateur est possible ». */
  readonly supporte = this.usbDisponible || this.bleDisponible;

  /** Renseigné par le dernier branchement quand le serveur a un avertissement à passer. */
  dernierAvertissement = '';

  constructor(private service: RelaisSerieService) {}

  ngOnDestroy(): void {
    for (const id of [...this.relais.keys()]) { void this.debrancher(id); }
  }

  liste(): Observable<RelaisVisible[]> {
    return this.sujet.asObservable();
  }

  actif(compagnonId: string): boolean {
    return this.relais.has(compagnonId);
  }

  /** Pourquoi ce transport est impossible ici, ou '' s'il l'est. Dit AVANT le clic. */
  raisonIndisponible(protocole: Protocole, transport: NomTransport): string {
    if (transport === 'USB' && !this.usbDisponible) {
      return "L'USB n'est accessible que depuis Chrome ou Edge, sur ordinateur ou Android.";
    }
    if (transport === 'BLE' && !this.bleDisponible) {
      return 'Le Bluetooth n\'est accessible que depuis Chrome ou Edge (sous Linux, activer '
        + 'chrome://flags/#enable-experimental-web-platform-features).';
    }
    if (transport === 'WIFI' && protocole === 'MESHCORE') {
      return 'Un companion MeshCore en Wi-Fi parle du TCP brut, qu\'aucun navigateur ne sait '
        + 'ouvrir. Branchez-le en USB ou en Bluetooth.';
    }
    return '';
  }

  // ══ Brancher ══════════════════════════════════════════════════════════════

  /**
   * Branche une radio. **À appeler directement depuis le clic** : le choix du port ou de
   * l'appareil Bluetooth exige un geste de l'utilisateur, et c'est la première chose faite ici.
   * Renvoie l'identifiant du companion relayé.
   */
  async brancher(b: Branchement): Promise<string> {
    const raison = this.raisonIndisponible(b.protocole, b.transport);
    if (raison) { throw new Error(raison); }

    const transport = await this.choisirTransport(b);
    const pilote = creerPilote(b.protocole, transport);
    transport.surDonnees = o => pilote.recevoir(o);

    let identite: IdentiteRadio;
    try {
      await transport.ouvrir();
      identite = await pilote.demarrer();
    } catch (e) {
      await transport.fermer();
      throw e;
    }

    const designation: DesignationRadio = {
      protocole: b.protocole, identite, transport: b.transport,
      ...(b.radio ? { [b.radio.genre]: b.radio.id } : {}),
    };
    let ouverture;
    try {
      ouverture = await firstValueFrom(this.service.ouvrirOuBattre(designation));
    } catch (e) {
      await transport.fermer();
      throw e;
    }
    const compagnonId = ouverture.compagnon!;
    this.dernierAvertissement = ouverture.avertissement || '';

    if (this.relais.has(compagnonId)) {
      // Déjà relayée depuis ce poste : la brancher deux fois enverrait chaque message en double.
      await transport.fermer();
      throw new Error(`« ${ouverture.nom} » est déjà relayée depuis ce poste.`);
    }

    const r: Relais = {
      compagnonId, protocole: b.protocole, transport: b.transport, liaison: transport.libelle,
      nom: ouverture.nom || identite.nom || 'Radio', etat: 'relais',
      tramesRecues: 0, tramesEnvoyees: 0, messagesRelayes: 0, canauxIgnores: [],
      derniereActivite: null, erreur: '',
      transportObj: transport, pilote, identite, minuterie: null, essais: 0, arrete: false,
      canaux: null, enCours: new Set(),
    };
    this.relais.set(compagnonId, r);
    pilote.surMessage = m => this.relayerEntrant(r, m);
    transport.surPerte = raison => void this.reconnecter(r, raison);

    await this.prendreLeVerrou();
    r.minuterie = setInterval(() => void this.unCycle(r), CYCLE_MS);
    void this.unCycle(r);
    this.publier();
    return compagnonId;
  }

  private async choisirTransport(b: Branchement): Promise<Transport> {
    if (b.transport === 'USB') { return TransportSerie.choisir(DEBIT_SERIE); }
    if (b.transport === 'BLE') { return TransportBle.choisir(PROFILS_BLE[b.protocole]); }
    return new TransportHttpMeshtastic(b.adresse || '');
  }

  async debrancher(compagnonId: string): Promise<void> {
    const r = this.relais.get(compagnonId);
    if (!r) { return; }
    r.arrete = true;
    if (r.minuterie) { clearInterval(r.minuterie); r.minuterie = null; }
    await r.transportObj.fermer();
    this.relais.delete(compagnonId);
    this.service.fermer({ protocole: r.protocole, compagnon: compagnonId })
      .subscribe({ error: () => undefined });
    if (!this.relais.size) { await this.relacherLeVerrou(); }
    this.publier();
  }

  // ══ Entrant : radio → serveur ═════════════════════════════════════════════

  private relayerEntrant(r: Relais, m: MessageRadio): void {
    r.derniereActivite = new Date();
    const echec = () => { r.erreur = "Un message reçu n'a pas pu être transmis."; this.publier(); };

    if (m.genre === 'DM') {
      r.messagesRelayes++;
      this.service.deposerDm(r.protocole, r.compagnonId, m.expediteur, m.texte)
        .subscribe({ error: echec });
      this.publier();
      return;
    }
    // Message de canal Meshtastic : le serveur exige un canal, retrouvé par son NOM parmi ceux
    // déclarés. Un canal inconnu d'Assista-Crise n'est pas enregistré — et on le dit.
    void this.canalPourNom(r, m.canalNom || '').then(canalId => {
      if (!canalId) {
        const nom = m.canalNom || 'canal primaire';
        if (!r.canauxIgnores.includes(nom)) { r.canauxIgnores.push(nom); }
        this.publier();
        return;
      }
      r.messagesRelayes++;
      this.service.deposerCanalMeshtastic(r.compagnonId, canalId, Number(m.expediteur), m.texte)
        .subscribe({ error: echec });
      this.publier();
    });
  }

  private async canalPourNom(r: Relais, nom: string): Promise<string | undefined> {
    if (!nom) { return undefined; }
    if (!r.canaux) {
      try {
        r.canaux = await firstValueFrom(this.service.canauxMeshtastic());
      } catch {
        return undefined;
      }
    }
    return r.canaux.get(nom.toLowerCase());
  }

  // ══ Cycle : battement, relève, file sortante ══════════════════════════════

  private async unCycle(r: Relais): Promise<void> {
    if (r.arrete || r.etat !== 'relais') { return; }

    r.tramesRecues = r.pilote.tramesRecues;
    r.tramesEnvoyees = r.pilote.tramesEnvoyees;
    // Le battement maintient la session vivante ET remonte les compteurs.
    this.service.ouvrirOuBattre({ protocole: r.protocole, compagnon: r.compagnonId,
                                  transport: r.transport },
                                r.tramesRecues, r.tramesEnvoyees)
      .subscribe({
        next: () => { if (r.erreur.startsWith('Le central')) { r.erreur = ''; } },
        error: () => {
          r.erreur = "Le central ne répond plus. Le relais continue d'écouter la radio, mais "
            + "rien ne remonte pour l'instant.";
          this.publier();
        },
      });

    try {
      await r.pilote.cycle();
    } catch (e) {
      r.erreur = this.lisible(e);
    }

    this.service.aEnvoyer(r.protocole, r.compagnonId).subscribe({
      next: messages => { for (const m of messages) { void this.transmettre(r, m); } },
      error: () => undefined,
    });
    this.publier();
  }

  private async transmettre(r: Relais,
                            m: { id: string; contenu: string; contact_pubkey_hex?: string;
                                 contact_node_num?: number }): Promise<void> {
    if (r.enCours.has(m.id)) { return; }
    r.enCours.add(m.id);
    const destination = r.protocole === 'MESHTASTIC' ? m.contact_node_num : m.contact_pubkey_hex;
    try {
      if (destination === undefined || destination === null) {
        throw new Error('Destinataire inconnu.');
      }
      await r.pilote.envoyerDm(destination, m.contenu);
      await firstValueFrom(this.service.marquer(r.protocole, m.id, 'ENVOYE'));
      r.messagesRelayes++;
      r.derniereActivite = new Date();
    } catch (e) {
      // Marqué en échec plutôt que laissé en attente : un message qui reste indéfiniment dans
      // la file sans que personne ne le sache est pire qu'un échec annoncé.
      this.service.marquer(r.protocole, m.id, 'ECHEC', this.lisible(e))
        .subscribe({ error: () => undefined });
    } finally {
      r.enCours.delete(m.id);
      this.publier();
    }
  }

  // ══ Reconnexion ═══════════════════════════════════════════════════════════

  private async reconnecter(r: Relais, raison: string): Promise<void> {
    if (r.arrete || r.etat === 'connexion') { return; }
    r.etat = 'connexion';
    r.erreur = raison;
    await r.transportObj.fermer();
    this.publier();
    const delai = RECONNEXION_MS[Math.min(r.essais, RECONNEXION_MS.length - 1)];
    r.essais++;
    setTimeout(() => void this.reprendre(r), delai);
  }

  /**
   * Reprise SANS geste de l'utilisateur : même port USB, même appareil Bluetooth, même adresse.
   * Et la radio doit redire qui elle est — si quelqu'un a branché une autre radio sur ce port
   * entre-temps, on s'arrête au lieu de lui attribuer le trafic de la première.
   */
  private async reprendre(r: Relais): Promise<void> {
    if (r.arrete) { return; }
    try {
      await r.transportObj.ouvrir();
      const identite = await r.pilote.demarrer();
      const memeRadio = r.protocole === 'MESHTASTIC'
        ? identite.node_num === r.identite.node_num
        : identite.pubkey_hex === r.identite.pubkey_hex;
      if (!memeRadio) {
        r.etat = 'erreur';
        r.erreur = "Une autre radio est branchée à la place de celle-ci : relais arrêté.";
        r.arrete = true;
        if (r.minuterie) { clearInterval(r.minuterie); r.minuterie = null; }
        await r.transportObj.fermer();
        this.publier();
        return;
      }
      r.essais = 0;
      r.etat = 'relais';
      r.erreur = '';
      this.publier();
    } catch (e) {
      r.etat = 'relais';   // pour que reconnecter() reparte
      void this.reconnecter(r, this.lisible(e));
    }
  }

  // ══ Verrou d'écran : un seul pour tous les relais ═════════════════════════

  private async prendreLeVerrou(): Promise<void> {
    if (!this.verrou) { this.verrou = await prendreVerrouEcran(); }
  }

  private async relacherLeVerrou(): Promise<void> {
    try { await this.verrou?.release(); } catch { /* sans importance */ }
    this.verrou = null;
  }

  // ══ Divers ════════════════════════════════════════════════════════════════

  private publier(): void {
    this.sujet.next([...this.relais.values()].map(r => ({
      compagnonId: r.compagnonId, protocole: r.protocole, transport: r.transport,
      liaison: r.liaison, nom: r.nom, etat: r.etat,
      tramesRecues: r.pilote.tramesRecues, tramesEnvoyees: r.pilote.tramesEnvoyees,
      messagesRelayes: r.messagesRelayes, canauxIgnores: [...r.canauxIgnores],
      derniereActivite: r.derniereActivite, erreur: r.erreur,
    })));
  }

  lisible(e: unknown): string {
    const err = e as { error?: { error?: string }; message?: string };
    if (err?.error?.error) { return err.error.error; }       // refus du serveur, fait pour être lu
    const brut = e instanceof Error ? e.message : String(e);
    if (/No port selected|cancel|User cancelled|chooser/i.test(brut)) { return 'Aucune radio choisie.'; }
    if (/Failed to open|already open|in use/i.test(brut)) {
      return "Ce port est déjà ouvert par un autre logiciel. Fermez l'autre application qui "
        + 'utilise la radio, puis réessayez.';
    }
    return brut;
  }
}
