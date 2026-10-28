import { ComponentFixture, TestBed } from '@angular/core/testing';

import { InstitutionsComponent } from './institutions.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('InstitutionsComponent', () => {
  let component: InstitutionsComponent;
  let fixture: ComponentFixture<InstitutionsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InstitutionsComponent],
      providers: fournisseursDeTest()
    })
    .compileComponents();

    fixture = TestBed.createComponent(InstitutionsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
