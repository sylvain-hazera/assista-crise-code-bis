import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { FooterComponent } from './footer.component';
import { BrandingService } from '../../../services/branding.service';

describe('FooterComponent', () => {
  let component: FooterComponent;
  let fixture: ComponentFixture<FooterComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [FooterComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    })
    .compileComponents();

    fixture = TestBed.createComponent(FooterComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('sur le domaine d\'une marque blanche, le pied de page porte son nom et son adresse de contact', () => {
    const texte = () => (fixture.nativeElement.textContent as string).replace(/\s+/g, ' ');
    expect(texte()).toContain('contact@assista-crise.fr');
    (TestBed.inject(BrandingService) as any).brandingSubject.next({
      nom_affichage: 'Réserve Résilience - Casques Jaunes', logo_url: null, couleur_primaire: '#3c4d81',
      couleur_secondaire: '#2ea3f2', police_titre: '', police_texte: '', reserve_active: true,
      email_contact: 'contact@reserve-resilience.org',
    });
    fixture.detectChanges();
    expect(texte()).toContain('contact@reserve-resilience.org');
    expect(texte()).not.toContain('assista-crise.fr');
    expect(texte()).toContain('Réserve Résilience - Casques Jaunes. Tous droits réservés.');
  });
});
