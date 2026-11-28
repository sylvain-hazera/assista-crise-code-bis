import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { courbe, OuvertReseauComponent } from './ouvert-reseau.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('OuvertReseauComponent', () => {
  it('trace une courbe sur une échelle qui contient le seuil', () => {
    const c = courbe([{ t: '2026-11-28T00:00:00Z', v: 5 }, { t: '2026-11-28T12:00:00Z', v: 10 }], 50);
    expect(c.max).toBe(50);
    expect(c.trace.startsWith('M0.0,')).toBeTrue();
    expect(c.dernier?.x).toBe(300);
    expect(courbe([{ t: '2026-11-28T00:00:00Z', v: 5 }]).trace).toBe('');
  });

  it('affiche les mesures agrégées, sans rien qui identifie une passerelle', () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting(), provideRouter([])], imports: [OuvertReseauComponent] });
    const fixture = TestBed.createComponent(OuvertReseauComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/carte-ouverte/radio/sante/')).flush({
      calcule_le: '2026-11-28T09:00:00Z',
      meshtastic: { passerelles: 'plusieurs', occupation_canal: [{ t: '2026-11-28T08:00:00Z', v: 12 }, { t: '2026-11-28T08:30:00Z', v: 31 }],
        occupation_actuelle: 31, temps_antenne_tx: [], paquets_par_heure: [], par_type: [{ type: 'TEXT_MESSAGE_APP', nombre: 30 }, { type: 'POSITION_APP', nombre: 10 }] },
      meshcore: { trames_24h: 1200, par_type: [], courbe: [], repeteurs_publics: 148, repeteurs_vus_24h: 97 },
    });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.valeur.charge')?.textContent).toContain('31');
    expect(el.textContent).toContain('Messages');
    expect(el.textContent).toContain('75 %');
    expect(el.textContent).toContain('148');
  });
});
