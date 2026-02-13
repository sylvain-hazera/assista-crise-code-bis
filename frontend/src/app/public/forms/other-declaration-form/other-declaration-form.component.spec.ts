import { ComponentFixture, TestBed } from '@angular/core/testing';

import { OtherDeclarationFormComponent } from './other-declaration-form.component';

describe('OtherDeclarationFormComponent', () => {
  let component: OtherDeclarationFormComponent;
  let fixture: ComponentFixture<OtherDeclarationFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
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
