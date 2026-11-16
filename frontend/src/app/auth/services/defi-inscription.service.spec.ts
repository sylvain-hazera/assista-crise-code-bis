import { HttpErrorResponse } from '@angular/common/http';
import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';
import { fournisseursDeTest } from '../../testing/test-providers';
import { DefiInscription, DefiResolu, sha256Hex } from './defi-calcul';
import { DefiInscriptionService } from './defi-inscription.service';

const URL = '/inscription/defi/';

function defi(nombre: number, niveau = 'NORMAL'): DefiInscription {
  const sel = `sel${nombre}`;
  return { sel, empreinte: sha256Hex(`${sel}${nombre}`), maximum: 50, emis: 1, expire: 2, niveau, signature: 's' };
}

/** Laisse passer les promesses et les pauses du calcul. */
const attendre = () => new Promise<void>((suite) => setTimeout(suite, 20));

describe('DefiInscriptionService', () => {
  let service: DefiInscriptionService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
    service = TestBed.inject(DefiInscriptionService);
    http = TestBed.inject(HttpTestingController);
  });

  const servirDefi = (d: DefiInscription) => http.expectOne((r) => r.url.endsWith(URL)).flush(d);

  it("résout le défi pendant que la personne remplit le formulaire, et le joint à l'envoi", async () => {
    service.preparer();
    servirDefi(defi(7));
    await attendre();

    let recu: DefiResolu | null = null;
    const reponse = await new Promise((fin) => service.avecDefi((d) => { recu = d; return of('créé'); }).subscribe(fin));

    expect(reponse).toBe('créé');
    expect(recu!.nombre).toBe(7);
    expect(recu!.signature).toBe('s');
    http.verify();          // aucun second défi demandé après une réussite
  });

  it('redemande un défi et renvoie le même formulaire quand le serveur répond 428', async () => {
    service.preparer();
    servirDefi(defi(3));
    await attendre();

    const envois: number[] = [];
    const envoyer = (d: DefiResolu | null): Observable<string> => {
      envois.push(d!.nombre);
      return envois.length === 1
        ? throwError(() => new HttpErrorResponse({ status: 428 }))
        : of('créé');
    };
    const fin = new Promise((ok) => service.avecDefi(envoyer).subscribe(ok));
    await attendre();
    expect(service.verification()).withContext('la personne lit « vérification en cours »').toBeTrue();
    servirDefi(defi(41, 'ELEVE'));

    expect(await fin).toBe('créé');
    expect(envois).toEqual([3, 41]);
    expect(service.verification()).toBeFalse();
  });

  it("laisse remonter une erreur de saisie et prépare le défi de l'envoi suivant", async () => {
    service.preparer();
    servirDefi(defi(5));
    await attendre();

    const erreur = await new Promise<HttpErrorResponse>((ko) => service
      .avecDefi(() => throwError(() => new HttpErrorResponse({ status: 400 })))
      .subscribe({ error: ko }));

    expect(erreur.status).toBe(400);
    servirDefi(defi(9));    // un défi ne sert qu'une fois : le suivant est déjà demandé
  });

  it("n'insiste pas indéfiniment si le serveur redemande toujours un défi", async () => {
    service.preparer();
    servirDefi(defi(1));
    await attendre();

    let envois = 0;
    const fin = new Promise<HttpErrorResponse>((ko) => service
      .avecDefi(() => { envois++; return throwError(() => new HttpErrorResponse({ status: 428 })); })
      .subscribe({ error: ko }));
    for (const n of [2, 3]) { await attendre(); servirDefi(defi(n)); }

    expect((await fin).status).toBe(428);
    expect(envois).toBe(3);
    await attendre();
    servirDefi(defi(4));
  });

  it("envoie sans défi quand le serveur n'en fournit pas (satellite pas encore à jour)", async () => {
    service.preparer();
    http.expectOne((r) => r.url.endsWith(URL)).flush('', { status: 404, statusText: 'Not Found' });
    await attendre();

    let recu: DefiResolu | null | undefined;
    await new Promise((fin) => service.avecDefi((d) => { recu = d; return of('créé'); }).subscribe(fin));

    expect(recu).toBeNull();
  });
});
