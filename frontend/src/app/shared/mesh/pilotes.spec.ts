import { PiloteMeshCore, PiloteMeshtastic, MessageRadio } from './pilotes';
import { REP, DEBUT_TRAME_RECUE } from './meshcore-trames';
import { encadrerMeshtastic, toRadioTexte } from './meshtastic-trames';
import { champ, lireChamps } from './protobuf-mini';
import { Transport } from './transports';

/** Un transport qui note ce qu'on lui écrit, sans radio ni réseau. */
class FauxTransport implements Transport {
  readonly nom = 'USB' as const;
  readonly libelle = 'faux';
  ecrits: Uint8Array[] = [];
  surDonnees: (o: Uint8Array) => void = () => undefined;
  surPerte: (r: string) => void = () => undefined;
  constructor(readonly flux: boolean) {}
  async ouvrir() { /* rien */ }
  async ecrire(o: Uint8Array) { this.ecrits.push(o); }
  async tirer() { /* rien */ }
  async fermer() { /* rien */ }
}

const hex = (o: Uint8Array) => Array.from(o).map(x => x.toString(16).padStart(2, '0')).join('');
const octets = (h: string) => Uint8Array.from(h.match(/../g)!.map(x => parseInt(x, 16)));
const pause = () => new Promise(r => setTimeout(r, 0));

/** Trame radio → application, en série : 0x3e + longueur LE. */
function trameRecue(charge: Uint8Array): Uint8Array {
  return new Uint8Array([DEBUT_TRAME_RECUE, charge.length & 0xff, charge.length >> 8, ...charge]);
}

function selfInfo(nom: string): Uint8Array {
  const n = new TextEncoder().encode(nom);
  const c = new Uint8Array(58 + n.length);
  c[0] = REP.SELF_INFO;
  c.fill(0xab, 4, 36);
  c.set(n, 58);
  return c;
}

describe('Pilote MeshCore', () => {
  it('se présente en 0x3c sur un port série et lit l\'identité de la radio', async () => {
    const t = new FauxTransport(true);
    const p = new PiloteMeshCore(t);

    const identite = p.demarrer();
    await pause();
    // Séquence des clients de référence : DEVICE_QUERY v3, puis APP_START, tout en 0x3c.
    expect(hex(t.ecrits[0])).toBe('3c02001603');
    expect(Array.from(t.ecrits[1].slice(0, 4))).toEqual([0x3c, 0x0f, 0x00, 0x01]);
    p.recevoir(trameRecue(selfInfo('Heltec V3')));

    expect(await identite).toEqual({ pubkey_hex: 'ab'.repeat(32), nom: 'Heltec V3' });
    // Puis la radio est remise à l'heure.
    expect(t.ecrits.at(-1)![3]).toBe(0x06);
  });

  it('n\'encadre rien en Bluetooth : une écriture est une trame', async () => {
    const t = new FauxTransport(false);
    const p = new PiloteMeshCore(t);

    const identite = p.demarrer();
    await pause();
    expect(hex(t.ecrits[0])).toBe('1603');   // DEVICE_QUERY nu
    expect(t.ecrits[1][0]).toBe(0x01);       // APP_START nu
    p.recevoir(selfInfo('T-Deck'));

    expect((await identite).nom).toBe('T-Deck');
  });

  it('remonte un message direct et relève le suivant', async () => {
    const t = new FauxTransport(false);
    const p = new PiloteMeshCore(t);
    const recus: MessageRadio[] = [];
    p.surMessage = m => recus.push(m);

    // CONTACT_MSG_RECV : type, préfixe(6), chemin(1), type de texte(1), horodatage(4), texte
    const texte = new TextEncoder().encode('Besoin d\'eau');
    p.recevoir(new Uint8Array([REP.CONTACT_MSG_RECV, 1, 2, 3, 4, 5, 6, 0xff, 0, 0, 0, 0, 0, ...texte]));
    await pause();

    expect(recus).toEqual([{ genre: 'DM', expediteur: '010203040506', texte: 'Besoin d\'eau' }]);
    expect(t.ecrits.at(-1)).toEqual(new Uint8Array([0x0a]));
  });

  it('« envoyé » attend l\'accord de la radio', async () => {
    const t = new FauxTransport(false);
    const p = new PiloteMeshCore(t);

    const envoi = p.envoyerDm('ee'.repeat(32), 'ok');
    await pause();
    p.recevoir(new Uint8Array([REP.MSG_SENT, 0, 1, 2, 3, 4, 0, 0, 0, 0]));

    await expectAsync(envoi).toBeResolved();
  });

  it('un refus de la radio fait échouer l\'envoi au lieu de le dire réussi', async () => {
    const t = new FauxTransport(false);
    const p = new PiloteMeshCore(t);

    const envoi = p.envoyerDm('ee'.repeat(32), 'ok');
    await pause();
    p.recevoir(new Uint8Array([REP.ERROR, 2]));

    await expectAsync(envoi).toBeRejectedWithError(/refusé/);
  });
});

describe('Pilote Meshtastic', () => {
  /** Attend qu'une écriture correspondant à ces octets (sans cadrage) soit passée. */
  async function attendreEcriture(t: FauxTransport, attendu: string) {
    const vue = (o: Uint8Array) => hex(t.flux && o[0] === 0x94 ? o.slice(4) : o);
    for (let n = 0; n < 100 && !t.ecrits.some(o => vue(o) === attendu); n++) {
      await new Promise(r => setTimeout(r, 10));
    }
    expect(t.ecrits.some(o => vue(o) === attendu)).withContext(`écriture ${attendu}`).toBeTrue();
  }

  /**
   * Rejoue une radio réelle : étape « configuration » (69420), battement, étape « base de
   * nœuds » (69421). Vecteurs produits par mesh_pb2 (voir meshtastic-trames.spec.ts).
   */
  async function configurer(p: PiloteMeshtastic, t: FauxTransport) {
    const envoyer = (h: string) => {
      const o = octets(h);
      p.recevoir(t.flux ? encadrerMeshtastic(o) : o);
    };
    const identite = p.demarrer();

    await attendreEcriture(t, '18ac9e04');                                     // want 69420
    envoyer('08071a0608cdd7d29101');                                           // my_info
    envoyer('2a0432023803');                                                   // config
    envoyer('52130801120d1201011a0846725f454d434f4d1802');                     // canal 1
    envoyer('38ac9e04');                                                       // fin 69420

    await attendreEcriture(t, '3a020802');                                     // battement, nonce 2
    await attendreEcriture(t, '18ad9e04');                                     // want 69421
    envoyer('224d08cdd7d2910112400a09213132333461626364120b52616b20646520467265641a0452414b4642200001'
      + '02030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f250000d040');   // node_info
    envoyer('38ad9e04');                                                       // fin 69421
    return identite;
  }

  it('lit son numéro, son nom et sa clé pendant la configuration', async () => {
    const t = new FauxTransport(false);
    const p = new PiloteMeshtastic(t);

    const identite = await configurer(p, t);

    expect(identite.node_num).toBe(0x1234ABCD);
    expect(identite.nom).toBe('Rak de Fred');
    expect(identite.cle_publique_hex?.length).toBe(64);
    expect(p.canaux.get(1)).toBe('Fr_EMCOM');
  });

  it('réveille un port série et encadre ses demandes', async () => {
    const t = new FauxTransport(true);
    const p = new PiloteMeshtastic(t);

    await configurer(p, t);

    expect(t.ecrits[0].length).toBe(32);                 // 32 × 0xC3
    expect(t.ecrits[0].every(o => o === 0xc3)).toBeTrue();
    expect(Array.from(t.ecrits[1].slice(0, 2))).toEqual([0x94, 0xc3]);
  });

  it('refuse une configuration arrivée sans numéro de nœud', async () => {
    const t = new FauxTransport(false);
    const p = new PiloteMeshtastic(t);

    const identite = p.demarrer();
    await attendreEcriture(t, '18ac9e04');
    p.recevoir(octets('38ac9e04'));                      // fin sans my_info

    await expectAsync(identite).toBeRejectedWithError(/numéro de nœud/);
  });

  it('remonte un message direct, et un message de canal avec le nom du canal', async () => {
    const t = new FauxTransport(false);
    const p = new PiloteMeshtastic(t);
    const recus: MessageRadio[] = [];
    p.surMessage = m => recus.push(m);
    await configurer(p, t);

    p.recevoir(octets('123d0dfecaad0b15cdab34122215080112114172726976c3a97320737572207a6f6e6535efbeadde3d60c5'
      + '166945000050c04803609fffffffffffffffff01'));
    p.recevoir(octets('12280dfecaad0b15ffffffff1801221508011211526f75746520636f7570c3a965204432303505000000'));

    expect(recus).toEqual([
      { genre: 'DM', expediteur: 0x0BADCAFE, texte: 'Arrivés sur zone' },
      { genre: 'CANAL', expediteur: 0x0BADCAFE, texte: 'Route coupée D20', canalNom: 'Fr_EMCOM' },
    ]);
  });

  it('envoie un message direct au numéro du destinataire', async () => {
    const t = new FauxTransport(false);
    const p = new PiloteMeshtastic(t);
    await configurer(p, t);
    t.ecrits = [];

    await p.envoyerDm(0x0BADCAFE, 'Reçu, on arrive');

    // Même octets que mesh_pb2, à l'identifiant aléatoire près : on le relit et on recompose.
    const paquet = lireChamps(champ(lireChamps(t.ecrits[0]), 1)!.octets!);
    const id = champ(paquet, 6)!.nombre!;
    expect(hex(t.ecrits[0])).toBe(hex(toRadioTexte(0x0BADCAFE, 'Reçu, on arrive', id)));
  });

  it('refuse le numéro de diffusion comme destinataire d\'un message direct', async () => {
    const p = new PiloteMeshtastic(new FauxTransport(false));
    await expectAsync(p.envoyerDm(0xffffffff, 'x')).toBeRejected();
  });
});
