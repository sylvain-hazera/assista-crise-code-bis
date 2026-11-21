import { ComponentFixture, TestBed } from '@angular/core/testing';

import { OtherDeclarationFormComponent } from './other-declaration-form.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { AuthService } from '../../../auth/services/auth.service';

describe('OtherDeclarationFormComponent', () => {
  let component: OtherDeclarationFormComponent;
  let fixture: ComponentFixture<OtherDeclarationFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [OtherDeclarationFormComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(OtherDeclarationFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('préremplit les coordonnées de la personne connectée', () => {
    const auth = TestBed.inject(AuthService);
    spyOn(auth, 'getCurrentUser').and.returnValue({
      last_name: 'Perrin', first_name: 'Jeanne', email: 'jeanne@courriel.exemple', phone_number: '0612345678',
    } as any);
    component.initForm();
    expect(component.otherInformationForm.value.lastName).toBe('Perrin');
    expect(component.otherInformationForm.value.email).toBe('jeanne@courriel.exemple');
    expect(component.declareSafeForm.value.firstName).toBe('Jeanne');
  });

  it('ne redemande pas l\'adresse quand le lieu est choisi en haut', () => {
    const lieu = { label: '12 Rue de la République', latitude: 45.5, longitude: 4.6, citycode: '42186' } as any;
    component.onLieuSelectionneOther(lieu);
    expect(component.lieuChoisiEnHaut).toBeTrue();
    expect(component.hasLocationForOther()).toBeTrue();
    component.onLieuSelectionneOther(null);
    expect(component.lieuChoisiEnHaut).toBeFalse();
  });
});
