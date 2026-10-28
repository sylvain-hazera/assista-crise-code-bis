import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DeclareCrisisFormComponent } from './declare-crisis-form.component';
import { fournisseursDeTest } from '../../../testing/test-providers';

describe('DeclareCrisisFormComponent', () => {
  let component: DeclareCrisisFormComponent;
  let fixture: ComponentFixture<DeclareCrisisFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [DeclareCrisisFormComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(DeclareCrisisFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
