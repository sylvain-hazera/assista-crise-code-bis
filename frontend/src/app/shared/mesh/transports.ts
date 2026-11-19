/**
 * Les trois façons dont un navigateur parle à une radio : USB, Bluetooth, réseau local.
 *
 * | | USB (Web Serial) | Bluetooth (Web Bluetooth) | Réseau local (HTTP) |
 * |---|---|---|---|
 * | MeshCore | oui | oui | **impossible** — TCP brut |
 * | Meshtastic | oui | oui | oui |
 *
 * Un transport ne connaît **rien** du protocole : il ouvre, écrit, rend ce qu'il reçoit et
 * signale une perte. Seule distinction qui le concerne : un **flux** d'octets (série — le
 * protocole doit encadrer et découper) contre des **paquets** (Bluetooth, HTTP — chaque écriture
 * est un message entier).
 *
 * Disponibilité, à dire à l'écran plutôt qu'à laisser découvrir : Web Serial et Web Bluetooth
 * n'existent que sur Chrome et Edge (ordinateur et Android) ; Web Bluetooth est en plus derrière
 * un drapeau expérimental sur Linux. Ni Firefox, ni Safari, ni iOS.
 */
import { PortSerie, apiSerie } from './web-serial';

export type NomTransport = 'USB' | 'BLE' | 'WIFI';

export interface Transport {
  readonly nom: NomTransport;
  /** Flux d'octets à encadrer (série), ou paquets entiers (Bluetooth, HTTP). */
  readonly flux: boolean;
  /** Ce qui identifie la liaison à l'écran : « port USB », « Heltec_A1B2 », « 192.168.1.50 ». */
  readonly libelle: string;
  /** Ouvre la liaison. Rappelée telle quelle pour se reconnecter, sans nouveau geste. */
  ouvrir(): Promise<void>;
  ecrire(octets: Uint8Array): Promise<void>;
  /** Va chercher ce qui attend côté radio, pour les transports où il faut le demander. */
  tirer(): Promise<void>;
  fermer(): Promise<void>;
  surDonnees: (octets: Uint8Array) => void;
  surPerte: (raison: string) => void;
}

const rien = () => undefined;
const attendre = (ms: number) => new Promise(r => setTimeout(r, ms));

/**
 * Tampon de lecture du port : 64 Ko. Relevé dans le client web officiel Meshtastic — celui de
 * Web Serial par défaut fait 255 octets, soit une ou deux fiches de nœud ; pendant le
 * téléchargement de la base de nœuds, une carte ESP32-S3 en USB natif **perd des trames** dès
 * que le fil principal du navigateur est occupé.
 */
const TAMPON_SERIE = 64 * 1024;

/** Nouvelles tentatives d'ouverture d'un port encore occupé — typiquement juste après une
 * fermeture, lors d'une reconnexion. Mêmes délais que le client officiel. */
const REESSAIS_OUVERTURE_MS = [250, 500, 750];

function portOccupe(e: unknown): boolean {
  if (!(e instanceof Error)) { return false; }
  return e.name === 'InvalidStateError'
    || /already open|failed to open serial port|access is denied/i.test(e.message);
}

// ══ USB ══════════════════════════════════════════════════════════════════════

export class TransportSerie implements Transport {
  readonly nom = 'USB' as const;
  readonly flux = true;
  readonly libelle = 'port USB';
  surDonnees: (octets: Uint8Array) => void = rien;
  surPerte: (raison: string) => void = rien;

  private lecteur: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private ecrivain: WritableStreamDefaultWriter<Uint8Array> | null = null;
  private ferme = false;

  /** On garde l'objet `SerialPort` : il reste valide après un débranchement, et c'est lui
   * qu'on rouvre — `getPorts()[0]` désignerait n'importe quelle radio dès qu'il y en a deux. */
  private constructor(private port: PortSerie, private debit: number) {}

  /** Exige un geste de l'utilisateur : à appeler directement depuis le clic. */
  static async choisir(debit: number): Promise<TransportSerie> {
    return new TransportSerie(await apiSerie().requestPort(), debit);
  }

  async ouvrir(): Promise<void> {
    this.ferme = false;
    for (let essai = 0; ; essai++) {
      try {
        await this.port.open({ baudRate: this.debit, bufferSize: TAMPON_SERIE });
        break;
      } catch (e) {
        if (!portOccupe(e) || essai >= REESSAIS_OUVERTURE_MS.length) { throw e; }
        await attendre(REESSAIS_OUVERTURE_MS[essai]);
      }
    }
    // DTR et RTS levés ENSEMBLE, comme Android et le client officiel : les basculer un par un
    // peut redémarrer un ESP32 (circuit de réinitialisation automatique). C'est aussi ce que
    // fait pyserial par défaut, donc ce que vivent déjà nos ponts Python.
    try {
      await this.port.setSignals?.({ dataTerminalReady: true, requestToSend: true });
    } catch { /* adaptateur sans lignes de contrôle : sans conséquence */ }
    this.lecteur = this.port.readable?.getReader() ?? null;
    this.ecrivain = this.port.writable?.getWriter() ?? null;
    if (!this.lecteur || !this.ecrivain) {
      throw new Error('Ce port ne peut pas être lu et écrit.');
    }
    void this.lire(this.lecteur);
  }

  private async lire(lecteur: ReadableStreamDefaultReader<Uint8Array>): Promise<void> {
    try {
      for (;;) {
        const { value, done } = await lecteur.read();
        if (done) { break; }
        if (value?.length) { this.surDonnees(value); }
      }
      if (!this.ferme) { this.surPerte('Liaison USB fermée par la radio.'); }
    } catch (e) {
      if (!this.ferme) { this.surPerte(e instanceof Error ? e.message : String(e)); }
    }
  }

  async ecrire(octets: Uint8Array): Promise<void> {
    if (!this.ecrivain) { throw new Error('Port USB fermé.'); }
    await this.ecrivain.write(octets);
  }

  async tirer(): Promise<void> { /* la radio écrit d'elle-même sur un port série */ }

  async fermer(): Promise<void> {
    this.ferme = true;
    try { await this.lecteur?.cancel(); } catch { /* déjà fermé */ }
    try { this.lecteur?.releaseLock(); } catch { /* déjà relâché */ }
    try { this.ecrivain?.releaseLock(); } catch { /* déjà relâché */ }
    try { await this.port.close(); } catch { /* déjà fermé */ }
    this.lecteur = null;
    this.ecrivain = null;
  }
}

// ══ Bluetooth ════════════════════════════════════════════════════════════════
// Types minimaux, décrits ici plutôt qu'importés : même raisonnement que web-serial.ts.

interface Caracteristique extends EventTarget {
  readonly value: DataView | null;
  readValue(): Promise<DataView>;
  writeValueWithResponse(donnees: BufferSource): Promise<void>;
  startNotifications(): Promise<Caracteristique>;
}
interface ServiceGatt { getCharacteristic(uuid: string): Promise<Caracteristique>; }
interface ServeurGatt {
  readonly connected: boolean;
  connect(): Promise<ServeurGatt>;
  disconnect(): void;
  getPrimaryService(uuid: string): Promise<ServiceGatt>;
}
interface AppareilBluetooth extends EventTarget {
  readonly name?: string;
  readonly gatt?: ServeurGatt;
}
interface ApiBluetooth {
  requestDevice(options: { filters: { services: string[] }[]; optionalServices?: string[] })
    : Promise<AppareilBluetooth>;
}

export function bluetoothDisponible(): boolean {
  return typeof navigator !== 'undefined' && 'bluetooth' in navigator;
}

function apiBluetooth(): ApiBluetooth {
  const api = (navigator as unknown as { bluetooth?: ApiBluetooth }).bluetooth;
  if (!api) {
    throw new Error("Ce navigateur n'expose pas le Bluetooth. Chrome ou Edge sont nécessaires "
      + '(sous Linux, le drapeau chrome://flags/#enable-experimental-web-platform-features).');
  }
  return api;
}

function versOctets(vue: DataView | null): Uint8Array {
  return vue ? new Uint8Array(vue.buffer, vue.byteOffset, vue.byteLength).slice() : new Uint8Array(0);
}

/**
 * Le profil GATT d'un protocole. Les deux radios n'exposent pas du tout la même chose :
 *
 * - **MeshCore** : le service UART Nordic. On écrit sur RX, chaque notification de TX est une
 *   trame entière (`ble_cx.py`) ;
 * - **Meshtastic** : on écrit sur TO_RADIO ; FROM_NUM notifie qu'il y a du courrier, qu'il faut
 *   alors **lire en boucle** sur FROM_RADIO jusqu'à obtenir une valeur vide
 *   (`ble_interface.py::_receiveFromRadioImpl`).
 */
export interface ProfilBle {
  service: string;
  ecriture: string;
  /** MeshCore : les données arrivent par notification. */
  notification?: string;
  /** Meshtastic : notification « il y a du courrier » puis lecture en boucle. */
  signal?: string;
  lecture?: string;
}

export class TransportBle implements Transport {
  readonly nom = 'BLE' as const;
  readonly flux = false;
  surDonnees: (octets: Uint8Array) => void = rien;
  surPerte: (raison: string) => void = rien;

  private carEcriture: Caracteristique | null = null;
  private carLecture: Caracteristique | null = null;
  private ferme = false;
  private enLecture = false;
  private relire = false;

  private constructor(private appareil: AppareilBluetooth, private profil: ProfilBle) {
    // Une seule fois par appareil : rouvrir ne doit pas empiler les écouteurs.
    appareil.addEventListener('gattserverdisconnected', () => {
      if (!this.ferme) { this.surPerte('Liaison Bluetooth perdue.'); }
    });
  }

  get libelle(): string {
    return this.appareil.name || 'radio Bluetooth';
  }

  /** Exige un geste de l'utilisateur. Le filtre sur le service ne propose que les radios du
   * bon protocole dans la fenêtre de choix du navigateur. */
  static async choisir(profil: ProfilBle): Promise<TransportBle> {
    const appareil = await apiBluetooth().requestDevice({ filters: [{ services: [profil.service] }] });
    return new TransportBle(appareil, profil);
  }

  /**
   * Connexion GATT, retentée une fois après 750 ms sur l'erreur transitoire d'une radio qui
   * sort de veille (`NetworkError: Connection attempt failed`) — comme le client officiel.
   */
  private async connecter(gatt: ServeurGatt): Promise<ServeurGatt> {
    if (gatt.connected) { return gatt; }
    try {
      return await gatt.connect();
    } catch (premiere) {
      const transitoire = premiere instanceof Error
        && (premiere.name === 'NetworkError' || /connection attempt failed|gatt/i.test(premiere.message));
      if (!transitoire) {
        throw new Error('Connexion Bluetooth impossible. Vérifiez que la radio est allumée, à '
          + "portée, et qu'elle n'est pas déjà connectée à un téléphone ou à un autre onglet.");
      }
      await attendre(750);
      try {
        return await gatt.connect();
      } catch {
        throw new Error('Connexion Bluetooth impossible après deux essais. Une radio déjà '
          + 'connectée à un téléphone refuse le navigateur : fermez l\'application sur le '
          + 'téléphone, puis réessayez.');
      }
    }
  }

  async ouvrir(): Promise<void> {
    this.ferme = false;
    const gatt = this.appareil.gatt;
    if (!gatt) { throw new Error("Cette radio n'expose pas de service Bluetooth exploitable."); }
    const serveur = await this.connecter(gatt);
    let service: ServiceGatt;
    try {
      service = await serveur.getPrimaryService(this.profil.service);
    } catch {
      throw new Error("Cette radio n'expose pas le service Bluetooth attendu : firmware trop "
        + 'ancien, ou radio dans un autre mode.');
    }
    this.carEcriture = await service.getCharacteristic(this.profil.ecriture);

    if (this.profil.notification) {
      const notif = await service.getCharacteristic(this.profil.notification);
      notif.addEventListener('characteristicvaluechanged',
        () => this.surDonnees(versOctets(notif.value)));
      await notif.startNotifications();
    }
    if (this.profil.lecture && this.profil.signal) {
      this.carLecture = await service.getCharacteristic(this.profil.lecture);
      const signal = await service.getCharacteristic(this.profil.signal);
      signal.addEventListener('characteristicvaluechanged', () => void this.tirer());
      await signal.startNotifications();
      // Amorce : des données attendent peut-être déjà (client officiel, même raison).
      void this.tirer();
    }
  }

  async ecrire(octets: Uint8Array): Promise<void> {
    if (!this.carEcriture) { throw new Error('Liaison Bluetooth fermée.'); }
    await this.carEcriture.writeValueWithResponse(octets as Uint8Array<ArrayBuffer>);
    // Meshtastic : la réponse attend dans FROM_RADIO, et la bibliothèque relit après chaque
    // écriture plutôt que de compter sur la notification.
    if (this.carLecture) { void this.tirer(); }
  }

  /** Lit FROM_RADIO jusqu'à une valeur vide. Une seule boucle à la fois : une notification
   * qui arrive pendant la lecture demande simplement un tour de plus. */
  async tirer(): Promise<void> {
    if (!this.carLecture) { return; }
    if (this.enLecture) { this.relire = true; return; }
    this.enLecture = true;
    try {
      do {
        this.relire = false;
        for (let vides = 0; vides < 3;) {
          const octets = versOctets(await this.carLecture.readValue());
          if (octets.length) { this.surDonnees(octets); vides = 0; } else { vides++; }
          if (!octets.length && vides < 3) { await new Promise(r => setTimeout(r, 100)); }
        }
      } while (this.relire && !this.ferme);
    } catch (e) {
      if (!this.ferme) { this.surPerte(e instanceof Error ? e.message : String(e)); }
    } finally {
      this.enLecture = false;
    }
  }

  async fermer(): Promise<void> {
    this.ferme = true;
    try { this.appareil.gatt?.disconnect(); } catch { /* déjà déconnecté */ }
    this.carEcriture = null;
    this.carLecture = null;
  }
}

// ══ Réseau local : API HTTP d'un nœud Meshtastic ══════════════════════════════

/**
 * L'API HTTP du firmware Meshtastic (`ContentHandler.cpp`) :
 *
 * - `PUT /api/v1/toradio` — un `ToRadio` par requête ;
 * - `GET /api/v1/fromradio` — un `FromRadio` par requête, **corps vide** quand rien n'attend.
 *
 * Le firmware répond `Access-Control-Allow-Origin: *`, ce qui rend l'appel possible depuis notre
 * page. Reste le contenu mixte : une page HTTPS qui appelle `http://192.168.1.50`. Chrome
 * l'accepte pour une **adresse locale** une fois que l'utilisateur a donné l'autorisation
 * « appareils du réseau local » (Local Network Access) ; `targetAddressSpace: 'local'` le
 * signale d'avance pour un nom d'hôte (`meshtastic.local`), qu'une IP privée n'exige pas.
 *
 * Deux limites du firmware, pas de nous : **un seul client** à la fois sur `fromradio` (l'appli
 * Meshtastic ouverte sur le même nœud nous volerait les messages), et **pas
 * d'authentification** — qui est sur le réseau local parle à la radio.
 */
export class TransportHttpMeshtastic implements Transport {
  readonly nom = 'WIFI' as const;
  readonly flux = false;
  surDonnees: (octets: Uint8Array) => void = rien;
  surPerte: (raison: string) => void = rien;

  private ferme = false;
  private enLecture = false;
  private readonly base: string;

  constructor(adresse: string) {
    this.base = TransportHttpMeshtastic.normaliser(adresse);
  }

  get libelle(): string {
    return this.base.replace(/^https?:\/\//, '');
  }

  /** « 192.168.1.50 », « meshtastic.local », « https://10.0.0.5 » → URL de base. */
  static normaliser(adresse: string): string {
    const propre = (adresse || '').trim().replace(/\/+$/, '');
    if (!propre) { throw new Error("Indiquez l'adresse de la radio sur le réseau local."); }
    const url = /^https?:\/\//i.test(propre) ? propre : `http://${propre}`;
    let hote: string;
    try { hote = new URL(url).hostname; } catch { throw new Error(`Adresse invalide : ${adresse}`); }
    if (!TransportHttpMeshtastic.estLocal(hote)) {
      // Pas un garde-fou de sécurité — le navigateur en a un — mais une erreur claire tout de
      // suite plutôt qu'un échec réseau incompréhensible plus tard.
      throw new Error(`${hote} n'est pas une adresse du réseau local (192.168.x.x, 10.x.x.x, `
        + '172.16–31.x.x ou un nom en .local).');
    }
    return url;
  }

  static estLocal(hote: string): boolean {
    if (/\.local$/i.test(hote)) { return true; }
    const m = hote.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
    if (!m) { return false; }
    const [a, b] = [Number(m[1]), Number(m[2])];
    return a === 10 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31)
      || (a === 169 && b === 254);
  }

  /**
   * `targetAddressSpace: 'local'` seulement pour du `http://` depuis une page HTTPS — le seul
   * cas où l'exemption de contenu mixte joue — comme le client officiel (`localNetwork.ts`).
   * Chrome rejette la requête si l'hôte se révèle public ; les autres navigateurs ignorent
   * l'option.
   *
   * Et un délai d'expiration sur chaque requête (7 s en lecture, 4 s en écriture, ceux du client
   * officiel) : sans lui, une requête pendue bloquait la lecture pour toujours.
   */
  private options(init: RequestInit, delaiMs: number): RequestInit {
    const resultat: RequestInit & { targetAddressSpace?: string } = {
      ...init, cache: 'no-store', signal: AbortSignal.timeout(delaiMs),
    };
    if (this.base.startsWith('http:') && globalThis.location?.protocol === 'https:') {
      resultat.targetAddressSpace = 'local';
    }
    return resultat as RequestInit;
  }

  /**
   * Une page HTTPS qui appelle `http://192.168.x.x` : seuls Chrome et Edge l'autorisent (après
   * la demande « appareils du réseau local »). Firefox et Safari bloquent l'appel comme contenu
   * mixte, sans rien demander : mieux vaut le dire avant que laisser croire à une radio muette.
   * `navigator.userAgentData` n'existe que dans les navigateurs Chromium (Chrome sur iPhone est
   * un Safari : il est bien bloqué lui aussi).
   */
  static navigateurBloque(base: string, page = globalThis.location?.protocol,
                          chromium = !!(globalThis.navigator as { userAgentData?: unknown } | undefined)?.userAgentData): boolean {
    return base.startsWith('http:') && page === 'https:' && !chromium;
  }

  async ouvrir(): Promise<void> {
    this.ferme = false;
    if (TransportHttpMeshtastic.navigateurBloque(this.base)) {
      throw new Error('Ce navigateur bloque la connexion à une radio du réseau local depuis ce site '
        + '(Firefox, Safari et les navigateurs sur iPhone). Ouvrez cette page dans Chrome ou Edge, '
        + "ou branchez la radio en USB ou en Bluetooth.");
    }
    // Une lecture d'essai : c'est elle qui déclenche l'autorisation « réseau local » et qui dit
    // tout de suite si la radio répond, plutôt qu'au premier message.
    const reponse = await this.lireUne();
    if (reponse.length) { this.surDonnees(reponse); }
  }

  private async lireUne(): Promise<Uint8Array> {
    let reponse: Response;
    try {
      reponse = await fetch(`${this.base}/api/v1/fromradio?all=false`,
                            this.options({ method: 'GET' }, 7000));
    } catch {
      throw new Error(`La radio ${this.libelle} ne répond pas. Vérifiez qu'elle est sur le même `
        + 'réseau, et autorisez ce site à accéder aux appareils du réseau local si le '
        + 'navigateur le demande.');
    }
    if (!reponse.ok) { throw new Error(`La radio a répondu ${reponse.status}.`); }
    return new Uint8Array(await reponse.arrayBuffer());
  }

  async ecrire(octets: Uint8Array): Promise<void> {
    let reponse: Response;
    try {
      reponse = await fetch(`${this.base}/api/v1/toradio`, this.options({
        method: 'PUT', headers: { 'Content-Type': 'application/x-protobuf' }, body: octets as Uint8Array<ArrayBuffer>,
      }, 4000));
    } catch (e) {
      this.surPerte(`Écriture vers ${this.libelle} impossible.`);
      throw e;
    }
    if (!reponse.ok) { throw new Error(`La radio a refusé l'écriture (${reponse.status}).`); }
    void this.tirer();
  }

  /** Lit jusqu'à un corps vide. Appelée à chaque cycle : en HTTP, rien n'arrive tout seul. */
  async tirer(): Promise<void> {
    if (this.enLecture || this.ferme) { return; }
    this.enLecture = true;
    try {
      // Borne : une radio qui débite sans fin (NodeDB énorme) ne doit pas bloquer le cycle.
      for (let n = 0; n < 200 && !this.ferme; n++) {
        const octets = await this.lireUne();
        if (!octets.length) { break; }
        this.surDonnees(octets);
      }
    } catch (e) {
      if (!this.ferme) { this.surPerte(e instanceof Error ? e.message : String(e)); }
    } finally {
      this.enLecture = false;
    }
  }

  async fermer(): Promise<void> {
    this.ferme = true;
  }
}
