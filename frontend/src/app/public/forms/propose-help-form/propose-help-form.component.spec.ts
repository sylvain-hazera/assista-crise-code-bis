import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ProposeHelpFormComponent } from './propose-help-form.component';
import { fournisseursDeTest } from '../../../testing/test-providers';

describe('ProposeHelpFormComponent', () => {
  let component: ProposeHelpFormComponent;
  let fixture: ComponentFixture<ProposeHelpFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [ProposeHelpFormComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ProposeHelpFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
