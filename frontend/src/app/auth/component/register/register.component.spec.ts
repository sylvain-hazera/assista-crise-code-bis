import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RegisterComponent } from './register.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { UserRole } from '../../../shared/models/user.model';

describe('RegisterComponent', () => {
  let component: RegisterComponent;
  let fixture: ComponentFixture<RegisterComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [RegisterComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(RegisterComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  /** Le prenom est demande a TOUT LE MONDE depuis le 11/11/2026.
   *
   * Il n'etait requis que pour un particulier, et `toggleFieldsBasedOnUserType` l'effacait et
   * le desactivait pour les comptes institutionnels : un responsable de mairie s'inscrivait
   * donc sous un seul patronyme, dans une plateforme ou l'on se nomme pour se coordonner. */
  describe('prenom et nom', () => {

    it('les deux sont requis des l\'ouverture du formulaire', () => {
      const prenom = component.registerForm.get('firstName')!;
      const nom = component.registerForm.get('lastName')!;
      prenom.setValue('');
      nom.setValue('');
      expect(prenom.hasError('required')).toBeTrue();
      expect(nom.hasError('required')).toBeTrue();
    });

    for (const type of [UserRole.SIMPLE_USER, UserRole.LOCAL_AUTH, UserRole.RESCUE]) {
      it(`reste requis et actif pour un compte ${type}`, () => {
        component.registerForm.get('userType')!.setValue(type);
        const prenom = component.registerForm.get('firstName')!;
        // Ni efface, ni desactive : c'est exactement ce que faisait l'ancien code pour tout
        // type autre que particulier.
        expect(prenom.enabled).toBeTrue();
        prenom.setValue('');
        expect(prenom.hasError('required')).toBeTrue();
      });
    }

    it('changer de type de compte n\'efface pas un prenom deja saisi', () => {
      component.registerForm.get('firstName')!.setValue('Jean');
      component.registerForm.get('userType')!.setValue(UserRole.LOCAL_AUTH);
      expect(component.registerForm.get('firstName')!.value).toBe('Jean');
    });
  });
});
