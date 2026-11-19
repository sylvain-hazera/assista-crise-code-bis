import { EcrivainProtobuf } from './protobuf-mini';
import { mesurerFromRadio } from './meshtastic-trames';
import { lireJournalRadio } from './meshcore-trames';
import { TamponMesures } from '../../services/relais-local.service';

/** Bits d'un float IEEE 754, pour l'écrire comme le firmware (fixed32). */
function bitsFlottant(v: number): number {
  const vue = new DataView(new ArrayBuffer(4));
  vue.setFloat32(0, v, true);
  return vue.getUint32(0, true);
}

function fromRadioTelemetrie(de: number, hopStart: number, hopLimit: number): Uint8Array {
  const appareil = new EcrivainProtobuf().varint(1, 87).fixed32(2, bitsFlottant(4.01))
    .fixed32(3, bitsFlottant(12.5)).fixed32(4, bitsFlottant(1.25)).varint(5, 3600);
  const telemetrie = new EcrivainProtobuf().fixed32(1, 1700000000).message(2, appareil);
  const data = new EcrivainProtobuf().varint(1, 67).message(2, telemetrie);
  const paquet = new EcrivainProtobuf().fixed32(1, de).message(4, data).varint(9, hopLimit).varint(15, hopStart);
  return new EcrivainProtobuf().message(2, paquet).fin();
}

describe('Mesures du relais navigateur (19/11/2026)', () => {
  it('lit la télémétrie et les sauts d’un paquet Meshtastic', () => {
    const m = mesurerFromRadio(fromRadioTelemetrie(0x1234, 7, 5))!;
    expect(m.type).toBe('TELEMETRY_APP');
    expect(m.de).toBe(0x1234);
    expect(m.sauts).toBe(2);
    expect(m.telemetrie).toEqual({
      node_num: 0x1234, horodatage: 1700000000, batterie: 87, tension: 4.01,
      occupation_canal: 12.5, temps_antenne_tx: 1.25, uptime_s: 3600,
    });
  });

  it('un paquet illisible est compté comme chiffré, une trame non-paquet est ignorée', () => {
    const paquet = new EcrivainProtobuf().fixed32(1, 9);
    const chiffre = new EcrivainProtobuf().message(2, paquet).fin();
    expect(mesurerFromRadio(chiffre)).toEqual({ type: 'CHIFFRE_CANAL_INCONNU', de: 9, sauts: null, telemetrie: null });
    expect(mesurerFromRadio(new EcrivainProtobuf().varint(7, 42).fin())).toBeNull();
    expect(mesurerFromRadio(new Uint8Array([0xff, 0xff]))).toBeNull();
  });

  it('lit une trame du journal radio MeshCore', () => {
    const t = lireJournalRadio(new Uint8Array([0x88, 0x1c, 0xb0, 0x11, 0x00, 0xaa]))!;
    expect(t.snr).toBe(7);
    expect(t.rssi).toBe(-80);
    expect(t.raw).toBe('1100aa');
    expect(lireJournalRadio(new Uint8Array([0x07, 0, 0, 0, 0]))).toBeNull();
  });

  it('le tampon compte par heure et par type, et garde un rapport refusé', () => {
    const tampon = new TamponMesures();
    const paquet = mesurerFromRadio(fromRadioTelemetrie(1, 3, 3))!;
    tampon.noter({ genre: 'paquet_meshtastic', paquet });
    tampon.noter({ genre: 'paquet_meshtastic', paquet });
    const corps = tampon.extraire()!;
    expect(corps.compteurs!.map(c => [c.type, c.nombre])).toEqual([['TELEMETRY_APP', 2]]);
    expect(corps.mesures!.length).toBe(2);
    expect(tampon.extraire()).toBeNull();
    tampon.remettre(corps);
    expect(tampon.extraire()!.mesures!.length).toBe(2);
  });
});
