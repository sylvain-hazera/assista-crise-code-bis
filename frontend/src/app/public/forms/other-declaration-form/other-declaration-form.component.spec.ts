import { ComponentFixture, TestBed } from '@angular/core/testing';

import { OtherDeclarationFormComponent } from './other-declaration-form.component';
import { fournisseursDeTest } from '../../../testing/test-providers';

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
});
