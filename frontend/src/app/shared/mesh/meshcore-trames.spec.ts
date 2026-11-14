import {
  CMD, DecoupeurDeTrames, REP, commandeAppStart, commandeEnvoiMessage, commandeHeure,
  commandeRequeteAppareil, commandeSimple, encadrer, hexVersOctets, lireSelfInfo,
  lireMessageRecu, octetsVersHex,
} from './meshcore-trames';

/**
 * Le cadrage et les commandes MeshCore, vérifiés sans radio.
 *
 * C'est tout l'intérêt d'avoir relevé les formats dans la bibliothèque Python dont dépend déjà
 * `meshcore-bridge` plutôt que dans une documentation : on peut les tester sur des vecteurs, et
 * la seule chose qui restera à découvrir sur du vrai matériel est le comportement du port série
 * lui-même.
 */
describe('Trames MeshCore', () => {

  describe('découpage', () => {
    it('rend une trame complète et garde le reliquat', () => {
      // Une lecture série coupe une trame n'importe où : c'est la première chose qui casse
      // quand on l'oublie.
      const d = new DecoupeurDeTrames();
      expect(d.pousser(new Uint8Array([0x3e, 0x03, 0x00, 0x00, 0x01]))).toEqual([]);
      expect(d.pousser(new Uint8Array([0x02]))).toEqual([new Uint8Array([0x00, 0x01, 0x02])]);
    });

    it('rend plusieurs trames arrivées dans le même paquet', () => {
      const d = new DecoupeurDeTrames();
      const trames = d.pousser(new Uint8Array([
        0x3e, 0x01, 0x00, 0x00,
        0x3e, 0x02, 0x00, 0x0a, 0x0b,
      ]));
      expect(trames).toEqual([new Uint8Array([0x00]), new Uint8Array([0x0a, 0x0b])]);
    });

    it('jette le bruit avant un début de trame', () => {
      // Branchement à chaud ou reconnexion : il reste des octets sans queue ni tête sur le fil.
      // C'est à cela que sert l'octet de début, et reader.py fait exactement pareil.
      const d = new DecoupeurDeTrames();
      const trames = d.pousser(new Uint8Array([0xff, 0x12, 0x3e, 0x01, 0x00, 0x07]));
      expect(trames).toEqual([new Uint8Array([0x07])]);
    });

    it('oublie la demi-trame à la réinitialisation', () => {
      const d = new DecoupeurDeTrames();
      d.pousser(new Uint8Array([0x3e, 0x05, 0x00, 0x01]));
      d.reinitialiser();
      expect(d.pousser(new Uint8Array([0x3e, 0x01, 0x00, 0x42])))
        .toEqual([new Uint8Array([0x42])]);
    });

    it('encadre une charge utile avec l\'octet du sens application → radio', () => {
      // 0x3c, PAS 0x3e : ce test attendait 0x3e jusqu'au 14/11/2026 et figeait l'erreur.
      expect(Array.from(encadrer(new Uint8Array([0xaa, 0xbb]))))
        .toEqual([0x3c, 0x02, 0x00, 0xaa, 0xbb]);
    });

    it('ignore un en-tête aberrant et se resynchronise', () => {
      const d = new DecoupeurDeTrames();
      // 0x3e suivi d'une taille de 0xffff : du bruit, pas une trame de 64 ko.
      expect(d.pousser(new Uint8Array([0x3e, 0xff, 0xff, 0x3e, 0x01, 0x00, 0x42])))
        .toEqual([new Uint8Array([0x42])]);
    });
  });

  /**
   * Octets produits par la bibliothèque Python `meshcore` elle-même (`SerialConnection.send`
   * appelé sur un faux transport, dans l'image du pont). C'est la seule vérification qui vaille :
   * un vecteur écrit à la main ne fait que répéter l'hypothèse de son auteur.
   */
  describe('vecteurs de la bibliothèque meshcore', () => {
    const hex = (o: Uint8Array) => octetsVersHex(o);

    it('APP_START est octet pour octet celui de la bibliothèque', () => {
      expect(hex(encadrer(commandeAppStart('mccli')))).toBe('3c0d0001032020202020206d63636c69');
    });

    it('DEVICE_QUERY, protocole v3', () => {
      expect(hex(encadrer(commandeRequeteAppareil()))).toBe('3c02001603');
    });

    it('SET_DEVICE_TIME', () => {
      expect(hex(encadrer(commandeHeure(1763100000)))).toBe('3c05000660c51669');
    });

    it('SYNC_NEXT_MESSAGE aussi', () => {
      expect(hex(encadrer(commandeSimple(CMD.SYNC_NEXT_MESSAGE)))).toBe('3c01000a');
    });

    it('et l\'envoi d\'un message direct', () => {
      const trame = encadrer(commandeEnvoiMessage('ee'.repeat(32), 'Rentrez à la base', 1763100000));
      expect(hex(trame)).toBe(
        '3c1f0002000060c51669eeeeeeeeeeee52656e7472657a20c3a0206c612062617365');
    });
  });

  describe('SELF_INFO', () => {
    it('lit la clé publique et le nom de la radio', () => {
      const charge = new Uint8Array(58 + 9);
      charge[0] = REP.SELF_INFO;
      for (let i = 0; i < 32; i++) { charge[4 + i] = i; }
      charge.set(new TextEncoder().encode('Heltec V3'), 58);

      const id = lireSelfInfo(charge);

      expect(id?.pubkeyHex).toBe(octetsVersHex(Uint8Array.from({ length: 32 }, (_, i) => i)));
      expect(id?.nom).toBe('Heltec V3');
    });

    it('refuse une trame trop courte plutôt que d\'inventer une clé', () => {
      expect(lireSelfInfo(new Uint8Array([REP.SELF_INFO, 1, 2, 3]))).toBeNull();
    });
  });

  describe('envoi d\'un message', () => {
    it('respecte la disposition relevée dans la bibliothèque', () => {
      // 0x02 0x00 | tentative | horodatage(4 LE) | destination(6) | texte
      const charge = commandeEnvoiMessage('a1b2c3d4e5f6' + '00'.repeat(26), 'ok', 0x01020304);

      expect(charge[0]).toBe(CMD.SEND_TXT_MSG);
      expect(charge[1]).toBe(0);
      expect(charge[2]).toBe(0);
      expect(Array.from(charge.slice(3, 7))).toEqual([0x04, 0x03, 0x02, 0x01]);
      expect(octetsVersHex(charge.slice(7, 13))).toBe('a1b2c3d4e5f6');
      expect(new TextDecoder().decode(charge.slice(13))).toBe('ok');
    });

    it('ne garde que les 6 premiers octets de la clé publique', () => {
      // La destination est un PRÉFIXE, pas la clé entière : envoyer 32 octets décalerait le
      // texte et la radio refuserait la commande.
      const charge = commandeEnvoiMessage('ff'.repeat(32), 'x');
      expect(charge.length).toBe(13 + 1);
    });

    it('refuse une clé trop courte plutôt que d\'envoyer une destination tronquée', () => {
      expect(() => commandeEnvoiMessage('a1b2', 'x')).toThrowError(/6 octets/);
    });
  });

  describe('message reçu', () => {
    function trameMessage(type: number, prefixe: string, texte: string): Uint8Array {
      const corps = new TextEncoder().encode(texte);
      const enTete = type === REP.CONTACT_MSG_RECV_V3 ? 4 : 1;
      const charge = new Uint8Array(enTete + 6 + 1 + 1 + 4 + corps.length);
      charge[0] = type;
      charge.set(hexVersOctets(prefixe), enTete);
      charge[enTete + 6] = 255;          // message direct
      charge[enTete + 7] = 0;            // texte simple
      new DataView(charge.buffer).setUint32(enTete + 8, 1234, true);
      charge.set(corps, enTete + 12);
      return charge;
    }

    it('lit le format classique', () => {
      const m = lireMessageRecu(trameMessage(REP.CONTACT_MSG_RECV, 'a1b2c3d4e5f6', 'coucou'));
      expect(m?.pubkeyPrefix).toBe('a1b2c3d4e5f6');
      expect(m?.texte).toBe('coucou');
      expect(m?.horodatageExpediteur).toBe(1234);
    });

    it('saute les trois octets de tête du format V3', () => {
      // SNR puis deux réservés. Les confondre décale tout le reste de la trame — c'est le
      // genre d'erreur qui produit des messages illisibles sans qu'on sache pourquoi.
      const m = lireMessageRecu(trameMessage(REP.CONTACT_MSG_RECV_V3, 'aabbccddeeff', 'salut'));
      expect(m?.pubkeyPrefix).toBe('aabbccddeeff');
      expect(m?.texte).toBe('salut');
    });

    it('ignore ce qui n\'est pas un message direct', () => {
      expect(lireMessageRecu(new Uint8Array([REP.NO_MORE_MSGS]))).toBeNull();
      expect(lireMessageRecu(new Uint8Array([REP.OK]))).toBeNull();
    });

    it('ne plante pas sur une trame tronquée', () => {
      expect(lireMessageRecu(new Uint8Array([REP.CONTACT_MSG_RECV, 0x01, 0x02]))).toBeNull();
    });
  });
});
