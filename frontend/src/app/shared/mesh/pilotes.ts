/**
 * Les pilotes de protocole : ce qu'un relais fait d'une radio, quel que soit le transport.
 *
 * Un pilote se présente à la radio, lit **son identité** (clé publique MeshCore, numéro de
 * nœud Meshtastic), remonte les messages texte reçus, envoie ceux qu'on lui confie et entretient
 * la liaison. Il ne parle jamais au serveur : c'est le moteur (`RelaisLocalService`) qui fait le
 * lien. Ainsi chaque pilote se teste avec un faux transport, sans réseau ni radio.
 */
import {
  CMD, DecoupeurDeTrames, REP, commandeAppStart, commandeEnvoiMessage, commandeHeure,
  commandeRequeteAppareil, commandeSimple, encadrer, lireJournalRadio, lireMessageRecu, lireSelfInfo, TrameEntendue,
} from './meshcore-trames';
import {
  DecoupeurMeshtastic, MT_DIFFUSION, NONCE_CONFIG, NONCE_NOEUDS, PREMIER_NONCE_BATTEMENT,
  decouperTexte, encadrerMeshtastic, lireFromRadio, MesurePaquet, mesurerFromRadio, nonceSuivant, nouvelIdentifiant,
  octetsDeReveil, toRadioBattement, toRadioTexte, toRadioVeutConfig, adminDemandeProprietaire,
  adminEcrireCanal, adminSupprimerCanal, toRadioAdmin, toRadioTexteCanal, ERREUR_ROUTAGE,
  ROLE_CANAL,
} from './meshtastic-trames';
import { Transport } from './transports';

export type Protocole = 'MESHCORE' | 'MESHTASTIC';

/** Ce que la radio dit d'elle-même — envoyé tel quel au serveur pour identification. */
export interface IdentiteRadio {
  pubkey_hex?: string;
  node_num?: number;
  cle_publique_hex?: string;
  nom: string;
}

export interface MessageRadio {
  /** Message direct pour cette radio, ou message de canal adressé à tous. */
  genre: 'DM' | 'CANAL';
  /** MeshCore : préfixe hexadécimal de la clé publique ; Meshtastic : numéro de nœud. */
  expediteur: string | number;
  texte: string;
  /** Meshtastic, message de canal : le nom du canal tel que configuré sur la radio. */
  canalNom?: string;
}

/** Ce que la radio entend, pour le tableau et la carte radio (19/11/2026) : la trame brute
 * MeshCore avec son SNR, ou le type, les sauts et la télémétrie d'un paquet Meshtastic. */
export type MesureRadio =
  | { genre: 'trame_meshcore'; trame: TrameEntendue }
  | { genre: 'paquet_meshtastic'; paquet: MesurePaquet };

export interface Pilote {
  readonly protocole: Protocole;
  identite: IdentiteRadio | null;
  tramesRecues: number;
  tramesEnvoyees: number;
  surMessage: (m: MessageRadio) => void;
  surMesure: (m: MesureRadio) => void;
  /** Se présente et attend l'identité de la radio. Rejette si elle ne répond pas. */
  demarrer(): Promise<IdentiteRadio>;
  /** À brancher sur `transport.surDonnees`. */
  recevoir(octets: Uint8Array): void;
  envoyerDm(destination: string | number, texte: string): Promise<void>;
  /** Appelé à chaque cycle du moteur : relève, battement, tirage. */
  cycle(): Promise<void>;
}

function delai<T>(promesse: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise<T>((resoudre, rejeter) => {
    const minuterie = setTimeout(() => rejeter(new Error(message)), ms);
    promesse.then(v => { clearTimeout(minuterie); resoudre(v); },
                  e => { clearTimeout(minuterie); rejeter(e); });
  });
}

// ══ MeshCore ═════════════════════════════════════════════════════════════════

export class PiloteMeshCore implements Pilote {
  readonly protocole = 'MESHCORE' as const;
  identite: IdentiteRadio | null = null;
  tramesRecues = 0;
  tramesEnvoyees = 0;
  surMessage: (m: MessageRadio) => void = () => undefined;
  surMesure: (m: MesureRadio) => void = () => undefined;

  private decoupeur = new DecoupeurDeTrames();
  private attenteIdentite: ((id: IdentiteRadio) => void) | null = null;
  /** Réponse attendue à un envoi : `MSG_SENT` (accepté) ou `ERROR` (refusé). */
  private attenteEnvoi: ((ok: boolean) => void) | null = null;

  constructor(private transport: Transport) {}

  private async ecrire(charge: Uint8Array): Promise<void> {
    // En série, cadrage `0x3c` + longueur ; en Bluetooth, la charge telle quelle.
    await this.transport.ecrire(this.transport.flux ? encadrer(charge) : charge);
    this.tramesEnvoyees++;
  }

  /**
   * Séquence de connexion des deux clients de référence (`meshcore.js` et la bibliothèque
   * Python) : annoncer la version de protocole comprise, se présenter, lire l'identité, puis
   * remettre la radio à l'heure.
   */
  async demarrer(): Promise<IdentiteRadio> {
    this.decoupeur.reinitialiser();
    const identite = new Promise<IdentiteRadio>(r => { this.attenteIdentite = r; });
    await this.ecrire(commandeRequeteAppareil());
    await this.ecrire(commandeAppStart());
    // Une radio qui sort de veille rate parfois la première commande : on la répète une fois
    // avant de conclure qu'elle ne répond pas.
    const relance = setTimeout(() => void this.ecrire(commandeAppStart()), 3000);
    let lue: IdentiteRadio;
    try {
      lue = await delai(identite, 8000, "La radio ne s'est pas présentée : est-ce bien un "
        + 'companion MeshCore, avec le firmware « companion » (USB ou Bluetooth) ?');
    } finally {
      clearTimeout(relance);
    }
    await this.ecrire(commandeHeure());
    return lue;
  }

  recevoir(octets: Uint8Array): void {
    const trames = this.transport.flux ? this.decoupeur.pousser(octets) : [octets];
    for (const charge of trames) {
      if (!charge.length) { continue; }
      this.tramesRecues++;
      const type = charge[0];

      if (type === REP.SELF_INFO) {
        const id = lireSelfInfo(charge);
        if (id) {
          this.identite = { pubkey_hex: id.pubkeyHex, nom: id.nom };
          this.attenteIdentite?.(this.identite);
          this.attenteIdentite = null;
        }
        continue;
      }
      if (type === REP.LOG_RX_DATA) {
        const trame = lireJournalRadio(charge);
        if (trame) { this.surMesure({ genre: 'trame_meshcore', trame }); }
        continue;
      }
      if (type === REP.MSG_SENT || type === REP.ERROR) {
        this.attenteEnvoi?.(type === REP.MSG_SENT);
        this.attenteEnvoi = null;
        continue;
      }
      const recu = lireMessageRecu(charge);
      if (recu) {
        if (recu.texte) {
          this.surMessage({ genre: 'DM', expediteur: recu.pubkeyPrefix, texte: recu.texte });
        }
        // Il y en a peut-être d'autres en attente dans la radio.
        void this.ecrire(commandeSimple(CMD.SYNC_NEXT_MESSAGE));
      } else if (type === REP.MESSAGES_WAITING) {
        void this.ecrire(commandeSimple(CMD.SYNC_NEXT_MESSAGE));
      }
    }
  }

  /** Envoie et attend que la radio accepte : « envoyé » ne doit pas vouloir dire « écrit sur
   * le port ». Une radio qui ne connaît pas le destinataire répond `ERROR`. */
  async envoyerDm(destination: string | number, texte: string): Promise<void> {
    const reponse = new Promise<boolean>(r => { this.attenteEnvoi = r; });
    await this.ecrire(commandeEnvoiMessage(String(destination), texte));
    const accepte = await delai(reponse, 5000, 'La radio ne confirme pas la prise en charge.');
    if (!accepte) {
      throw new Error("La radio a refusé l'envoi : destinataire absent de ses contacts ?");
    }
  }

  async cycle(): Promise<void> {
    await this.ecrire(commandeSimple(CMD.SYNC_NEXT_MESSAGE));
  }
}

// ══ Meshtastic ═══════════════════════════════════════════════════════════════

/** Battement : 30 s, comme le client web officiel (`HEARTBEAT_INTERVAL_MS`). */
const BATTEMENT_MESHTASTIC_MS = 30_000;

/** Délai d'inactivité d'une étape de poignée de main, réarmé à chaque trame de poignée de
 * main : une grosse base de nœuds ne le déclenche jamais tant qu'elle défile, une radio figée
 * oui. Repris du client officiel, comme le plafond par étape. */
const POIGNEE_INACTIVITE_MS = 15_000;
const POIGNEE_PLAFOND_MS = 150_000;
/** Pendant la poignée de main en HTTP : fréquence des lectures de `fromradio`. */
const POIGNEE_SONDAGE_HTTP_MS = 400;
const POIGNEE_PAUSE_MS = 100;

const attendre = (ms: number) => new Promise(r => setTimeout(r, ms));

export class PiloteMeshtastic implements Pilote {
  readonly protocole = 'MESHTASTIC' as const;
  identite: IdentiteRadio | null = null;
  tramesRecues = 0;
  tramesEnvoyees = 0;
  surMessage: (m: MessageRadio) => void = () => undefined;
  surMesure: (m: MesureRadio) => void = () => undefined;

  /** Index → nom des canaux configurés sur la radio, lus pendant la configuration. */
  readonly canaux = new Map<number, string>();

  /** Les 8 emplacements tels que la radio les a décrits, désactivés compris. C'est sur eux que
   * se fonde la proposition de plan de canaux au branchement. */
  readonly emplacements = new Map<number, EmplacementCanal>();

  /** Commandes d'administration en attente de leur réponse, par identifiant de paquet. */
  private attentes = new Map<number, (e: { erreur: number; cleSession?: string }) => void>();
  private cleSession = '';

  private decoupeur = new DecoupeurMeshtastic();
  private monNumero = 0;
  private noms = new Map<number, { nom: string; cle: string }>();
  private etape: number | null = null;
  private finEtape: (() => void) | null = null;
  private echecEtape: ((e: Error) => void) | null = null;
  private minuterieInactivite: ReturnType<typeof setTimeout> | null = null;
  private dernierBattement = 0;
  private nonce = PREMIER_NONCE_BATTEMENT;

  constructor(private transport: Transport) {}

  private async ecrire(toRadio: Uint8Array): Promise<void> {
    await this.transport.ecrire(this.transport.flux ? encadrerMeshtastic(toRadio) : toRadio);
    this.tramesEnvoyees++;
  }

  /**
   * Poignée de main en deux temps, celle du client officiel et d'Android : configuration seule
   * (`69420`), pause, battement, pause, puis base de nœuds seule (`69421`).
   *
   * Pas de renvoi de `want_config` dans la même session en cas de blocage : le client officiel
   * a constaté que cela peut figer le firmware. Une étape qui cale échoue ; c'est la
   * reconnexion du moteur (qui rouvre le transport) qui retente.
   */
  async demarrer(): Promise<IdentiteRadio> {
    this.decoupeur.reinitialiser();
    this.monNumero = 0;
    this.canaux.clear();
    this.emplacements.clear();
    this.cleSession = '';
    if (this.transport.flux) {
      await this.transport.ecrire(octetsDeReveil());
      await attendre(POIGNEE_PAUSE_MS);
    }

    try {
      await this.etapePoignee(NONCE_CONFIG);
    } catch {
      throw new Error("La radio ne s'est pas présentée : est-ce bien un nœud Meshtastic, et "
        + "aucune autre application (téléphone, autre onglet) n'y est-elle connectée ?");
    }
    if (!this.monNumero) {
      // Le client officiel refuse aussi ce cas : sans my_info, la session n'a pas d'identité.
      throw new Error("La radio a envoyé sa configuration sans son numéro de nœud.");
    }

    await attendre(POIGNEE_PAUSE_MS);
    await this.battre();
    await attendre(POIGNEE_PAUSE_MS);
    try {
      await this.etapePoignee(NONCE_NOEUDS);
    } catch {
      // La base de nœuds sert au nom de notre propre radio, pas au relais : on continue sans.
    }

    const moi = this.noms.get(this.monNumero);
    this.identite = {
      node_num: this.monNumero,
      nom: moi?.nom || '',
      cle_publique_hex: moi?.cle || '',
    };
    return this.identite;
  }

  private etapePoignee(nonce: number): Promise<void> {
    this.etape = nonce;
    const fin = new Promise<void>((resoudre, rejeter) => {
      this.finEtape = resoudre;
      this.echecEtape = rejeter;
    });
    this.rearmer();
    const plafond = setTimeout(() => this.echecEtape?.(new Error('plafond')), POIGNEE_PLAFOND_MS);
    // Réseau local (HTTP) : rien n'arrive tout seul, et le cycle régulier du relais ne démarre
    // qu'APRÈS la poignée de main. Sans ce sondage, la seule lecture était celle qui suit
    // l'écriture ; une radio qui répond « vide » le temps de préparer sa configuration, ou une
    // base de nœuds de plus de 200 trames, laissait l'étape caler jusqu'au délai d'inactivité
    // (vu le 19/11/2026 : « Connexion… » sans fin sur une radio en Wi-Fi). Le client officiel
    // interroge lui aussi la radio en continu.
    const sondage = this.transport.flux ? null
      : setInterval(() => void this.transport.tirer(), POIGNEE_SONDAGE_HTTP_MS);
    void this.ecrire(toRadioVeutConfig(nonce)).catch(e => this.echecEtape?.(e));
    return fin.finally(() => {
      clearTimeout(plafond);
      if (sondage) { clearInterval(sondage); }
      if (this.minuterieInactivite) { clearTimeout(this.minuterieInactivite); }
      this.minuterieInactivite = null;
      this.etape = null;
      this.finEtape = null;
      this.echecEtape = null;
    });
  }

  /** Réarme le délai d'inactivité : appelé à chaque trame de poignée de main. */
  private rearmer(): void {
    if (this.etape === null) { return; }
    if (this.minuterieInactivite) { clearTimeout(this.minuterieInactivite); }
    this.minuterieInactivite = setTimeout(
      () => this.echecEtape?.(new Error('inactivité')), POIGNEE_INACTIVITE_MS);
  }

  private async battre(): Promise<void> {
    this.dernierBattement = Date.now();
    const nonce = this.nonce;
    this.nonce = nonceSuivant(nonce);
    await this.ecrire(toRadioBattement(nonce));
  }

  recevoir(octets: Uint8Array): void {
    const trames = this.transport.flux ? this.decoupeur.pousser(octets) : [octets];
    for (const trame of trames) {
      if (!trame.length) { continue; }
      this.tramesRecues++;
      let e;
      try {
        e = lireFromRadio(trame);
      } catch {
        continue;   // trame corrompue : écartée, comptée, jamais interprétée
      }
      const mesure = mesurerFromRadio(trame);
      if (mesure) { this.surMesure({ genre: 'paquet_meshtastic', paquet: mesure }); }
      switch (e.genre) {
        case 'mon_noeud':
          this.monNumero = e.numero;
          this.rearmer();
          break;
        case 'noeud':
          this.noms.set(e.numero, { nom: e.nomLong, cle: e.clePubliqueHex });
          this.rearmer();
          break;
        case 'canal':
          this.emplacements.set(e.index, { index: e.index, nom: e.nom, role: e.role, pskHex: e.pskHex });
          if (e.actif) { this.canaux.set(e.index, e.nom); } else { this.canaux.delete(e.index); }
          this.rearmer();
          break;
        case 'admin':
          if (e.cleSession) { this.cleSession = e.cleSession; }
          this.attentes.get(e.requete)?.({ erreur: 0, cleSession: e.cleSession });
          this.attentes.delete(e.requete);
          break;
        case 'routage':
          this.attentes.get(e.requete)?.({ erreur: e.erreur });
          this.attentes.delete(e.requete);
          break;
        case 'progression':
          this.rearmer();
          break;
        case 'config_terminee':
          if (e.identifiant === this.etape) { this.finEtape?.(); }
          break;
        case 'texte':
          if (!this.monNumero || e.de === this.monNumero || !e.texte) { break; }
          if (e.vers === this.monNumero) {
            this.surMessage({ genre: 'DM', expediteur: e.de, texte: e.texte });
          } else if (e.vers === MT_DIFFUSION) {
            // Le canal 0 sans nom est le canal primaire par défaut, que le firmware nomme
            // selon le préréglage (LongFast…) sans l'écrire dans la configuration.
            this.surMessage({
              genre: 'CANAL', expediteur: e.de, texte: e.texte,
              canalNom: this.canaux.get(e.canal) || '',
            });
          }
          break;
      }
    }
  }

  async envoyerDm(destination: string | number, texte: string): Promise<void> {
    const numero = Number(destination);
    if (!Number.isInteger(numero) || numero <= 0 || numero >= MT_DIFFUSION) {
      throw new Error(`Destinataire Meshtastic invalide : ${destination}`);
    }
    for (const morceau of decouperTexte(texte)) {
      await this.ecrire(toRadioTexte(numero, morceau, nouvelIdentifiant()));
    }
  }

  /** Message sur un canal de la radio, par son emplacement. */
  async envoyerCanal(index: number, texte: string): Promise<void> {
    if (!this.canaux.has(index)) { throw new Error(`Aucun canal actif à l'emplacement ${index}.`); }
    for (const morceau of decouperTexte(texte)) {
      await this.ecrire(toRadioTexteCanal(index, morceau, nouvelIdentifiant()));
    }
  }

  // ══ Administration de la radio locale ══════════════════════════════════════

  /** Envoie une commande d'administration et attend sa réponse (accusé de routage ou réponse
   * d'administration portant le même identifiant de requête). */
  private async commandeAdmin(admin: Uint8Array): Promise<{ erreur: number; cleSession?: string }> {
    if (!this.monNumero) { throw new Error('Radio non identifiée.'); }
    const id = nouvelIdentifiant();
    const reponse = new Promise<{ erreur: number; cleSession?: string }>(
      r => this.attentes.set(id, r));
    await this.ecrire(toRadioAdmin(this.monNumero, admin, id));
    try {
      return await delai(reponse, 10000, 'La radio ne répond pas à la commande.');
    } finally {
      this.attentes.delete(id);
    }
  }

  /** La clé de session, demandée à la radio si on ne l'a pas : sa réponse au « qui es-tu » la
   * porte. Même méthode que le client officiel et qu'Android. */
  private async assurerCleSession(forcer = false): Promise<string> {
    if (this.cleSession && !forcer) { return this.cleSession; }
    const r = await this.commandeAdmin(adminDemandeProprietaire());
    if (!r.cleSession && !this.cleSession) {
      throw new Error("La radio n'a pas fourni de clé de session : firmware trop ancien ?");
    }
    return this.cleSession;
  }

  /** Une commande qui porte la clé de session, retentée une fois si la radio la refuse
   * (`ADMIN_BAD_SESSION_KEY`) — les clés expirent au bout de quelques minutes. */
  private async commandeAvecSession(fabriquer: (cle: string) => Uint8Array): Promise<void> {
    let r = await this.commandeAdmin(fabriquer(await this.assurerCleSession()));
    if (r.erreur === ERREUR_ROUTAGE.MAUVAISE_CLE_SESSION) {
      r = await this.commandeAdmin(fabriquer(await this.assurerCleSession(true)));
    }
    if (r.erreur !== ERREUR_ROUTAGE.AUCUNE) {
      throw new Error(`La radio a refusé la modification (code ${r.erreur}).`);
    }
  }

  /** Écrit un canal dans un emplacement. Jamais l'emplacement 0 en secondaire : c'est le
   * primaire, il ne peut pas être autre chose. */
  async ecrireCanal(index: number, nom: string, pskHex: string): Promise<void> {
    const role = index === 0 ? ROLE_CANAL.PRIMAIRE : ROLE_CANAL.SECONDAIRE;
    await this.commandeAvecSession(cle => adminEcrireCanal(index, nom, pskHex, role, cle));
    this.emplacements.set(index, { index, nom, role, pskHex });
    this.canaux.set(index, nom);
  }

  /** Libère un emplacement. Le primaire ne se supprime pas : la radio n'aurait plus de canal
   * par défaut. */
  async supprimerCanal(index: number): Promise<void> {
    if (index === 0) { throw new Error('Le canal primaire ne se supprime pas.'); }
    await this.commandeAvecSession(cle => adminSupprimerCanal(index, cle));
    this.emplacements.set(index, { index, nom: '', role: ROLE_CANAL.DESACTIVE, pskHex: '' });
    this.canaux.delete(index);
  }

  async cycle(): Promise<void> {
    if (Date.now() - this.dernierBattement >= BATTEMENT_MESHTASTIC_MS) {
      await this.battre();
    }
    // En HTTP rien n'arrive tout seul ; en Bluetooth c'est un filet si une notification s'est
    // perdue. En série, sans effet.
    await this.transport.tirer();
  }
}

/** Un emplacement de canal tel que la radio le décrit. */
export interface EmplacementCanal {
  index: number;
  nom: string;
  /** 0 désactivé, 1 primaire, 2 secondaire. */
  role: number;
  pskHex: string;
}

export function creerPilote(protocole: Protocole, transport: Transport): Pilote {
  return protocole === 'MESHTASTIC' ? new PiloteMeshtastic(transport) : new PiloteMeshCore(transport);
}
