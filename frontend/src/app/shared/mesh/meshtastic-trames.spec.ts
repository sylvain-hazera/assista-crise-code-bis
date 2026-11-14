import {
  DecoupeurMeshtastic, MT_DIFFUSION, NONCE_CONFIG, NONCE_NOEUDS, PREMIER_NONCE_BATTEMENT,
  decouperTexte, encadrerMeshtastic, lireFromRadio, nonceSuivant, octetsDeReveil,
  toRadioBattement, toRadioTexte, toRadioVeutConfig,
} from './meshtastic-trames';
import { EcrivainProtobuf } from './protobuf-mini';

/**
 * Le protocole client Meshtastic, vérifié sans radio.
 *
 * **Chaque vecteur hexadécimal ci-dessous est produit par la bibliothèque protobuf officielle**
 * (`meshtastic.protobuf.mesh_pb2`, version 2.7.11, exécutée dans l'image du pont Meshtastic) —
 * jamais écrit à la main. La leçon vient du relais MeshCore : un test qui vérifie un encodeur
 * contre l'hypothèse de son propre auteur laisse passer l'erreur, et l'en-tête série MeshCore
 * était faux depuis le premier jour sans qu'aucun test ne bronche.
 */
const VECTEURS = {
  to_want_config: '18f8acd19101',
  to_heartbeat: '3a00',
  to_texte_dm: '0a2215fecaad0b2214080112105265c3a7752c206f6e2061727269766535040302015001',
  from_my_info: '08071a0608cdd7d29101',
  from_node_info: '224d08cdd7d2910112400a09213132333461626364120b52616b20646520467265641a0452414b4642200001'
    + '02030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f250000d040',
  from_channel: '52130801120d1201011a0846725f454d434f4d1802',
  from_config_complete: '38f8acd19101',
  from_texte_dm: '123d0dfecaad0b15cdab34122215080112114172726976c3a97320737572207a6f6e6535efbeadde3d60c5'
    + '166945000050c04803609fffffffffffffffff01',
  from_texte_canal: '12280dfecaad0b15ffffffff1801221508011211526f75746520636f7570c3a965204432303505000000',
  from_chiffre: '121d0dfecaad0b15cdab34122a0c9999999999999999999999993506000000',
  from_position: '12150dfecaad0b15cdab34122209080312050d00000000',
};

const hex = (o: Uint8Array) => Array.from(o).map(x => x.toString(16).padStart(2, '0')).join('');
const octets = (h: string) => Uint8Array.from(h.match(/../g)!.map(x => parseInt(x, 16)));

describe('Protocole Meshtastic', () => {

  describe('ToRadio, comparé à mesh_pb2', () => {
    it('want_config_id', () => {
      expect(hex(toRadioVeutConfig(0x12345678))).toBe(VECTEURS.to_want_config);
    });

    it('heartbeat sans nonce : le sous-message vide est écrit', () => {
      // Forme d'origine, gardée comme vecteur de l'encodeur ; le pilote ne l'envoie plus.
      expect(hex(new EcrivainProtobuf().message(7, new EcrivainProtobuf()).fin()))
        .toBe(VECTEURS.to_heartbeat);
    });

    it('heartbeat avec nonce, comme le client officiel', () => {
      expect(hex(toRadioBattement(2))).toBe('3a020802');
      expect(hex(toRadioBattement(300))).toBe('3a0308ac02');
    });

    it('les nonces de battement ne repassent jamais par 0 ni 1', () => {
      expect(PREMIER_NONCE_BATTEMENT).toBe(2);
      expect(nonceSuivant(2)).toBe(3);
      expect(nonceSuivant(0xffffffff)).toBe(2);
    });

    it('les deux identifiants réservés de la poignée de main', () => {
      expect(hex(toRadioVeutConfig(NONCE_CONFIG))).toBe('18ac9e04');
      expect(hex(toRadioVeutConfig(NONCE_NOEUDS))).toBe('18ad9e04');
    });

    it('message texte direct avec accusé de réception', () => {
      expect(hex(toRadioTexte(0x0BADCAFE, 'Reçu, on arrive', 0x01020304)))
        .toBe(VECTEURS.to_texte_dm);
    });
  });

  describe('FromRadio, produit par mesh_pb2', () => {
    it('lit le numéro de la radio', () => {
      expect(lireFromRadio(octets(VECTEURS.from_my_info)))
        .toEqual({ genre: 'mon_noeud', numero: 0x1234ABCD });
    });

    it('lit le nom et la clé publique d\'un nœud', () => {
      const e = lireFromRadio(octets(VECTEURS.from_node_info));
      expect(e.genre).toBe('noeud');
      if (e.genre !== 'noeud') { return; }
      expect(e.numero).toBe(0x1234ABCD);
      expect(e.nomLong).toBe('Rak de Fred');
      expect(e.clePubliqueHex).toBe(hex(Uint8Array.from({ length: 32 }, (_, i) => i)));
    });

    it('lit un canal configuré, sans toucher à sa clé', () => {
      expect(lireFromRadio(octets(VECTEURS.from_channel)))
        .toEqual({ genre: 'canal', index: 1, nom: 'Fr_EMCOM', actif: true });
    });

    it('reconnaît la fin de la configuration', () => {
      expect(lireFromRadio(octets(VECTEURS.from_config_complete)))
        .toEqual({ genre: 'config_terminee', identifiant: 0x12345678 });
    });

    it('lit un message direct — y compris un RSSI négatif sur 10 octets', () => {
      expect(lireFromRadio(octets(VECTEURS.from_texte_dm))).toEqual({
        genre: 'texte', de: 0x0BADCAFE, vers: 0x1234ABCD, canal: 0,
        texte: 'Arrivés sur zone', id: 0xDEADBEEF,
      });
    });

    it('lit un message de canal adressé à tous', () => {
      const e = lireFromRadio(octets(VECTEURS.from_texte_canal));
      expect(e).toEqual({
        genre: 'texte', de: 0x0BADCAFE, vers: MT_DIFFUSION, canal: 1,
        texte: 'Route coupée D20', id: 5,
      });
    });

    it('compte comme progression une trame de configuration', () => {
      expect(lireFromRadio(octets('2a0432023803'))).toEqual({ genre: 'progression' });
      expect(lireFromRadio(octets('6a080a06322e372e3135'))).toEqual({ genre: 'progression' });
    });

    it('mais pas l\'état de la file d\'envoi', () => {
      expect(lireFromRadio(octets('5a021010'))).toEqual({ genre: 'autre' });
    });

    it('ignore un paquet chiffré qu\'elle n\'a pas pu ouvrir', () => {
      expect(lireFromRadio(octets(VECTEURS.from_chiffre))).toEqual({ genre: 'autre' });
    });

    it('ignore ce qui n\'est pas du texte', () => {
      expect(lireFromRadio(octets(VECTEURS.from_position))).toEqual({ genre: 'autre' });
    });

    it('refuse une trame tronquée plutôt que d\'en tirer un numéro faux', () => {
      expect(() => lireFromRadio(octets(VECTEURS.from_texte_dm).slice(0, 20))).toThrow();
    });
  });

  describe('cadrage série', () => {
    it('encadre en 0x94 0xC3 et longueur gros-boutiste', () => {
      expect(hex(encadrerMeshtastic(octets('3a00')))).toBe('94c300023a00');
    });

    it('réveille la radio avec 32 octets 0xC3', () => {
      const r = octetsDeReveil();
      expect(r.length).toBe(32);
      expect(r.every(o => o === 0xc3)).toBeTrue();
    });

    it('recolle une trame coupée et saute les journaux texte du firmware', () => {
      const d = new DecoupeurMeshtastic();
      const trame = encadrerMeshtastic(octets(VECTEURS.from_my_info));
      const journal = new TextEncoder().encode('DEBUG | 12:00:01 boot\r\n');

      expect(d.pousser(new Uint8Array([...journal, ...trame.slice(0, 5)]))).toEqual([]);
      expect(d.pousser(trame.slice(5))).toEqual([octets(VECTEURS.from_my_info)]);
    });

    it('se resynchronise après une longueur aberrante', () => {
      const d = new DecoupeurMeshtastic();
      const bonne = encadrerMeshtastic(octets('3a00'));
      expect(d.pousser(new Uint8Array([0x94, 0xc3, 0xff, 0xff, ...bonne])))
        .toEqual([octets('3a00')]);
    });
  });

  describe('découpe des textes longs', () => {
    it('ne coupe jamais un caractère UTF-8 en deux', () => {
      const morceaux = decouperTexte('é'.repeat(150), 200);
      expect(morceaux.length).toBe(2);
      expect(morceaux.join('')).toBe('é'.repeat(150));
      for (const m of morceaux) {
        expect(new TextEncoder().encode(m).length).toBeLessThanOrEqual(200);
      }
    });

    it('laisse intact un texte court', () => {
      expect(decouperTexte('ok')).toEqual(['ok']);
    });
  });
});
